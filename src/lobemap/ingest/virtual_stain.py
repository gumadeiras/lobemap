"""Virtual neuropil stain: a synapse-density map at light-microscopy resolution.

Method (Bates et al. 2026, as described): downsample and Gaussian-blur
predicted synapse locations, sigma ~= 900 nm, to approximate the resolution of
the LM data behind the Drosophila standard templates.

That is a **binned 3D Gaussian KDE**. Evaluating a true KDE over 10^7-10^9
voxels is infeasible, and binning first is the standard approximation: the
effective kernel becomes Gaussian convolved with a voxel-wide box, so the
effective bandwidth is sqrt(sigma^2 + h^2/12) = 911 nm for sigma 900 nm and
h 500 nm -- a 1.3% inflation, negligible.

Two deliberate choices:

**Presynapses only** (decided 2026-09-21). nc82 labels Bruchpilot at
presynaptic active zones, so a presynapse density map is the same underlying
signal rather than a substitute. Counting synaptic *connections* instead would
weight each T-bar by its number of postsynaptic partners, which fly synapses
have several of and which nc82 does not do.

**From the full detected synapse list, not proofread-linked connections.**
Roughly 60% of detected synapses are not assigned to proofread neurons, mostly
postsynapses on fine twigs. Starting from proofread connections would make the
stain biased rather than merely sparser: brightest where tracing was most
complete rather than where synapses are. Sources are the published
buckets; see `synapse_buckets`.

**The bandwidth is an instrument constant, not a fitted parameter.** A
data-driven bandwidth rule gives roughly n^(-1/7) in 3D, which at 10^7
synapses is far smaller than 900 nm. This is deliberately over-smoothed
relative to density-estimation optimality, because the goal is to forge a
point-spread function, not to estimate density well. So sigma is fixed and
recorded, never tuned.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime

import numpy as np

from ..core.imagefmt import Volume

#: Target grid, matching the JRC2018 templates the method aims at.
DEFAULT_VOXEL_UM = 0.5
#: Point-spread width the method specifies.
DEFAULT_SIGMA_UM = 0.9
#: Stored sample type. 8-bit matches the confocal stacks this emulates --
#: `grabe2015_stack` is uint8 -- and halves the
#: whole-brain grids. What it discards is the faint outer skirt of the blur:
#: the voxels it rounds away all sit below 0.2% of peak.
DEFAULT_DTYPE = np.uint8
#: Above this many voxels the grid no longer fits in RAM and the build goes
#: slab by slab through disk. The 0.5 um whole-brain grids sit below it; the
#: 0.25 um ones are 2-5 G voxels and sit far above.
SLABWISE_THRESHOLD_VOXELS = 400_000_000

#: Published confidence thresholds, per source. Recorded in the Derivation so
#: a different choice is visible rather than implicit.
DEFAULT_CONFIDENCE = {
    "neuprint": 0.5,      # hemibrain / male CNS synapse confidence
    "flywire": 50.0,      # FlyWire cleft_score, the published recommendation
}


@dataclass
class StainStats:
    n_points: int = 0
    n_outside: int = 0
    batches: int = 0
    notes: list[str] = field(default_factory=list)


class StainAccumulator:
    """Streaming 3D histogram over a fixed grid.

    Counts are accumulated with `np.bincount` over flattened voxel indices, so
    memory stays at one grid plus one batch rather than one grid per batch.
    """

    def __init__(
        self,
        origin_um: np.ndarray,
        voxel_um: float,
        shape: tuple[int, int, int],
        dtype=np.float32,
    ) -> None:
        self.origin_um = np.asarray(origin_um, dtype=float)
        self.voxel_um = float(voxel_um)
        self.shape = tuple(int(n) for n in shape)
        self.counts = np.zeros(self.shape, dtype=dtype)
        self.stats = StainStats()

    @property
    def n_voxels(self) -> int:
        return int(np.prod(self.shape))

    def add(self, points_um: np.ndarray) -> None:
        pts = np.asarray(points_um, dtype=float)
        if not len(pts):
            return
        idx = np.floor((pts - self.origin_um) / self.voxel_um).astype(np.int64)
        keep = np.all((idx >= 0) & (idx < np.asarray(self.shape)), axis=1)
        self.stats.n_points += len(pts)
        self.stats.n_outside += int((~keep).sum())
        if not keep.any():
            self.stats.batches += 1
            return
        idx = idx[keep]
        flat = np.ravel_multi_index((idx[:, 0], idx[:, 1], idx[:, 2]), self.shape)
        self.counts += np.bincount(flat, minlength=self.n_voxels).reshape(
            self.shape
        ).astype(self.counts.dtype)
        self.stats.batches += 1

    def blurred(self, sigma_um: float = DEFAULT_SIGMA_UM) -> np.ndarray:
        """Separable Gaussian, in voxels. Edges use 'nearest' so the volume
        boundary does not darken artificially."""
        from scipy.ndimage import gaussian_filter

        sigma_vox = sigma_um / self.voxel_um
        return gaussian_filter(self.counts, sigma=sigma_vox, mode="nearest")


def effective_sigma_um(sigma_um: float, voxel_um: float) -> float:
    """Bandwidth after binning: Gaussian convolved with a voxel-wide box."""
    return float(np.sqrt(sigma_um**2 + (voxel_um**2) / 12.0))


def grid_for_bounds(
    lo_um, hi_um, voxel_um: float = DEFAULT_VOXEL_UM, pad_um: float = 5.0
):
    """Origin and shape covering `lo..hi` with a margin for the blur tail."""
    lo = np.asarray(lo_um, dtype=float) - pad_um
    hi = np.asarray(hi_um, dtype=float) + pad_um
    shape = tuple(int(np.ceil(n)) for n in ((hi - lo) / voxel_um))
    return lo, shape


def build_stain(
    batches: Iterator[np.ndarray],
    lo_um,
    hi_um,
    space: str,
    source: str,
    voxel_um: float = DEFAULT_VOXEL_UM,
    sigma_um: float = DEFAULT_SIGMA_UM,
    confidence: float | None = None,
    extra_meta: dict | None = None,
    dtype=DEFAULT_DTYPE,
    workdir=None,
    on_stage=None,
) -> tuple[Volume, StainStats]:
    """Accumulate presynapse batches into a blurred density Volume.

    Grids past `SLABWISE_THRESHOLD_VOXELS` are handed to the disk-backed
    builder, which needs somewhere to work; without a `workdir` this raises
    rather than attempting an allocation that would take the machine down.
    """
    origin, shape = grid_for_bounds(lo_um, hi_um, voxel_um)
    n_voxels = int(np.prod(shape, dtype=np.int64))
    if n_voxels > SLABWISE_THRESHOLD_VOXELS:
        if workdir is None:
            raise ValueError(
                f"grid is {n_voxels:,} voxels ({n_voxels * 4 / 1e9:.1f} GB as "
                f"float32); pass workdir= to build it slab by slab"
            )
        return build_stain_slabwise(
            batches, lo_um, hi_um, space, source, workdir,
            voxel_um=voxel_um, sigma_um=sigma_um, confidence=confidence,
            extra_meta=extra_meta, dtype=dtype, on_stage=on_stage,
        )
    acc = StainAccumulator(origin, voxel_um, shape)
    for batch in batches:
        acc.add(batch)

    density = acc.blurred(sigma_um)
    peak = float(density.max())
    # The scale factor is recorded, so raw density is recoverable whatever
    # the stored type.
    hi = float(np.iinfo(dtype).max)
    scale = (hi / peak) if peak > 0 else 1.0
    data = np.clip(density * scale, 0, hi).astype(dtype)

    meta = _stain_meta(space, source, voxel_um, sigma_um, confidence,
                       acc.stats, scale, peak, extra_meta, dtype)
    return Volume(data=data, voxel_um=(voxel_um,) * 3, origin_um=tuple(origin),
                  meta=meta), acc.stats


def _stain_meta(space, source, voxel_um, sigma_um, confidence, stats, scale,
                peak, extra_meta=None, dtype=DEFAULT_DTYPE) -> dict:
    meta = {
        "source": "virtual_stain",
        "space": space,
        "role": "virtual_stain",
        "units": "um",
        "derivation": {
            "recipe": "synapse_density",
            "params": {
                "synapse_source": source,
                "synapse_type": "pre",
                "confidence_threshold": confidence,
                "voxel_um": voxel_um,
                "sigma_um": sigma_um,
                "effective_sigma_um": effective_sigma_um(sigma_um, voxel_um),
                "blur_mode": "nearest",
                "n_synapses": stats.n_points,
                "n_outside_grid": stats.n_outside,
                "intensity_scale": scale,
                "peak_density": peak,
                "dtype": np.dtype(dtype).name,
            },
        },
        "retrieved": datetime.now(UTC).date().isoformat(),
    }
    meta.update(extra_meta or {})
    return meta


def build_stain_slabwise(
    batches: Iterator[np.ndarray],
    lo_um,
    hi_um,
    space: str,
    source: str,
    workdir,
    voxel_um: float = DEFAULT_VOXEL_UM,
    sigma_um: float = DEFAULT_SIGMA_UM,
    confidence: float | None = None,
    extra_meta: dict | None = None,
    dtype=DEFAULT_DTYPE,
    on_stage=None,
) -> tuple[Volume, StainStats]:
    """Same stain, built through disk for grids that cannot fit in RAM.

    Identical arithmetic to `build_stain` -- same bins, same kernel, same
    uint16 scaling -- so the two agree to rounding on a grid small enough for
    both. `tests/test_stain_slabs.py` pins that.
    """
    from pathlib import Path

    from . import stain_slabs as ss

    work = Path(workdir)
    work.mkdir(parents=True, exist_ok=True)
    origin, shape = grid_for_bounds(lo_um, hi_um, voxel_um)
    halo = ss.blur_radius_vox(sigma_um, voxel_um) + 1
    slab_w = ss.slab_width(shape, halo)

    stats = StainStats()
    part = ss.partition_points(batches, origin, voxel_um, shape, work,
                               slab_w, stats, on_stage=on_stage)
    try:
        blur_path = work / "blurred.f32.npy"
        peak = ss.blur_to_memmap(part, shape, halo, sigma_um / voxel_um,
                                 blur_path, on_stage=on_stage)
        scale = (float(np.iinfo(dtype).max) / peak) if peak > 0 else 1.0
        data = ss.rescale_to_dtype(blur_path, work / "data.int.npy", shape,
                                   scale, dtype=dtype)
    finally:
        part.cleanup()

    stats.notes.append(
        f"slabwise: {part.n_slabs} slabs of {slab_w} voxels, halo {halo}"
    )
    meta = _stain_meta(space, source, voxel_um, sigma_um, confidence, stats,
                       scale, peak, extra_meta, dtype)
    return Volume(data=data, voxel_um=(voxel_um,) * 3, origin_um=tuple(origin),
                  meta=meta), stats
