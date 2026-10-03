"""Geometry validation.

A transform bug does not raise. It draws a plausible antennal lobe in the wrong
place. These checks exist to turn that into a failure.

One deliberate asymmetry: containment and scale are ASSERTIONS (a violation is
a bug), while cross-atlas correspondence only REPORTS. Two atlases disagreeing
after a bridge may be a bridging error or may be a real anatomical
disagreement, and that distinction is a research finding, not a test failure.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

import numpy as np

from ..core.meshfmt import MeshSet
from ..core.names import normalize, parse_roi


@dataclass
class Check:
    name: str
    passed: bool
    detail: str
    offenders: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        mark = "PASS" if self.passed else "FAIL"
        extra = ""
        if self.offenders:
            shown = ", ".join(self.offenders[:8])
            more = f" (+{len(self.offenders) - 8})" if len(self.offenders) > 8 else ""
            extra = f"\n      offenders: {shown}{more}"
        return f"  [{mark}] {self.name}: {self.detail}{extra}"


def _side_of(name: str) -> str | None:
    return parse_roi(name)[1]


def check_scale(
    ms: MeshSet, expect_um: tuple[float, float] = (4.0, 45.0), label: str = ""
) -> Check:
    """Median compartment size must be anatomically plausible.

    This is the nm/um tripwire: a factor-1000 error cannot survive it.
    """
    sizes = np.array(
        [
            float(np.max(ms.compartment(i)[0].max(0) - ms.compartment(i)[0].min(0)))
            for i in range(ms.n_compartments)
        ]
    )
    med = float(np.median(sizes))
    lo, hi = expect_um
    return Check(
        f"scale{' ' + label if label else ''}",
        lo <= med <= hi,
        f"median compartment extent {med:.1f} um (expect {lo}-{hi})",
    )


#: A glomerulus whose convex hull is under this fraction of its atlas's
#: median is not a glomerulus. Real ones sit at 5% and up -- the smallest is
#: hemibrain DA4m(R) at 5.5%, truncated by the imaged volume -- so a floor of
#: 2% leaves room for anatomy and none for a collapsed mesh.
MIN_SIZE_FRACTION = 0.02


def hull_volume(vertices: np.ndarray) -> float:
    """Convex-hull volume in um3; 0 for a flat or empty set.

    The hull rather than the enclosed volume, because it is defined for an
    open mesh -- several male CNS glomeruli have holes -- and still goes to
    zero for a mesh that collapsed.
    """
    import trimesh

    if len(vertices) < 4:
        return 0.0
    try:
        return float(trimesh.convex.convex_hull(np.asarray(vertices, float)).volume)
    except Exception:  # noqa: BLE001 - qhull rejects flat input
        return 0.0


def check_compartment_sizes(
    ms: MeshSet,
    label: str = "",
    min_fraction: float = MIN_SIZE_FRACTION,
    known: Mapping[str, str] | None = None,
) -> Check:
    """No compartment may be a sliver of its atlas's typical size.

    The median-extent scale check cannot see one bad compartment: a
    glomerulus that collapsed to a point leaves the median where it was.

    `known` names compartments already examined and recorded as defective
    in the source (registry/checks.toml). They are still listed, so the
    defect stays visible, but they do not fail the check.
    """
    known = known or {}
    hulls = np.array([hull_volume(ms.compartment(i)[0]) for i in range(ms.n_compartments)])
    med = float(np.median(hulls)) if len(hulls) else 0.0
    floor = min_fraction * med
    small = [(ms.names[i], float(hulls[i])) for i in np.argsort(hulls) if hulls[i] < floor]
    unknown = [n for n, _ in small if n not in known]
    offenders = [
        f"{n} ({vol:.0f} um3{', known: ' + known[n] if n in known else ''})"
        for n, vol in small
    ]
    return Check(
        f"compartment size{' ' + label if label else ''}",
        med > 0 and not unknown,
        f"{len(small)} below {floor:.0f} um3 ({min_fraction:.0%} of the median "
        f"convex hull, {med:.0f} um3), {len(small) - len(unknown)} of them known",
        offenders,
    )


def check_containment(
    glom: MeshSet,
    neuropil: MeshSet,
    tolerance_um: float = 2.0,
    glom_side: str | None = None,
    shell_side: str | None = None,
    shell_name: str | None = "AL",
) -> Check:
    """Every glomerulus centroid must fall inside its own side's AL.

    `glom_side` / `shell_side` supply laterality for meshes whose names omit
    it. Schlegel S11/S12 name their glomeruli bare ("DA1"), so without this the
    check silently tests nothing and reports a vacuous 0/0 pass.

    Both sides must use the SAME convention, and the one names and assets
    record is biological: FlyWire's `AL_L` is the fly's left lobe, and
    Benton's asset says `L` for the same lobe. The side only pairs a
    glomerulus with its shell here, so converting just one of the two to
    apparent side would pair a mirrored space's glomeruli with the other lobe.

    `shell_name` picks WHICH neuropil to test against, by bare name. It is not
    optional in practice: the FAFB neuropil layer holds all 78 neuropils, and
    keying only on side meant whichever L and R compartment happened to come
    last -- WED, alphabetically -- became "the AL", so every antennal lobe
    glomerulus tested as outside. Two compartments claiming one side without a
    name to choose between them is now an error rather than a silent pick.

    Uses a watertight point-in-mesh test when trimesh is available, and falls
    back to the neuropil bounding box otherwise -- weaker, but still catches a
    glomerulus landing in the wrong hemisphere or outside the brain.
    """
    shells: dict[str, tuple[int, MeshSet]] = {}
    claimed: dict[str, list[str]] = {}
    for i, name in enumerate(neuropil.names):
        bare, side = parse_roi(name)
        side = side or shell_side
        if not side and len(neuropil.names) == 1:
            # A single unsided shell (a whole-brain mesh) contains everything,
            # whatever it is called -- the name filter cannot apply.
            shells["*"] = (i, neuropil)
            continue
        if shell_name is not None and bare != shell_name:
            continue
        if side:
            claimed.setdefault(side, []).append(name)
            shells[side] = (i, neuropil)

    ambiguous = {s: n for s, n in claimed.items() if len(n) > 1}
    if ambiguous:
        raise ValueError(
            f"several neuropils claim the same side {ambiguous}; pass "
            f"shell_name to say which one the glomeruli should sit inside"
        )
    if shell_name is not None and not shells:
        raise ValueError(
            f"no neuropil compartment named {shell_name!r} in "
            f"{neuropil.names[:6]}{'...' if len(neuropil.names) > 6 else ''}"
        )

    meshes: dict = {}
    method = "bounding-box"
    try:
        import trimesh

        built = {}
        for side, (i, npl) in shells.items():
            v, f = npl.compartment(i)
            built[side] = trimesh.Trimesh(vertices=v, faces=f, process=False)
        # Probe the ray engine before relying on it: trimesh.contains needs
        # rtree, and an ImportError here must degrade, not crash the harness.
        if built:
            probe = next(iter(built.values()))
            probe.contains(np.zeros((1, 3)))
        meshes = built
        method = "point-in-mesh"
    except Exception:  # noqa: BLE001 - any engine failure -> boxes
        meshes = {}
        method = "bounding-box (trimesh ray engine unavailable)"

    # A shell with holes cannot support an authoritative inside/outside test.
    # neuPrint's male CNS AL meshes are ~7k vertices and NOT watertight, while
    # hemibrain's are ~27k. Rather than pretend, downgrade to advisory.
    watertight = all(getattr(m, "is_watertight", False) for m in meshes.values())

    offenders: list[str] = []
    tested = 0
    skipped_no_side = 0
    for i, name in enumerate(glom.names):
        side = _side_of(name) or glom_side
        if side not in shells:
            side = "*" if "*" in shells else side
        if side not in shells:
            skipped_no_side += 1
            continue
        tested += 1
        c = glom.centroid(i)
        if side in meshes:
            if not bool(meshes[side].contains(c.reshape(1, 3))[0]):
                d = float(
                    np.abs(
                        trimesh.proximity.signed_distance(
                            meshes[side], c.reshape(1, 3)
                        )
                    )[0]
                )
                if d > tolerance_um:
                    offenders.append(f"{name} ({d:.1f} um outside)")
        else:
            v, _ = shells[side][1].compartment(shells[side][0])
            lo, hi = v.min(0) - tolerance_um, v.max(0) + tolerance_um
            if not np.all((c >= lo) & (c <= hi)):
                offenders.append(name)

    qualifier = "" if watertight else ", shell NOT watertight -> advisory"
    if skipped_no_side:
        qualifier += f", {skipped_no_side} unmatched to a shell"
    return Check(
        "containment",
        # A test that examined nothing is not a pass.
        bool(tested) and ((not offenders) or not watertight),
        f"{tested - len(offenders)}/{tested} centroids inside their AL "
        f"({method}, tol {tolerance_um} um{qualifier})",
        offenders,
    )


def check_roundtrip(
    ms: MeshSet,
    source_template: str,
    via_template: str,
    tolerance_um: float = 10.0,
) -> Check:
    """A -> B -> A displacement must stay well under a glomerulus diameter."""
    from ..core.resolve import resolve_points

    there, _ = resolve_points(ms.vertices.astype(float), source_template, via_template)
    back, _ = resolve_points(there, via_template, source_template)
    d = np.linalg.norm(back - ms.vertices, axis=1)
    finite = d[np.isfinite(d)]
    med = float(np.median(finite)) if len(finite) else float("nan")
    p95 = float(np.percentile(finite, 95)) if len(finite) else float("nan")
    return Check(
        f"roundtrip {source_template}->{via_template}->{source_template}",
        bool(med < tolerance_um),
        f"median {med:.2f} um, p95 {p95:.2f} um, "
        f"{len(d) - len(finite)} non-finite (tol {tolerance_um})",
    )


@dataclass
class Pairing:
    canonical: str
    a_name: str
    b_name: str
    distance_um: float


def _group_centroid(ms: MeshSet, indices: list[int]) -> np.ndarray:
    """Vertex mean over several compartments, as `MeshSet.centroid` is for one."""
    return np.concatenate([ms.compartment(i)[0] for i in indices]).mean(axis=0)


def correspondence_report(
    a: MeshSet,
    b: MeshSet,
    a_label: str = "A",
    b_label: str = "B",
    a_side: str | None = None,
    b_side: str | None = None,
    a_canonical: Mapping[str, Sequence[str]] | None = None,
    b_canonical: Mapping[str, Sequence[str]] | None = None,
) -> tuple[list[Pairing], Check]:
    """Centroid separation for corresponding compartments in a shared space.

    Compartments correspond by CANONICAL name and side, not by published
    name. `a_canonical` / `b_canonical` map a published name to its canonical
    names (`Compartment.canonical`); a name with no entry falls back to its
    bare published glomerulus. A join on published names is wrong exactly
    where atlases disagree: hemibrain's `VC5(R)` is canonical VM6, so it was
    paired with Schlegel S12's `VC5` -- a different glomerulus 11 um away --
    and VC3l and VC3m were never paired at all.

    Correspondence is many-to-many, so pairing is over connected groups: the
    three S11 compartments VM6l, VM6m and VM6v all carry VM6 and are compared
    as one body against a single VM6. A group's position is the vertex mean
    over all its compartments.

    `a_side` / `b_side` supply laterality for atlases whose published names
    omit it: Schlegel S11/S12 name their glomeruli bare ("DA1"), so side is a
    property of the asset there. Sides are biological, so both meshsets must
    already share a biological frame -- see `resolve(..., align_biology=True)`.

    REPORTS rather than asserts. A large separation may be a bridging error or
    a genuine disagreement between segmentations; deciding which is the
    scientific question this application exists to support.
    """

    def keyed(ms: MeshSet, default_side, canonical) -> list[list[tuple[str, str | None]]]:
        out = []
        for name in ms.names:
            glom, side = parse_roi(name)
            names = tuple((canonical or {}).get(name) or ()) or (glom,)
            out.append([(n, side or default_side) for n in names])
        return out

    ka, kb = keyed(a, a_side, a_canonical), keyed(b, b_side, b_canonical)

    # Union-find over the compartments of both atlases, joined through the
    # (canonical name, side) keys they carry.
    parent: dict = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for tag, keys in (("a", ka), ("b", kb)):
        for i, carried in enumerate(keys):
            for n, side in carried:
                parent[find((tag, i))] = find(("key", normalize(n), side))

    groups: dict = {}
    for node in list(parent):
        if node[0] != "key":
            groups.setdefault(find(node), []).append(node)

    pairs: list[Pairing] = []
    only_a = only_b = 0
    for members in groups.values():
        ia = sorted(i for tag, i in members if tag == "a")
        ib = sorted(i for tag, i in members if tag == "b")
        if not ib:
            only_a += len(ia)
            continue
        if not ia:
            only_b += len(ib)
            continue
        spelled: dict[str, str] = {}
        for n, _side in [k for i in ia for k in ka[i]] + [k for j in ib for k in kb[j]]:
            spelled.setdefault(normalize(n), n)
        pairs.append(
            Pairing(
                ";".join(spelled[k] for k in sorted(spelled)),
                "+".join(a.names[i] for i in ia),
                "+".join(b.names[j] for j in ib),
                float(np.linalg.norm(_group_centroid(a, ia) - _group_centroid(b, ib))),
            )
        )
    pairs.sort(key=lambda p: (normalize(p.canonical), p.a_name))

    unpaired = f"; {only_a} only in {a_label}, {only_b} only in {b_label}"
    if not pairs:
        return pairs, Check(
            f"correspondence {a_label} vs {b_label}", False, "no shared names" + unpaired
        )
    ds = np.array([p.distance_um for p in pairs])
    return pairs, Check(
        f"correspondence {a_label} vs {b_label}",
        True,
        f"{len(pairs)} shared, centroid separation median "
        f"{np.median(ds):.1f} um, p90 {np.percentile(ds, 90):.1f} um, "
        f"max {ds.max():.1f} um ({max(pairs, key=lambda p: p.distance_um).canonical})"
        + unpaired,
    )
