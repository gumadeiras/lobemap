"""Ingest glomeruli from a voxel label volume via marching cubes.

Grabe 2015's glomeruli are voxel-level masks, not meshes. An OBJ export of
them exists, but it is a derived rendering: taking it as the source inherits
whatever offsets and decimation the exporter applied, and indeed the OBJ set
sits ~1.1 voxels off in x from the masks for reasons that were never
established.

Surfacing the masks directly removes that question. The meshes and the
confocal stack then come from one array in one orientation, so their
alignment is exact by construction rather than something to check afterwards.
It also recovers both antennal lobes -- the OBJ export shipped only the left.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from ..core.meshfmt import MeshSet
from ..core.meshrepair import RepairReport, repair_meshset

#: "VP1_left_Ir40a" -> glomerulus VP1, side L.
AMIRA_NAME_RE = re.compile(
    r"^(?P<name>[^_]+)_(?P<side>left|right)(?:_.*)?$", re.IGNORECASE
)
SIDE_LETTER = {"left": "L", "right": "R"}

#: Materials that are not glomeruli.
NON_GLOMERULUS = {"exterior", "corners", "background"}


@dataclass
class LabelIngestResult:
    meshset: MeshSet
    skipped: list[str]
    repair: RepairReport | None = None


def parse_material(name: str) -> tuple[str, str | None] | None:
    """(glomerulus, side) for an Amira material, or None if not a glomerulus."""
    text = str(name).strip()
    if text.lower() in NON_GLOMERULUS:
        return None
    m = AMIRA_NAME_RE.match(text)
    if m:
        return m.group("name"), SIDE_LETTER[m.group("side").lower()]
    return text.split("_")[0], None


#: Marching cubes on a *binary* mask is a staircase: 42% of Grabe's faces had
#: an exactly axis-aligned normal against 3% for Bates, and 31% pointed along
#: z alone, because the z sampling is 0.96 um against 0.34 in x and y.
#: Blurring the mask and taking the isosurface of the smooth field removes it
#: at the source -- 42% -> 3.9%, in line with the other atlases -- where
#: smoothing the mesh afterwards only reached 17%, since by then the steps
#: are vertices.
#:
#: Sigma is in MICROMETERS, so the anisotropy is handled: ~3 voxels in x and y
#: against 1 in z, which is what the step sizes call for.
#:
#: It is chosen for smoothness ALONE. Disjointness is guaranteed structurally
#: by `_rival_field` and volume is corrected by `DEFAULT_LEVEL`, so none of
#: the three is traded against the others -- picking sigma small enough to
#: keep neighbors apart would undersmooth for a reason unrelated to
#: smoothing.
DEFAULT_MASK_SIGMA_UM = 1.0

#: Background isolevel. Blurring shrinks a convex surface -- roughly
#: sigma^2/R, so hardest on the small glomeruli -- and 0.5 loses 7.2% of the
#: volume. 0.44 was measured to restore it, to -0.4% on average. Lowering it
#: cannot make neighbors collide: a shared boundary is set by the midpoint
#: rule and never by this level.
DEFAULT_LEVEL = 0.44

#: Taubin passes AFTER the isosurface. Zero by default: against a blurred
#: mask it changed the axis-aligned fraction by a few tenths of a point, so
#: it is a second geometry-altering step that buys nothing.
DEFAULT_SMOOTH_ITERATIONS = 0


def materials_from_amira(header_path, id_offset: int = -1) -> dict[int, str]:
    """Voxel value -> material name, from an AmiraMesh header.

    The `.am` file is the only place the mapping from voxel value to
    glomerulus name lives, so parsing it here keeps the ingest reproducible
    from the published files rather than from a hand-transcribed dict.
    `Id` may appear before or after `Color` within a block, so it is matched
    by name rather than position.

    **`id_offset` defaults to -1 and that is not arbitrary.** Amira numbers
    materials from 1 with `Exterior` as Id 1, but its TIFF export writes
    background as 0: in the Grabe volume, value 0 holds 28.98 M of 31.38 M
    voxels while `Exterior` carries Id 1. Taking the Ids at face value shifts
    every glomerulus onto its neighbor's label, which is not a crash but a
    silent mislabeling -- it moved four glomeruli in and two out, and dropped
    the mean positional-nomenclature coherence from 0.81 to 0.74. `ingest`
    now checks the modal value is unclaimed, which catches a wrong offset.
    """
    import re

    head = Path(header_path).read_bytes()[:200_000].decode("latin-1")
    start = head.index("Materials")
    depth, end = 0, None
    for i, ch in enumerate(head[start:], start=start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
    block = head[start:end]
    out: dict[int, str] = {}
    for m in re.finditer(r"([A-Za-z_][\w\-]*)\s*\{([^{}]*)\}", block):
        name, body = m.group(1), m.group(2)
        ident = re.search(r"\bId\s+(\d+)", body)
        if ident:
            out[int(ident.group(1)) + id_offset] = name
    return out


def label_names(materials: dict[int, str]) -> dict[int, str]:
    """Voxel value -> the compartment name a mesh of it would carry.

    The Amira header maps a voxel value to a RAW material name
    (`DA1_left`); a MeshSet carries the PARSED, sided name (`DA1(L)`). The
    viewer needs to join the two -- to color a voxel mask the same as its
    mesh -- and neither container held the correspondence, so it had to be
    re-derived from the `.am` file, which does not ship.

    Non-glomerulus materials (`Exterior`) are dropped, so a value absent from
    the result is background or scaffolding, not a missing name.

    For Grabe this maps 112 materials onto exactly the 108 surfaced
    compartments; the two left over are VM6 left and right, which have no
    voxels in the published volume at all and so are also the ingest's two
    skips.
    """
    out: dict[int, str] = {}
    for value, raw in materials.items():
        parsed = parse_material(raw)
        if parsed is None:
            continue
        name, side = parsed
        out[int(value)] = f"{name}({side})" if side else name
    return out


def masks_volume(label_path, materials: dict[int, str],
                 voxel_um_zyx, transpose=(2, 1, 0)):
    """The publication's own voxel masks as a Volume, unmodified.

    The meshes in `grabe2015_glomeruli` are surfaced FROM this, so keeping it
    means the smoothing can always be checked against its input.

    It is stored as npz rather than zarr on purpose: a multiscale pyramid
    averages neighboring voxels, and the mean of two label ids is a third
    label -- a plausible-looking glomerulus that does not exist.

    The value -> name map travels in the metadata. Without it the viewer
    cannot color a mask the same as its mesh, and the correspondence lives
    only in the Amira header, which does not ship.
    """
    import tifffile

    from ..core.imagefmt import Volume

    label_path = Path(label_path)
    labels = np.transpose(tifffile.imread(label_path), transpose)
    spacing = tuple(float(voxel_um_zyx[a]) for a in transpose)
    names = label_names(materials)

    present = set(np.unique(labels).tolist()) - {0}
    unnamed = sorted(present - set(names))
    if unnamed:
        raise ValueError(
            f"voxel values with no material name: {unnamed}. The Amira Id "
            f"offset is probably wrong; see `materials_from_amira`."
        )

    return Volume(
        data=labels,
        voxel_um=spacing,
        meta={
            "source": "label-volume",
            "source_file": label_path.name,
            "role": "glomeruli",
            "kind": "labels",
            "units": "um",
            "transpose": list(transpose),
            "note": (
                "the publication's own voxel-wise masks, unmodified. The "
                "meshes in grabe2015_glomeruli are surfaced from these; "
                "value = Amira material Id - 1."
            ),
            "label_names": {str(k): v for k, v in sorted(names.items())},
            "label_names_source": label_path.with_suffix(".am").name,
            "retrieved": datetime.now(UTC).date().isoformat(),
        },
    )


def orient_outward(verts: np.ndarray, faces: np.ndarray) -> np.ndarray:
    """Face winding that puts normals outward, flipping it if they are not.

    The array is transposed before marching cubes and `(2, 1, 0)` is an ODD
    permutation, which inverts handedness -- so skimage's winding came back
    describing inward normals and every Grabe mesh had a negative signed
    volume. Checking the sign is self-correcting; reasoning about whose
    convention it is, is not.
    """
    import trimesh

    mesh = trimesh.Trimesh(vertices=np.asarray(verts, dtype=float),
                           faces=faces, process=False)
    if mesh.volume < 0:
        return np.asarray(faces)[:, ::-1]
    return np.asarray(faces)


def smooth_surface(verts: np.ndarray, faces: np.ndarray,
                   iterations: int = DEFAULT_SMOOTH_ITERATIONS):
    """Taubin-smooth one surface. Returns (verts, faces, volume_change_pct)."""
    import trimesh

    mesh = trimesh.Trimesh(vertices=np.asarray(verts, dtype=float),
                           faces=faces, process=False)
    before = abs(float(mesh.volume))
    trimesh.smoothing.filter_taubin(mesh, iterations=iterations)
    after = abs(float(mesh.volume))
    change = 100.0 * (after / before - 1.0) if before > 0 else 0.0
    return np.asarray(mesh.vertices, dtype=np.float32), np.asarray(mesh.faces), change


def _blur_block(labels, value, spacing, sigma_um, pad):
    """Blurred indicator for one label, and where it sits in the volume."""
    from scipy.ndimage import gaussian_filter

    where = np.argwhere(labels == value)
    if not len(where):
        return None
    lo = np.maximum(where.min(0) - pad, 0)
    hi = np.minimum(where.max(0) + pad + 1, np.asarray(labels.shape))
    sl = tuple(slice(a, b) for a, b in zip(lo, hi))
    block = (labels[sl] == value).astype(np.float32)
    if block.sum() < 8:
        return None
    if sigma_um:
        block = gaussian_filter(
            block, sigma=tuple(sigma_um / np.asarray(spacing, dtype=float)),
            mode="constant",
        )
    return sl, block


def _rival_field(labels, values, spacing, sigma_um, pad):
    """Per voxel: the strongest blurred label, the runner-up, and the winner.

    This is what keeps the smoothed glomeruli DISJOINT without constraining
    sigma. Surfacing each blurred mask alone and thresholding expands every
    region outward, so neighbors that were touching interpenetrate -- at a
    level of 0.46, 158 voxels landed inside two glomeruli at once (VC3/VP2,
    VA1d/VA1v, DM1/DM4 among them).

    Shrinking sigma until that stops would be choosing smoothness to satisfy
    a constraint that has nothing to do with smoothness. Instead each surface
    is placed where its own field overtakes its strongest rival: two regions
    can meet but never overlap, because `g_i > g_j` and `g_j > g_i` cannot
    both hold, and sigma is left free.
    """
    best = np.zeros(labels.shape, dtype=np.float32)
    second = np.zeros(labels.shape, dtype=np.float32)
    owner = np.zeros(labels.shape, dtype=np.int32)
    for value in values:
        got = _blur_block(labels, value, spacing, sigma_um, pad)
        if got is None:
            continue
        sl, block = got
        current = best[sl]
        wins = block > current
        second[sl] = np.where(wins, current, np.maximum(second[sl], block))
        best[sl] = np.where(wins, block, current)
        owner[sl] = np.where(wins, value, owner[sl])
    return best, second, owner


def surface_from_field(block, sl, spacing, level_field, pad):
    """Isosurface where a label's field overtakes background and rivals.

    `level_field` is the elementwise larger of the background level and the
    strongest rival, so the zero crossing is the smooth background boundary
    in open space and the midpoint between two glomeruli where they touch.
    """
    from skimage.measure import marching_cubes

    spacing = np.asarray(spacing, dtype=float)
    height = np.pad(block - level_field, pad, mode="constant",
                    constant_values=-1.0)
    if height.max() <= 0:
        return None
    verts, faces, _normals, _values = marching_cubes(
        height, level=0.0, spacing=tuple(spacing)
    )
    lo = np.array([s.start for s in sl], dtype=float)
    verts = verts - pad * spacing + lo * spacing
    return verts, orient_outward(verts, faces)


def surface_from_mask(
    labels: np.ndarray,
    value: int,
    spacing: tuple[float, float, float],
    pad: int | None = None,
    mask_sigma_um: float = DEFAULT_MASK_SIGMA_UM,
    level: float = DEFAULT_LEVEL,
):
    """Isosurface of one label, in world units, from a smoothed mask.

    The sub-volume is padded so neither the mask nor the blur's tail reaches
    the array border, which would leave the surface open there. The pad is
    derived from sigma rather than fixed: the old fixed pad of 2 voxels is
    narrower than this blur, and it would have clipped the surface flat on
    every side.
    """
    from scipy.ndimage import gaussian_filter
    from skimage.measure import marching_cubes

    spacing = np.asarray(spacing, dtype=float)
    sigma_vox = (mask_sigma_um / spacing) if mask_sigma_um else np.zeros(3)
    if pad is None:
        pad = int(max(2, np.ceil(3.0 * float(sigma_vox.max()))))

    where = np.argwhere(labels == value)
    if not len(where):
        return None
    lo = np.maximum(where.min(0) - pad, 0)
    hi = np.minimum(where.max(0) + pad + 1, np.asarray(labels.shape))
    block = labels[lo[0]:hi[0], lo[1]:hi[1], lo[2]:hi[2]] == value
    if block.sum() < 8:
        return None
    # Pad by the blur's reach as well, so a mask touching the crop keeps a
    # closed surface.
    block = np.pad(block.astype(np.float32), pad, mode="constant")

    if mask_sigma_um:
        block = gaussian_filter(block, sigma=tuple(sigma_vox), mode="constant")

    verts, faces, _normals, _values = marching_cubes(
        block, level=level, spacing=tuple(spacing)
    )
    # Undo the pad, then place the block back in the full volume.
    verts = verts - pad * spacing
    verts = verts + lo * spacing
    return verts, orient_outward(verts, faces)


def ingest(
    label_path: str | Path,
    materials: dict[int, str],
    voxel_um_zyx: tuple[float, float, float],
    transpose: tuple[int, int, int] = (2, 1, 0),
    repair: bool = True,
    smooth: int = DEFAULT_SMOOTH_ITERATIONS,
    mask_sigma_um: float = DEFAULT_MASK_SIGMA_UM,
    level: float = DEFAULT_LEVEL,
) -> LabelIngestResult:
    import tifffile

    label_path = Path(label_path)
    labels = tifffile.imread(label_path)
    # Reorient once, so meshes and any image from the same grid agree.
    labels = np.transpose(labels, transpose)
    spacing = tuple(float(voxel_um_zyx[a]) for a in transpose)

    # The most common value is background. If a glomerulus claims it, the
    # material Ids are offset against the voxel values and every label is
    # shifted -- which mislabels silently rather than failing.
    values, counts = np.unique(labels, return_counts=True)
    modal = int(values[int(np.argmax(counts))])
    claimed = materials.get(modal)
    if claimed is not None and parse_material(claimed) is not None:
        raise ValueError(
            f"the most common voxel value ({modal}, "
            f"{counts.max() / labels.size:.1%} of the volume) is mapped to "
            f"{claimed!r}, a glomerulus. The material Ids are almost certainly "
            f"offset against the voxel values; see `materials_from_amira`."
        )

    parts: list[tuple[str, np.ndarray, np.ndarray]] = []
    skipped: list[str] = []
    smoothing_changes: dict[str, float] = {}

    pad = int(max(2, np.ceil(
        3.0 * float((mask_sigma_um / np.asarray(spacing)).max())
    ))) if mask_sigma_um else 2
    wanted = [v for v, raw in sorted(materials.items())
              if parse_material(raw) is not None]
    best, second, owner = _rival_field(labels, wanted, spacing,
                                       mask_sigma_um, pad)
    # Disjointness is structural, but verified rather than asserted.
    claims = np.zeros(labels.shape, dtype=np.uint8)
    overlaps: list[str] = []

    for value, raw_name in sorted(materials.items()):
        parsed = parse_material(raw_name)
        if parsed is None:
            continue
        glom, side = parsed
        label = f"{glom}({side})" if side else glom
        try:
            got = _blur_block(labels, value, spacing, mask_sigma_um, pad)
            if got is None:
                skipped.append(f"{label}: no voxels")
                continue
            sl, block = got
            rival = np.where(owner[sl] == value, second[sl], best[sl])
            level_field = np.maximum(np.float32(level), rival)
            surface = surface_from_field(block, sl, spacing, level_field, pad)
        except Exception as exc:  # noqa: BLE001 - one bad label must not stop the run
            skipped.append(f"{label}: {type(exc).__name__}: {exc}")
            continue
        if surface is None:
            skipped.append(f"{label}: empty after smoothing")
            continue

        region = (block > level_field).astype(np.uint8)
        if np.any(region & (claims[sl] > 0)):
            overlaps.append(label)
        claims[sl] += region

        v, f = surface
        if smooth:
            v, f, change = smooth_surface(v, f, smooth)
            smoothing_changes[label] = round(change, 3)
        parts.append((label, v, f))

    if overlaps:
        raise ValueError(
            f"{len(overlaps)} smoothed labels overlap another: {overlaps[:6]}. "
            f"The midpoint rule in `_rival_field` should make this impossible, "
            f"so this means that rule is broken -- not that sigma is too big."
        )

    if not parts:
        raise ValueError(f"no glomerulus labels surfaced from {label_path}")

    ms = MeshSet.from_parts(
        parts,
        meta={
            "source": "label-volume",
            "source_file": label_path.name,
            "units": "um",
            "role": "glomeruli",
            "voxel_um": list(spacing),
            "transpose": list(transpose),
            "method": (
                f"gaussian(sigma={mask_sigma_um} um), isosurface where the "
                f"label overtakes max(level={level}, strongest rival)"
                + (f", taubin x{smooth}" if smooth else "")
            ),
            "mask_sigma_um": mask_sigma_um,
            "level": level,
            "boundary": "midpoint between neighboring blurred labels",
            "disjoint_verified": True,
            "smooth_iterations": smooth,
            "max_smoothing_volume_change_pct": (
                max(abs(v) for v in smoothing_changes.values())
                if smoothing_changes else 0.0
            ),
            "retrieved": datetime.now(UTC).date().isoformat(),
            "n_skipped": len(skipped),
            "background_value": modal,
        },
    )
    report = None
    if repair:
        ms, report = repair_meshset(ms)
    return LabelIngestResult(ms, skipped, report)
