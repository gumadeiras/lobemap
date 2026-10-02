"""Slab-partitioned stain builder, for grids too large to hold in RAM.

The whole-brain stains at 0.25 um are 2-5 G voxels each, which the in-RAM
builder cannot touch: `np.bincount(..., minlength=n_voxels)` alone wants an
int64 temporary of 8 bytes per voxel -- 39 GB for the male CNS grid.

The way out is to notice that **the point cloud is far smaller than the grid
it fills**: 35 M presynapses are 420 MB as int32 voxel indices, against 19.6 GB
for the grid. So partition the points by slab, spill them to disk, then bin and
blur one slab at a time. That also avoids scattered writes into a multi-GB
memmap, which is what makes the naive version unusable rather than merely slow.

The blur stays exact. A Gaussian is separable, so a slab that spans all of y
and z is already exact in those axes; along the partition axis it needs a halo
of the kernel's true reach, `truncate * sigma` voxels. Slabs are forced wider
than that halo, so three consecutive point files always cover one slab's
working block, and `mode="nearest"` at a block edge only ever affects voxels
inside the halo, which are cropped away. At the volume's real boundary the
block edge *is* the volume edge, which is what the whole-array version does
there too.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import numpy as np

#: RAM for one working slab. The filter allocates its own output, so a block
#: is counted twice.
SLAB_BUDGET_BYTES = 1_200_000_000


def blur_radius_vox(sigma_um: float, voxel_um: float, truncate: float = 4.0) -> int:
    """Half-width scipy's Gaussian actually touches, in voxels.

    Matches `scipy.ndimage.gaussian_filter`'s own rule, so the halo is the
    kernel's real reach rather than a guess.
    """
    return int(truncate * (sigma_um / voxel_um) + 0.5)


class SlabPartition:
    """Presynapse voxel indices spilled to one int32 file per slab."""

    def __init__(self, workdir: str | Path, shape, slab_w: int) -> None:
        self.dir = Path(workdir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.shape = tuple(int(n) for n in shape)
        self.slab_w = int(slab_w)
        self.n_slabs = -(-self.shape[0] // self.slab_w)
        self.n_written = 0
        self._fh: dict[int, object] = {}

    def _path(self, s: int) -> Path:
        return self.dir / f"slab{s:05d}.i32"

    def add(self, idx: np.ndarray) -> None:
        """Append in-grid voxel indices, routed to their slab's file."""
        if not len(idx):
            return
        rows = np.ascontiguousarray(idx, dtype=np.int32)
        slab = rows[:, 0] // self.slab_w
        order = np.argsort(slab, kind="stable")
        rows, slab = rows[order], slab[order]
        edges = np.searchsorted(slab, np.arange(self.n_slabs + 1))
        for s in range(self.n_slabs):
            a, b = int(edges[s]), int(edges[s + 1])
            if b <= a:
                continue
            fh = self._fh.get(s)
            if fh is None:
                fh = self._path(s).open("wb")
                self._fh[s] = fh
            fh.write(np.ascontiguousarray(rows[a:b]).tobytes())
            self.n_written += b - a

    def close(self) -> None:
        for fh in self._fh.values():
            fh.close()
        self._fh.clear()

    def read(self, s0: int, s1: int) -> np.ndarray:
        """Every index in slabs [s0, s1), as one (n, 3) int32 array."""
        out = []
        for s in range(max(0, s0), min(self.n_slabs, s1)):
            p = self._path(s)
            if p.exists():
                out.append(np.fromfile(p, dtype=np.int32).reshape(-1, 3))
        return np.vstack(out) if out else np.empty((0, 3), dtype=np.int32)

    def cleanup(self) -> None:
        self.close()
        for p in self.dir.glob("slab*.i32"):
            p.unlink(missing_ok=True)


def slab_width(shape, halo: int, budget: int | None = None) -> int:
    """Widest slab fitting the budget, but never narrower than the halo.

    Two float32 blocks are counted: the counts and the filter's output.
    The budget is read at call time, not bound as a default, so lowering
    `SLAB_BUDGET_BYTES` on a smaller machine actually takes effect.
    """
    budget = SLAB_BUDGET_BYTES if budget is None else budget
    plane = int(shape[1]) * int(shape[2]) * 4
    fits = int(budget // (2 * plane)) - 2 * halo
    return int(min(int(shape[0]), max(2 * halo, fits)))


def partition_points(
    batches: Iterator[np.ndarray],
    origin: np.ndarray,
    voxel_um: float,
    shape,
    workdir: str | Path,
    slab_w: int,
    stats,
    on_stage=None,
) -> SlabPartition:
    """Stream batches straight to per-slab index files."""
    part = SlabPartition(Path(workdir) / "points", shape, slab_w)
    shape_arr = np.asarray(shape)
    for batch in batches:
        pts = np.asarray(batch, dtype=float)
        stats.batches += 1
        stats.n_points += len(pts)
        if not len(pts):
            continue
        idx = np.floor((pts - origin) / voxel_um).astype(np.int64)
        keep = np.all((idx >= 0) & (idx < shape_arr), axis=1)
        stats.n_outside += int((~keep).sum())
        part.add(idx[keep])
        del pts, idx, keep
    part.close()
    if on_stage is not None:
        on_stage("partitioned", part.n_slabs, part.n_written)
    return part


def blur_to_memmap(
    part: SlabPartition,
    shape,
    halo: int,
    sigma_vox: float,
    out_path: str | Path,
    on_stage=None,
) -> float:
    """Bin and blur slab by slab into a float32 memmap; return its peak.

    Slabs are wider than the halo, so slabs s-1, s and s+1 always cover the
    working block -- that invariant is what `slab_width` protects.
    """
    from numpy.lib.format import open_memmap
    from scipy.ndimage import gaussian_filter

    nx, ny, nz = (int(n) for n in shape)
    blurred = open_memmap(out_path, mode="w+", dtype=np.float32,
                          shape=(nx, ny, nz))
    peak = 0.0
    for s in range(part.n_slabs):
        a, b = s * part.slab_w, min(nx, (s + 1) * part.slab_w)
        lo_i, hi_i = max(0, a - halo), min(nx, b + halo)
        block = np.zeros((hi_i - lo_i, ny, nz), dtype=np.float32)

        idx = part.read(s - 1, s + 2)
        if len(idx):
            m = (idx[:, 0] >= lo_i) & (idx[:, 0] < hi_i)
            sub = idx[m].astype(np.int64, copy=False)
            if len(sub):
                flat = ((sub[:, 0] - lo_i) * ny + sub[:, 1]) * nz + sub[:, 2]
                u, c = np.unique(flat, return_counts=True)
                # Assignment, not +=: np.unique already collapsed duplicates
                # and the block starts at zero.
                block.reshape(-1)[u] = c
                del flat, u, c
            del sub, m
        del idx

        block = gaussian_filter(block, sigma=sigma_vox, mode="nearest")
        keep = block[a - lo_i:(a - lo_i) + (b - a)]
        peak = max(peak, float(keep.max()))
        blurred[a:b] = keep
        del block, keep
        if on_stage is not None:
            on_stage("blurred", s + 1, part.n_slabs)

    blurred.flush()
    del blurred
    return peak


def rescale_to_dtype(
    blur_path: str | Path,
    out_path: str | Path,
    shape,
    scale: float,
    dtype=np.uint8,
    budget: int | None = None,
) -> np.ndarray:
    """Stream the float32 density into the integer type the asset stores."""
    from numpy.lib.format import open_memmap

    budget = SLAB_BUDGET_BYTES if budget is None else budget
    nx, ny, nz = (int(n) for n in shape)
    hi = float(np.iinfo(dtype).max)
    src = np.load(blur_path, mmap_mode="r")
    dst = open_memmap(out_path, mode="w+", dtype=dtype, shape=(nx, ny, nz))
    step = max(1, int(budget // (ny * nz * 8)))
    for a in range(0, nx, step):
        b = min(nx, a + step)
        dst[a:b] = np.clip(np.asarray(src[a:b]) * scale, 0, hi).astype(dtype)
    dst.flush()
    del src, dst
    return np.load(out_path, mmap_mode="r")
