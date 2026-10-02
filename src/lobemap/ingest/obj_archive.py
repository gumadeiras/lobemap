"""Ingest glomerulus meshes from an archive of per-glomerulus mesh files.

Handles .obj and .stl inside .7z / .zip archives, or a plain directory.

- Grabe et al. 2015: 55 OBJs in a .7z, `left-AL_<glomerulus>.Labels<n>.obj`.
  An island space, built on a light-microscopy template.
- Schlegel et al. 2021 supplementary files 11 and 12: STLs named
  `JRCFIB2018Fraw.<glomerulus>.stl`. The two files are the same glomeruli
  defined two different ways -- S11 from receptor-neuron terminals, S12 from
  projection-neuron dendrites -- so they are two atlases, not duplicates.
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from ..core.meshfmt import MeshSet
from ..core.meshrepair import RepairReport, repair_meshset
from ..core.units import scale_to_um, verify_extent
from ._obj import parse_obj

#: Filename conventions, tried in order. Each must yield a `name` group and
#: may yield a `side` group.
NAME_PATTERNS = [
    # Grabe: "left-AL_DA4l.Labels6.obj"
    re.compile(
        r"^(?P<side>left|right)[-_]AL[-_](?P<name>[^.]+)\.Labels\d*\.(obj|stl)$",
        re.IGNORECASE,
    ),
    # Schlegel: "JRCFIB2018Fraw.VM3.stl" -- the prefix is the template, not a name.
    re.compile(r"^[A-Za-z0-9]+\.(?P<name>[^.]+)\.(obj|stl)$"),
]

MESH_SUFFIXES = (".obj", ".stl")

#: Used to CHECK the units the recipe declares, never to choose them.
COMPARTMENT_EXTENT_UM = (4.0, 45.0)

SIDE_LETTER = {"left": "L", "right": "R"}


@dataclass
class ObjIngestResult:
    meshset: MeshSet
    skipped: list[str]
    scale_to_um: float
    source_units: str
    repair: RepairReport | None = None


def _is_mesh(name: str) -> bool:
    low = name.lower()
    # Skip macOS resource forks, which zip alongside the real files.
    if "__MACOSX" in name or Path(name).name.startswith("._"):
        return False
    return low.endswith(MESH_SUFFIXES)


def _members(path: Path):
    """Yield (name, bytes) from a .7z or .zip archive, or a directory."""
    if path.is_dir():
        for p in sorted(path.rglob("*")):
            if _is_mesh(p.name):
                yield p.name, p.read_bytes()
        return
    if path.suffix.lower() == ".7z":
        import tempfile

        import py7zr

        # py7zr >= 1.0 has no in-memory readall(); extract to a scratch dir.
        with tempfile.TemporaryDirectory() as tmp:
            with py7zr.SevenZipFile(path) as archive:
                archive.extractall(path=tmp)
            for p in sorted(Path(tmp).rglob("*")):
                if _is_mesh(p.name):
                    yield p.name, p.read_bytes()
        return
    with zipfile.ZipFile(path) as archive:
        for name in sorted(archive.namelist()):
            if _is_mesh(name):
                yield Path(name).name, archive.read(name)


def parse_name(filename: str) -> tuple[str, str | None]:
    """Return (compartment_name, side) for an archive member."""
    for pattern in NAME_PATTERNS:
        m = pattern.match(filename)
        if not m:
            continue
        groups = m.groupdict()
        side = SIDE_LETTER.get((groups.get("side") or "").lower())
        return groups["name"], side
    return Path(filename).stem, None


def ingest(
    archive: str | Path, source_units: str, repair: bool = True,
    include_side: bool = True,
) -> ObjIngestResult:
    archive = Path(archive)
    raw: list[tuple[str, np.ndarray, np.ndarray]] = []
    skipped: list[str] = []

    for member, payload in _members(archive):
        if not _is_mesh(member):
            continue
        name, side = parse_name(member)
        try:
            if member.lower().endswith(".stl"):
                import trimesh

                mesh = trimesh.load(
                    io.BytesIO(payload), file_type="stl", process=False
                )
                v = np.asarray(mesh.vertices, dtype=np.float64)
                f = np.asarray(mesh.faces, dtype=np.int64)
            else:
                v, f = parse_obj(payload)
        except Exception as exc:  # noqa: BLE001
            skipped.append(f"{member}: {type(exc).__name__}: {exc}")
            continue
        if not len(v) or not len(f):
            skipped.append(f"{member}: empty mesh")
            continue
        # Encode laterality in the name so downstream pairing sees it, matching
        # the neuPrint convention.
        label = f"{name}({side})" if (include_side and side) else name
        raw.append((label, v, f))

    if not raw:
        raise ValueError(f"no OBJ meshes found in {archive}")

    raw.sort(key=lambda r: r[0])
    extents = np.array(
        [float(np.max(v.max(axis=0) - v.min(axis=0))) for _, v, _ in raw]
    )
    units = source_units
    scale = scale_to_um(units)
    verify_extent(extents, scale, COMPARTMENT_EXTENT_UM, units)

    ms = MeshSet.from_parts(
        [(n, v * scale, f) for n, v, f in raw],
        meta={
            "source": "obj-archive",
            "source_file": archive.name,
            "source_units": units,
            "scale_to_um": scale,
            "units": "um",
            "role": "glomeruli",
            "retrieved": datetime.now(UTC).date().isoformat(),
            "n_skipped": len(skipped),
        },
    )
    report = None
    if repair:
        ms, report = repair_meshset(ms)
    return ObjIngestResult(ms, skipped, scale, units, report)
