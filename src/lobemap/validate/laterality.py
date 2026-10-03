"""Left-right validation.

A left-right error does not move anything off the brain. Mirror a whole
space and every glomerulus still sits inside its antennal lobe, every stain
is still bright on the neuropil, and every check that compares a space with
itself still passes: those checks are symmetric, and so is most of the brain.

Two things are not symmetric, and these checks hold the data to both:

- the anatomy a space DECLARES (`anatomical_rotation` in `spaces.toml`),
  which says where the fly's right is in array coordinates;
- the fly itself. The asymmetric body is larger on the fly's right in most
  wild-type flies (Pascual et al. 2004, Nature 427:605, doi:10.1038/427605a),
  and it is: 3.7x in the hemibrain and 4.2x in the male CNS.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np

from ..core.meshfmt import MeshSet
from ..core.model import anatomical_axes
from ..core.names import parse_roi
from .geometry import Check

#: A pair's R member must lie within 60 degrees of the declared right. Real
#: pairs sit within 15 degrees of it; a mirrored space puts them near 180.
MIN_PAIR_COS = 0.5

#: |det| of the name- and body-derived frame must clear this. The three
#: directions are measured separately, so they are not exactly orthogonal;
#: the real frames give 0.92, a mirrored one the same magnitude negated.
MIN_HANDEDNESS = 0.3


def lateral_pairs(ms: MeshSet) -> list[tuple[str, int, int]]:
    """(bare name, index of L, index of R) for every name present on both sides."""
    sides: dict[str, dict[str, int]] = {}
    for i, name in enumerate(ms.names):
        bare, side = parse_roi(name)
        if side in ("L", "R"):
            sides.setdefault(bare, {})[side] = i
    return [(b, s["L"], s["R"]) for b, s in sorted(sides.items()) if len(s) == 2]


def check_lateral_sides(
    space, sets: Sequence[tuple[str, MeshSet]], min_cos: float = MIN_PAIR_COS
) -> Check | None:
    """Every X(R) must sit toward the fly's right of its X(L).

    "Right" is the space's declared anatomy, so this catches a space whose
    geometry was reflected, or whose labels were swapped, after its anatomy
    was measured. None when the space declares no anatomy or no set in it
    has a name on both sides.
    """
    frame = anatomical_axes(space)
    if frame is None:
        return None
    right = np.asarray(frame["R"], dtype=float)
    cosines: list[float] = []
    offenders: list[str] = []
    for label, ms in sets:
        for bare, left, rgt in lateral_pairs(ms):
            d = ms.centroid(rgt) - ms.centroid(left)
            n = float(np.linalg.norm(d))
            if not np.isfinite(n) or n == 0:
                continue
            cos = float(d @ right) / n
            cosines.append(cos)
            if cos <= min_cos:
                offenders.append(f"{label}:{bare} (cos {cos:+.2f})")
    if not cosines:
        return None
    return Check(
        f"laterality {space.id}",
        not offenders,
        f"{len(cosines) - len(offenders)}/{len(cosines)} L/R pairs put (R) toward "
        f"the declared right (min cos {min(cosines):+.2f}, need > {min_cos})",
        offenders,
    )


def name_axes(
    ms: MeshSet,
    canonical: Mapping[str, Sequence[str]] | None = None,
    default_side: str | None = None,
) -> tuple[np.ndarray, np.ndarray] | None:
    """Anterior and dorsal directions, read from glomerulus names.

    The first letter of a glomerulus name places it dorsally or ventrally
    (D/V); the second, where it is A or P, anteriorly or posteriorly. The
    contrast of the two groups' mean centroids is an axis, computed per lobe
    and then averaged, so a lobe with more glomeruli cannot tilt it.
    """
    lobes: dict[str | None, list[tuple[str, np.ndarray]]] = {}
    for i, name in enumerate(ms.names):
        glom, side = parse_roi(name)
        label = (tuple((canonical or {}).get(name) or ()) or (glom,))[0].upper()
        lobes.setdefault(side or default_side, []).append((label, ms.centroid(i)))

    def contrast(members, pos: str, neg: str, at: int):
        p = [c for n, c in members if len(n) > at and n[at] == pos]
        q = [c for n, c in members if len(n) > at and n[at] == neg]
        if len(p) < 3 or len(q) < 3:
            return None
        v = np.mean(p, axis=0) - np.mean(q, axis=0)
        return v / np.linalg.norm(v)

    anterior, dorsal = [], []
    for members in lobes.values():
        a, d = contrast(members, "A", "P", 1), contrast(members, "D", "V", 0)
        if a is not None and d is not None:
            anterior.append(a)
            dorsal.append(d)
    if not anterior:
        return None
    a, d = np.mean(anterior, axis=0), np.mean(dorsal, axis=0)
    return a / np.linalg.norm(a), d / np.linalg.norm(d)


def _body_volume(v: np.ndarray, f: np.ndarray) -> float:
    """Enclosed volume when closed; the convex hull's otherwise."""
    import trimesh

    mesh = trimesh.Trimesh(vertices=v, faces=f, process=False)
    return float(abs(mesh.volume) if mesh.is_watertight else mesh.convex_hull.volume)


def check_chirality(
    space,
    glomeruli: MeshSet,
    neuropil: MeshSet,
    canonical: Mapping[str, Sequence[str]] | None = None,
    glom_side: str | None = None,
) -> Check | None:
    """The data's own handedness must match the space's lateral convention.

    Nothing declared is trusted here. Anterior and dorsal come from
    glomerulus names, and the fly's right from the asymmetric body: the
    larger AB is the right one, whatever it is labeled. In a right-handed
    array frame a real brain has det[A, D, R] = +1, and a left-right
    inverted image (`lateral_convention = "mirrored"`, FAFB) has -1. A
    whole space reflected -- geometry, labels and declared anatomy all
    consistent with each other -- fails only this.

    Also fails when the larger AB is labeled L: then the side labels, not
    the geometry, are swapped. None when the space has no AB pair or too
    few named glomeruli to give axes.
    """
    ab = {}
    for i, name in enumerate(neuropil.names):
        bare, side = parse_roi(name)
        if bare.upper() == "AB" and side in ("L", "R"):
            ab[side] = i
    if set(ab) != {"L", "R"}:
        return None
    axes = name_axes(glomeruli, canonical, glom_side)
    if axes is None:
        return None
    vol = {s: _body_volume(*neuropil.compartment(i)) for s, i in ab.items()}
    big, small = ("R", "L") if vol["R"] >= vol["L"] else ("L", "R")
    right = neuropil.centroid(ab[big]) - neuropil.centroid(ab[small])
    right = right / np.linalg.norm(right)
    det = float(np.linalg.det(np.column_stack([axes[0], axes[1], right])))
    expect = -1.0 if space.is_mirrored else 1.0
    labels_ok = big == "R"
    handed_ok = det * expect > MIN_HANDEDNESS
    return Check(
        f"chirality {space.id}",
        labels_ok and handed_ok,
        f"AB(R) {vol['R']:.0f} um3 vs AB(L) {vol['L']:.0f} um3 "
        f"({vol[big] / vol[small]:.1f}x on the {big}"
        f"{'' if labels_ok else ', so the side labels are swapped'}); "
        f"det[A, D, R] {det:+.2f} from glomerulus names and the larger AB, "
        f"{space.lateral_convention} expects {'+' if expect > 0 else '-'}",
    )
