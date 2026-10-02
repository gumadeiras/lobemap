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


def check_image_inside_shell(
    volume: Volume,
    shell: MeshSet,
    label: str = "",
    min_ratio: float = 2.0,
    n_samples: int = 20000,
    seed: int = 0,
) -> Check:
    """Mean intensity inside a neuropil shell vs outside it.

    Stronger than the centroid test: it uses the shell's whole interior, so a
    partial overlap cannot pass by luck.
    """
    import trimesh

    lo, hi = volume.bounds_um()
    rng = np.random.default_rng(seed)
    points = rng.uniform(lo, hi, size=(n_samples, 3))

    inside_mask = np.zeros(len(points), dtype=bool)
    for i in range(shell.n_compartments):
        v, f = shell.compartment(i)
        mesh = trimesh.Trimesh(vertices=v, faces=f, process=False)
        try:
            inside_mask |= mesh.contains(points)
        except Exception:  # noqa: BLE001 - no ray engine
            return Check(
                f"image inside shell{' ' + label if label else ''}",
                False,
                "point-in-mesh unavailable (needs rtree)",
            )

    if not inside_mask.any():
        return Check(
            f"image inside shell{' ' + label if label else ''}",
            False,
            "no sample points fell inside the shell -- image and mesh do not overlap",
        )

    values = volume.sample(points)
    inner = float(values[inside_mask].mean())
    outer = float(values[~inside_mask].mean()) if (~inside_mask).any() else 0.0
    ratio = inner / outer if outer > 0 else float("inf")
    return Check(
        f"image inside shell{' ' + label if label else ''}",
        ratio >= min_ratio,
        f"{inner:.1f} inside vs {outer:.1f} outside = {ratio:.2f}x "
        f"({int(inside_mask.sum())}/{len(points)} samples inside, "
        f"expect >= {min_ratio}x)",
    )
