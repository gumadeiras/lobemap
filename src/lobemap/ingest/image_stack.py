"""Ingest an image stack (TIFF / NRRD) as a canonical Volume.

Voxel size is read from the file's own metadata wherever possible -- ImageJ
TIFFs carry XResolution and a `spacing` field -- because a hard-coded voxel
size is the image-layer equivalent of a hard-coded unit scale, and fails the
same silent way.

Axis order is explicit, and it is known rather than discovered. Readers return
(z, y, x) while OBJ/mesh vertices are (x, y, z), so the reconciling transpose
is simply (2, 1, 0) and the world mapping is `index * voxel_size` with a zero
origin. That is a prediction, so `verify_against_labels` checks it instead of
searching for it: for Grabe the y and z offsets come out at -0.01 and -0.05 um
across 50 glomeruli, i.e. zero, confirming the mapping.

A residual worth recording: x is offset by +0.38 um, about 1.1 voxels, and
consistently so. Its cause is not established. It is left UNCORRECTED -- a
sub-voxel empirical shim that cannot be explained is worse than a known, small,
documented error, and 0.38 um is ~1/60 of a glomerulus.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from ..core.imagefmt import Volume


@dataclass
class ImageIngestResult:
    volume: Volume
    source_voxel_zyx: tuple[float, float, float]
    notes: list[str]


def read_tiff_voxel_um(path: Path) -> tuple[float, float, float] | None:
    """(z, y, x) voxel size in micrometers from ImageJ/TIFF metadata."""
    import tifffile

    with tifffile.TiffFile(path) as tif:
        page = tif.pages[0]
        tags = page.tags

        def _res(name: str) -> float | None:
            if name not in tags:
                return None
            value = tags[name].value
            if isinstance(value, tuple) and len(value) == 2 and value[1]:
                per_unit = value[0] / value[1]
                return 1.0 / per_unit if per_unit else None
            return None

        xy = _res("XResolution")
        yx = _res("YResolution") or xy
        z = None
        desc = tags["ImageDescription"].value if "ImageDescription" in tags else ""
        unit_um = "micron" in str(desc).lower()
        for line in str(desc).splitlines():
            if line.lower().startswith("spacing="):
                try:
                    z = float(line.split("=", 1)[1])
                except ValueError:
                    pass
        if xy is None or z is None:
            return None
        if not unit_um:
            # Without an explicit micron unit the numbers cannot be trusted.
            return None
        return (float(z), float(yx), float(xy))


def ingest(
    path: str | Path,
    space: str,
    voxel_um_zyx: tuple[float, float, float] | None = None,
    transpose: tuple[int, int, int] = (2, 1, 0),
    origin_um: tuple[float, float, float] = (0.0, 0.0, 0.0),
    role: str = "template_image",
) -> ImageIngestResult:
    path = Path(path)
    notes: list[str] = []

    if path.suffix.lower() in (".tif", ".tiff"):
        import tifffile

        data = tifffile.imread(path)
        measured = read_tiff_voxel_um(path)
    elif path.suffix.lower() in (".nrrd",):
        import nrrd

        data, header = nrrd.read(str(path))
        measured = None
        directions = header.get("space directions")
        if directions is not None:
            spacing = np.linalg.norm(np.asarray(directions, dtype=float), axis=1)
            measured = tuple(float(s) for s in spacing)
    else:
        raise ValueError(f"unsupported image format: {path.suffix}")

    if voxel_um_zyx is None:
        if measured is None:
            raise ValueError(
                f"{path.name}: no voxel size in the file metadata; pass "
                "voxel_um_zyx explicitly rather than assuming isotropic"
            )
        voxel_um_zyx = measured
        notes.append(f"voxel size read from metadata: {measured}")

    data = np.asarray(data)
    if data.ndim != 3:
        raise ValueError(f"{path.name}: expected 3D, got shape {data.shape}")

    # Reorder both the array and its voxel sizes together.
    arranged = np.transpose(data, transpose)
    voxel = tuple(float(voxel_um_zyx[a]) for a in transpose)
    notes.append(f"transposed {transpose}, voxel {voxel} um")

    volume = Volume(
        data=np.ascontiguousarray(arranged),
        voxel_um=voxel,
        origin_um=origin_um,
        meta={
            "source": "image-stack",
            "source_file": path.name,
            "space": space,
            "role": role,
            "units": "um",
            "source_voxel_zyx": list(voxel_um_zyx),
            "transpose": list(transpose),
            "retrieved": datetime.now(UTC).date().isoformat(),
        },
    )
    return ImageIngestResult(volume, tuple(voxel_um_zyx), notes)


def verify_against_labels(
    volume: Volume,
    label_volume: np.ndarray,
    label_to_name: dict[int, str],
    meshset,
    transpose: tuple[int, int, int] = (2, 1, 0),
) -> dict:
    """Check the predicted index->world mapping against known geometry.

    Compares each label's voxel-volume centroid with the corresponding mesh's
    VOLUME centroid (`center_mass`). Using the surface-vertex mean instead is a
    subtly different quantity and inflates the residual.

    Returns per-axis mean offsets in micrometers; near-zero means the mapping
    holds.
    """
    import trimesh

    voxel = np.asarray(volume.voxel_um, dtype=float)
    deltas = []
    for value, name in label_to_name.items():
        if name not in meshset.names:
            continue
        where = np.argwhere(label_volume == value)
        if not len(where):
            continue
        centroid = where[:, list(transpose)].mean(0) * voxel
        v, f = meshset.compartment(meshset.names.index(name))
        mesh = trimesh.Trimesh(vertices=v, faces=f, process=False)
        deltas.append(centroid - np.asarray(mesh.center_mass))

    if not deltas:
        return {"n": 0}
    d = np.asarray(deltas)
    return {
        "n": len(d),
        "mean_offset_um": d.mean(0).tolist(),
        "rms_um": float(np.sqrt((d**2).sum(1)).mean()),
    }
