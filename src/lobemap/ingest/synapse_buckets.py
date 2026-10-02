"""Presynapse locations from the published bulk releases.

These are the sources for the virtual stain. neuPrint is not: roughly 60% of
detected synapses are not assigned to proofread neurons, mostly postsynapses
on fine twigs, so anything reached through neuron criteria is biased toward
well-traced regions rather than merely sparser. Measured, not assumed:
the bucket and neuPrint counts differ by that margin in every dataset.

Three sources, three shapes:

- **hemibrain** -- `gs://neuroglancer-janelia-flyem-hemibrain/v1.2/synapses/by_id/`,
  8 sharded neuroglancer LINE annotations. Only `by_id` is the full detected
  set; `pre_synaptic_cell/` and `post_synaptic_cell/` index assigned synapses
  only. One annotation per (T-bar, PSD) pair, so T-bars repeat and must be
  deduplicated.
- **male CNS** -- a feather table of individual points with a `kind` column.
  Rows are already unique points; no deduplication.
- **FAFB** -- a CSV of synapse *pairs*, so `pre_*` repeats and must be
  deduplicated.

Units are never assumed. `infer_point_scale` picks the scale whose resulting
extent matches the target template's bounding box, and refuses when the answer
is ambiguous.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import numpy as np

#: Candidate scales from source units into micrometers.
SCALE_CANDIDATES = [
    (8e-3, "px8nm"),
    (1e-3, "nm"),
    (4e-3, "px4nm"),
    (1.0, "um"),
]


def template_extent_um(template_name: str) -> np.ndarray:
    import flybrains

    template = getattr(flybrains, template_name)
    box = np.asarray(template.boundingbox, dtype=float).reshape(3, 2)
    units = str(template.units[0] if isinstance(template.units, (list, tuple))
                else template.units).lower()
    scale = 1e-3 if "nano" in units else 1.0
    return (box[:, 1] - box[:, 0]) * scale


def infer_point_scale(
    points: np.ndarray,
    template_name: str,
    tolerance: float = 0.35,
    sample: int = 200_000,
) -> tuple[float, str]:
    """Identify source units by matching extent against the template box.

    Compares the 0.1-99.9 percentile extent, so a few stray points cannot
    swing the answer. Raises when no candidate fits or several do -- an
    ambiguous answer is worse than none.
    """
    pts = np.asarray(points, dtype=float)
    if len(pts) > sample:
        idx = np.random.default_rng(0).choice(len(pts), sample, replace=False)
        pts = pts[idx]
    lo = np.percentile(pts, 0.1, axis=0)
    hi = np.percentile(pts, 99.9, axis=0)
    span = hi - lo
    expect = template_extent_um(template_name)

    hits, detail = [], []
    for scale, label in SCALE_CANDIDATES:
        got = span * scale
        # Compare the largest dimension; orientation may differ from the
        # template's axis order, so per-axis matching is not safe here.
        ratio = float(np.max(got)) / float(np.max(expect))
        detail.append(f"{label}->{np.max(got):.0f}um (x{ratio:.2f})")
        if abs(ratio - 1.0) <= tolerance:
            hits.append((scale, label))
    if len(hits) == 1:
        return hits[0]
    joined = ", ".join(detail)
    if not hits:
        raise ValueError(
            f"cannot identify units against {template_name} "
            f"(expect max {np.max(expect):.0f} um): {joined}"
        )
    raise ValueError(f"ambiguous units: {[h[1] for h in hits]} ({joined})")


def _unique_rows(points: np.ndarray) -> np.ndarray:
    """Distinct 3D points, preserving dtype. Used to collapse T-bars."""
    if not len(points):
        return points
    view = np.ascontiguousarray(points).view(
        np.dtype((np.void, points.dtype.itemsize * points.shape[1]))
    )
    _vals, idx = np.unique(view.ravel(), return_index=True)
    return points[np.sort(idx)]


# -- hemibrain ----------------------------------------------------------


def hemibrain_shard_presynapses(shard_path: Path, spec) -> np.ndarray:
    """Distinct presynaptic points from one `by_id` shard, in source units.

    Each annotation is LINE geometry: 6 float32, point A then point B. A is
    presynaptic -- verified rather than assumed, by the polyadic signature:
    in shard 0, A is 66% unique and B is 100% unique (a T-bar serves many
    PSDs, a PSD belongs to one).
    """
    from cloudvolume.datasource.precomputed.sharding import ShardReader

    reader = ShardReader(None, None, spec)
    items = reader.disassemble_shard(Path(shard_path).read_bytes())
    n = len(items)
    pre = np.empty((n, 3), dtype="<f4")
    for i, raw in enumerate(items.values()):
        pre[i] = np.frombuffer(raw[:12], dtype="<f4")
    del items
    return _unique_rows(pre)


def hemibrain_presynapses(
    shard_dir: str | Path,
    info: dict | None = None,
    progress=None,
) -> Iterator[np.ndarray]:
    """Yield presynapse positions in micrometers, one batch per shard.

    Deduplication is global: the same T-bar appears in every shard holding one
    of its PSDs, so per-shard uniqueness is not enough. Shards are collapsed
    individually to keep memory bounded, then unioned once at the end.
    """
    import requests
    from cloudvolume.datasource.precomputed.sharding import ShardingSpecification

    if info is None:
        info = requests.get(
            "https://storage.googleapis.com/neuroglancer-janelia-flyem-hemibrain"
            "/v1.2/synapses/info",
            timeout=60,
        ).json()
    spec = ShardingSpecification.from_dict(info["by_id"]["sharding"])

    shards = sorted(Path(shard_dir).glob("*.shard"))
    if not shards:
        raise FileNotFoundError(f"no .shard files in {shard_dir}")

    collected = []
    for i, shard in enumerate(shards):
        pre = hemibrain_shard_presynapses(shard, spec)
        collected.append(pre)
        if progress is not None:
            progress(i + 1, len(shards), len(pre))

    allpts = _unique_rows(np.vstack(collected))
    del collected
    scale, _label = infer_point_scale(allpts, "JRCFIB2018F")
    yield allpts.astype(np.float64) * scale


# -- male CNS -----------------------------------------------------------


def malecns_presynapses(
    feather_path: str | Path,
    batch_size: int = 8_000_000,
    progress=None,
) -> Iterator[np.ndarray]:
    """Yield presynapse positions in micrometers from the syn-points feather.

    Rows are individual points with a `kind` of PreSyn or PostSyn, so no
    deduplication is needed. The columns are stored in the order z, y, x and
    are read by NAME into (x, y, z) -- verified, not assumed: with that order
    93.2% of in-bbox presynapses fall inside the AL neuropil mesh, against a
    30.4% bbox fill fraction and 11.9% for the next-best permutation.
    """
    import pyarrow.compute as pc
    from pyarrow import feather

    table = feather.read_table(
        feather_path, columns=["x", "y", "z", "kind"], memory_map=True
    )
    mask = pc.equal(table.column("kind"), "PreSyn")
    table = table.filter(mask).drop_columns(["kind"])
    total = table.num_rows

    # Sample ACROSS the table, not from its head: the rows are spatially
    # ordered, so the first 400k span only ~210 um of a ~1077 um volume and
    # unit inference from them fails outright.
    rng = np.random.default_rng(0)
    idx = np.sort(rng.choice(total, min(500_000, total), replace=False))
    sample = table.take(idx)
    sample_xyz = np.column_stack([
        sample.column(c).to_numpy(zero_copy_only=False) for c in ("x", "y", "z")
    ]).astype(float)
    scale, _label = infer_point_scale(sample_xyz, "JRCFIB2022M")
    del sample, sample_xyz

    for start in range(0, total, batch_size):
        chunk = table.slice(start, batch_size)
        pts = np.column_stack([
            chunk.column(c).to_numpy(zero_copy_only=False) for c in ("x", "y", "z")
        ]).astype(np.float64)
        if progress is not None:
            progress(start // batch_size + 1,
                     -(-total // batch_size), len(pts))
        yield pts * scale


# -- FAFB ---------------------------------------------------------------


def fafb_presynapses(
    csv_path: str | Path,
    block_size: int = 1 << 26,
    progress=None,
) -> Iterator[np.ndarray]:
    """Yield presynapse positions in micrometers from the Princeton table.

    One row is one (pre, post) pair, so `pre_*` repeats once per postsynaptic
    partner and must be collapsed -- otherwise every T-bar is weighted by its
    partner count, which is exactly what counting connections would do.
    """
    import pyarrow as pa
    from pyarrow import csv as pacsv

    columns = ["pre_x", "pre_y", "pre_z"]
    reader = pacsv.open_csv(
        str(csv_path),
        read_options=pacsv.ReadOptions(block_size=block_size),
        convert_options=pacsv.ConvertOptions(
            include_columns=columns,
            column_types={c: pa.int32() for c in columns},
        ),
    )

    collected, n_rows, n_batches = [], 0, 0
    for batch in reader:
        pts = np.column_stack([
            batch.column(c).to_numpy(zero_copy_only=False) for c in columns
        ])
        n_rows += len(pts)
        n_batches += 1
        collected.append(_unique_rows(pts))
        if progress is not None and n_batches % 20 == 0:
            progress(n_batches, -1, n_rows)

    allpts = _unique_rows(np.vstack(collected))
    del collected
    if progress is not None:
        progress(n_batches, n_batches, 0)
    scale, _label = infer_point_scale(allpts.astype(float), "FAFB14")
    yield allpts.astype(np.float64) * scale
