"""Streaming presynapse locations, per dataset.

SUPERSEDED for stain building. neuPrint is slower (~40 s fixed overhead per
query) and, for anything reached through neuron criteria, incomplete: ~60% of
detected synapses are not assigned to proofread neurons. Build stains from
the published buckets instead, via `synapse_buckets`. This module is kept
as a fallback and for ROI-scoped queries, where it remains convenient.

Whole-brain queries return 10^7 rows, so nothing here fetches everything in
one call. neuPrint is partitioned into spatial slabs along one axis; each slab
is a separate query, which keeps both the server response and our memory
bounded and lets a long run report progress.
"""

from __future__ import annotations

from collections.abc import Iterator

import numpy as np

#: hemibrain and male CNS both serve synapse locations in 8 nm voxels.
NEUPRINT_VOXEL_NM = 8.0


def neuprint_client(server: str, dataset: str, token: str | None = None):
    from neuprint import Client

    return Client(server, dataset=dataset, token=token)


def _roi_predicate(rois: list[str] | None) -> str:
    if not rois:
        return ""
    # A synapse carries a boolean property per ROI it falls in.
    terms = " OR ".join(f"s.`{roi}`" for roi in rois)
    return f"AND ({terms}) "


# NB: do NOT ask neo4j for min/max over the synapse table. An unfiltered
# aggregate scans ~10^7 rows and hits the server transaction timeout. Bounds
# always come from geometry we already hold -- a neuropil mesh, or the
# flybrains template bounding box.


def neuprint_presynapses(
    client,
    lo_um,
    hi_um,
    rois: list[str] | None = None,
    confidence: float | None = 0.5,
    n_slabs: int = 24,
    axis: int = 2,
    progress=None,
    max_retries: int = 3,
) -> Iterator[np.ndarray]:
    """Yield (N, 3) presynapse positions in micrometers, slab by slab.

    `lo_um`/`hi_um` bound the region and are supplied by the caller, never
    queried -- see the note above. A slab that times out is split and retried,
    so one dense region cannot fail the whole run.
    """
    scale = NEUPRINT_VOXEL_NM * 1e-3
    roi_clause = _roi_predicate(rois)
    conf_clause = (
        f"AND s.confidence >= {float(confidence)} " if confidence is not None else ""
    )
    letter = "xyz"[axis]
    lo_vox = float(np.asarray(lo_um, dtype=float)[axis] / scale)
    hi_vox = float(np.asarray(hi_um, dtype=float)[axis] / scale)
    edges = np.linspace(lo_vox, hi_vox + 1.0, n_slabs + 1)

    def fetch(a: float, b: float, depth: int = 0) -> np.ndarray:
        query = (
            "MATCH (s:Synapse {type:'pre'}) "
            f"WHERE s.location.{letter} >= {a} AND s.location.{letter} < {b} "
            f"{roi_clause}{conf_clause}"
            "RETURN s.location.x AS x, s.location.y AS y, s.location.z AS z"
        )
        try:
            df = client.fetch_custom(query)
        except Exception:
            if depth >= max_retries:
                raise
            mid = 0.5 * (a + b)
            return np.vstack([fetch(a, mid, depth + 1), fetch(mid, b, depth + 1)])
        if not len(df):
            return np.zeros((0, 3), dtype=float)
        return df[["x", "y", "z"]].to_numpy(dtype=float) * scale

    for i in range(n_slabs):
        points = fetch(edges[i], edges[i + 1])
        if progress is not None:
            progress(i + 1, n_slabs, len(points))
        yield points


def flywire_presynapses(
    confidence: float = 50.0, batch_size: int = 2_000_000, progress=None
) -> Iterator[np.ndarray]:
    """Yield (N, 3) FlyWire presynapse positions in micrometers.

    `confidence` is the published cleft-score recommendation. FlyWire
    coordinates are 4 nm voxels; fafbseg returns them in nanometers.
    """
    from fafbseg import flywire

    table = flywire.get_synapses(
        None, pre=True, post=False, min_score=confidence, transmitters=False
    )
    columns = [c for c in ("pre_x", "pre_y", "pre_z") if c in table.columns]
    if len(columns) != 3:
        columns = ["x", "y", "z"]
    points = table[columns].to_numpy(dtype=float) * 1e-3  # nm -> um
    for start in range(0, len(points), batch_size):
        chunk = points[start : start + batch_size]
        if progress is not None:
            progress(start // batch_size + 1, -1, len(chunk))
        yield chunk
