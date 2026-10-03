"""Ingest a 3D Slicer segmentation (.vtm index + per-segment .vtp meshes).

Used for Benton et al. 2025 Dataset EV2, a manual revision of the Bates 2020
antennal lobe meshes (including a split of one glomerulus into two, which is
why compartment-to-canonical correspondence is many-to-many).

Coordinate convention: 3D Slicer works in RAS, while the FAFB meshes these
were derived from are in an LPS-style frame, so x and y arrive negated. That
is verified rather than assumed -- converting and comparing centroid clouds
against Bates gives an offset of 0.0 um.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from ..core.meshfmt import MeshSet
from ..core.meshrepair import RepairReport, repair_meshset
from ..core.units import scale_to_um, verify_extent

#: Plausible size of one glomerulus, in micrometers. Used to CHECK the units
#: the recipe declares, never to choose them.
COMPARTMENT_EXTENT_UM = (4.0, 45.0)

#: RAS -> LPS: negate the first two axes. See module docstring.
RAS_TO_LPS = np.array([-1.0, -1.0, 1.0])


@dataclass
class SlicerIngestResult:
    meshset: MeshSet
    skipped: list[str]
    scale_to_um: float
    source_units: str
    repair: RepairReport | None = None


def _field(block, key: str, default=None):
    try:
        value = block.field_data[key]
    except (KeyError, AttributeError):
        return default
    return value[0] if len(value) else default


def _triangles(poly) -> np.ndarray:
    """Triangle indices from a PolyData, triangulating if needed."""
    import pyvista as pv  # noqa: F401  (import guard; poly comes from pyvista)

    surf = poly.triangulate()
    faces = np.asarray(surf.faces).reshape(-1, 4)
    if faces.size and not np.all(faces[:, 0] == 3):
        raise ValueError("non-triangular faces after triangulate()")
    return faces[:, 1:].astype(np.int64), np.asarray(surf.points, dtype=np.float64)


def ingest(
    vtm_path: str | Path,
    source_units: str,
    ras_to_lps: bool = True,
    repair: bool = True,
) -> SlicerIngestResult:
    import pyvista as pv

    vtm_path = Path(vtm_path)
    multiblock = pv.read(str(vtm_path))

    raw: list[tuple[str, np.ndarray, np.ndarray]] = []
    colors: dict[str, list[float]] = {}
    skipped: list[str] = []
    for i in range(multiblock.n_blocks):
        block = multiblock[i]
        if block is None:
            skipped.append(f"block {i}: empty")
            continue
        # Prefer Segment_Name's prefix over Segment_ID. Segment_Name is
        # "VM7d-Or42a-pb1" (glomerulus-receptor-sensillum), so the part before
        # the first hyphen is the glomerulus. Segment_ID looks cleaner but
        # carries 3D Slicer's uniquifying suffix -- Benton's VP1m arrives as
        # Segment_ID "VP1m_1", which would fabricate a glomerulus that the
        # dataset's own color table calls plain "VP1m".
        seg_name = _field(block, "Segment_Name")
        seg_id = _field(block, "Segment_ID")
        if seg_name:
            name = str(seg_name).split("-", 1)[0].strip()
        elif seg_id:
            name = str(seg_id)
        else:
            name = multiblock.get_block_name(i) or f"block{i}"
        try:
            faces, points = _triangles(block)
        except Exception as exc:  # noqa: BLE001
            skipped.append(f"{name}: {type(exc).__name__}: {exc}")
            continue
        if not len(points) or not len(faces):
            skipped.append(f"{name}: empty mesh")
            continue
        col = _field(block, "Segment_Color")
        if col is not None:
            colors[name] = [*(float(c) for c in np.asarray(col).ravel()[:3]), 1.0]
        raw.append((name, points, faces))

    if not raw:
        raise ValueError(f"no usable segments in {vtm_path}")

    extents = np.array(
        [float(np.max(v.max(axis=0) - v.min(axis=0))) for _, v, _ in raw]
    )
    units = source_units
    scale = scale_to_um(units)
    verify_extent(extents, scale, COMPARTMENT_EXTENT_UM, units)
    sign = RAS_TO_LPS if ras_to_lps else np.ones(3)

    ms = MeshSet.from_parts(
        [(n, v * scale * sign, f) for n, v, f in raw],
        meta={
            "source": "slicer-vtm",
            "source_file": vtm_path.name,
            "source_units": units,
            "scale_to_um": scale,
            "units": "um",
            "role": "glomeruli",
            "ras_to_lps": bool(ras_to_lps),
            "retrieved": datetime.now(UTC).date().isoformat(),
            "colors": colors,
            "n_skipped": len(skipped),
        },
    )
    report = None
    if repair:
        ms, report = repair_meshset(ms)
    return SlicerIngestResult(ms, skipped, scale, units, report)
