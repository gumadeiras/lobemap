"""Image alignment validation.

An image layer is placed by `scale` and `translate`. Get either wrong and the
result is not an error but a plausible picture in the wrong place -- the
image-layer version of every silent failure this project has already hit.

So images are checked against geometry we trust. Neuropil is bright: an nc82
stack, or a synapse-density stain, must be substantially more intense inside
the antennal lobe than outside it. If that contrast is absent, the alignment
or the units are wrong.
"""

from __future__ import annotations

import numpy as np

from ..core.imagefmt import Volume
from ..core.meshfmt import MeshSet
from .geometry import Check


def check_image_covers_mesh(
    volume: Volume, meshset: MeshSet, label: str = "", margin_um: float = 5.0
) -> Check:
    """The mesh must lie inside the volume's bounds, or nothing can align."""
    lo, hi = volume.bounds_um()
    mlo = meshset.vertices.min(axis=0)
    mhi = meshset.vertices.max(axis=0)
    inside = bool(np.all(mlo >= lo - margin_um) and np.all(mhi <= hi + margin_um))
    return Check(
        f"image covers mesh{' ' + label if label else ''}",
        inside,
        f"mesh {np.round(mlo, 1)}..{np.round(mhi, 1)} vs volume "
        f"{np.round(lo, 1)}..{np.round(hi, 1)} um",
    )


def check_image_brightness_at_mesh(
    volume: Volume,
    meshset: MeshSet,
    label: str = "",
    min_ratio: float = 2.0,
    n_random: int = 4000,
    seed: int = 0,
) -> Check:
    """Intensity at compartment centroids vs random points in the volume.

    Neuropil is bright, so this ratio should be emphatic. A ratio near 1 means
    the image and the meshes are not in the same place.
    """
    centroids = np.array(
        [meshset.centroid(i) for i in range(meshset.n_compartments)]
    )
    at_mesh = volume.sample(centroids)
    lo, hi = volume.bounds_um()
    rng = np.random.default_rng(seed)
    background = volume.sample(rng.uniform(lo, hi, size=(n_random, 3)))

    denominator = float(background.mean())
    ratio = float(at_mesh.mean()) / denominator if denominator > 0 else float("inf")
    return Check(
        f"image brightness at mesh{' ' + label if label else ''}",
        ratio >= min_ratio,
        f"{at_mesh.mean():.1f} at centroids vs {background.mean():.1f} "
        f"background = {ratio:.2f}x (expect >= {min_ratio}x)",
    )


def shell_samples(
    volume: Volume,
    shell: MeshSet,
    n_samples: int = 20000,
    seed: int = 0,
    region: tuple[np.ndarray, np.ndarray] | None = None,
) -> tuple[np.ndarray, np.ndarray] | None:
    """Random points in the volume (or in `region`), and which are inside `shell`.

    Shared by the checks that compare inside with outside, so the costly
    point-in-mesh test runs once. None when trimesh has no ray engine.
    """
    import trimesh

    lo, hi = region if region is not None else volume.bounds_um()
    points = np.random.default_rng(seed).uniform(lo, hi, size=(n_samples, 3))
    inside = np.zeros(len(points), dtype=bool)
    for i in range(shell.n_compartments):
        v, f = shell.compartment(i)
        try:
            inside |= trimesh.Trimesh(vertices=v, faces=f, process=False).contains(points)
        except Exception:  # noqa: BLE001 - no ray engine
            return None
    return points, inside


def check_image_inside_shell(
    volume: Volume,
    shell: MeshSet,
    label: str = "",
    min_ratio: float = 2.0,
    n_samples: int = 20000,
    seed: int = 0,
    samples: tuple[np.ndarray, np.ndarray] | None = None,
) -> Check:
    """Mean intensity inside a neuropil shell vs outside it.

    Stronger than the centroid test: it uses the shell's whole interior, so a
    partial overlap cannot pass by luck.
    """
    name = f"image inside shell{' ' + label if label else ''}"
    samples = samples or shell_samples(volume, shell, n_samples, seed)
    if samples is None:
        return Check(name, False, "point-in-mesh unavailable (needs rtree)")
    points, inside_mask = samples

    if not inside_mask.any():
        return Check(
            name,
            False,
            "no sample points fell inside the shell -- image and mesh do not overlap",
        )

    values = volume.sample(points)
    inner = float(values[inside_mask].mean())
    outer = float(values[~inside_mask].mean()) if (~inside_mask).any() else 0.0
    ratio = inner / outer if outer > 0 else float("inf")
    return Check(
        name,
        ratio >= min_ratio,
        f"{inner:.1f} inside vs {outer:.1f} outside = {ratio:.2f}x "
        f"({int(inside_mask.sum())}/{len(points)} samples inside, "
        f"expect >= {min_ratio}x)",
    )


def mirror_points(points: np.ndarray, volume: Volume, axis: int) -> np.ndarray:
    """Reflect points through the center of the voxel grid along one axis.

    Sampling a volume at the mirrored points reads it as `np.flip(data,
    axis)` would, voxel for voxel.
    """
    lo, _ = volume.bounds_um()
    center = lo[axis] + (volume.shape[axis] - 1) * volume.voxel_um[axis] / 2.0
    out = np.array(points, dtype=float, copy=True)
    out[:, axis] = 2.0 * center - out[:, axis]
    return out


def _contrast(values: np.ndarray, inside: np.ndarray) -> float:
    outer = float(values[~inside].mean())
    return float(values[inside].mean()) / outer if outer > 0 else float("inf")


def check_image_orientation(
    volume: Volume,
    samples: tuple[np.ndarray, np.ndarray],
    axis: int,
    label: str = "",
    min_margin: float = 1.25,
) -> Check:
    """The image must fit its geometry better as stored than mirrored.

    A brain is nearly symmetric, so a stain flipped left-right still lies on
    neuropil, and the contrast checks above pass it -- in FAFB and the male
    CNS, a flipped stain kept 5.8x and 14x inside-shell contrast against a
    threshold of 2x. Its own mirror image is the one alternative that can
    fool them, so it is the one to compare against: flipped, the brain no
    longer lands on itself exactly, and the real stains lose 5-75x of their
    contrast (Grabe's confocal stack, an AL-only volume, 1.5x).

    `axis` is the array axis closest to the space's left-right axis;
    `samples` comes from `shell_samples`.
    """
    points, inside = samples
    name = f"image orientation{' ' + label if label else ''}"
    if not inside.any() or inside.all():
        return Check(name, False, "samples do not straddle the geometry")
    stored = _contrast(volume.sample(points), inside)
    flipped = _contrast(volume.sample(mirror_points(points, volume, axis)), inside)
    margin = stored / flipped if flipped > 0 else float("inf")
    return Check(
        name,
        margin >= min_margin,
        f"{stored:.2f}x inside vs outside as stored, {flipped:.2f}x mirrored "
        f"along {'xyz'[axis]} = {margin:.2f}x better (expect >= {min_margin}x)",
    )


def check_label_containment(
    glomeruli: MeshSet, labels: Volume, tolerance_um: float = 2.0
) -> Check | None:
    """Every glomerulus centroid must lie on its own label's voxels.

    The containment test for a space with no neuropil shell: Grabe's meshes
    are surfaced from these masks, so each must sit on the mask it came
    from. A centroid off its own mask is allowed `tolerance_um` to the
    nearest voxel of it, which curved glomeruli need (VP4 is 1.9 um off).
    None when the volume carries no `label_names`.
    """
    names = (labels.meta or {}).get("label_names")
    if not names:
        return None
    value_of = {name: int(value) for value, name in names.items()}
    data = labels.data
    voxel = np.asarray(labels.voxel_um)
    origin = np.asarray(labels.origin_um)
    reach = np.ceil(tolerance_um / voxel).astype(int) + 1

    offenders: list[str] = []
    tested = 0
    for i, name in enumerate(glomeruli.names):
        value = value_of.get(name)
        if value is None:
            continue
        tested += 1
        c = glomeruli.centroid(i)
        if labels.sample(c[None, :])[0] == value:
            continue
        # Look for the label in a box just past the tolerance.
        idx = labels.world_to_index(c[None, :])[0]
        lo = np.clip(idx - reach, 0, labels.shape)
        hi = np.clip(idx + reach + 1, 0, labels.shape)
        window = np.asarray(data[lo[0]:hi[0], lo[1]:hi[1], lo[2]:hi[2]])
        hits = np.argwhere(window == value)
        d = (
            float(np.min(np.linalg.norm(origin + (hits + lo) * voxel - c, axis=1)))
            if len(hits) else np.inf
        )
        if d > tolerance_um:
            where = f"{d:.1f} um" if np.isfinite(d) else f"> {tolerance_um} um"
            offenders.append(f"{name} ({where} from its label)")
    return Check(
        "label containment",
        bool(tested) and not offenders,
        f"{tested - len(offenders)}/{tested} centroids on their own label "
        f"(tol {tolerance_um} um)",
        offenders,
    )
