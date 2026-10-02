"""Geometry validation.

A transform bug does not raise. It draws a plausible antennal lobe in the wrong
place. These checks exist to turn that into a failure.

One deliberate asymmetry: containment and scale are ASSERTIONS (a violation is
a bug), while cross-atlas correspondence only REPORTS. Two atlases disagreeing
after a bridge may be a bridging error or may be a real anatomical
disagreement, and that distinction is a research finding, not a test failure.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..core.meshfmt import MeshSet
from ..core.names import parse_roi


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

    These are APPARENT sides -- which half of the image the geometry occupies.
    This is a geometric test, so it must not be given biological sides in a
    mirrored space (see Space.apparent_side).

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


def correspondence_report(
    a: MeshSet,
    b: MeshSet,
    a_label: str = "A",
    b_label: str = "B",
    a_side: str | None = None,
    b_side: str | None = None,
) -> tuple[list[Pairing], Check]:
    """Centroid separation for same-named compartments in a shared space.

    `a_side` / `b_side` supply laterality for atlases whose published names
    omit it. Bates 2020 is a left-AL atlas but names its glomeruli bare
    ("VP1d"), so side is a property of the asset, not of the name -- without
    this, nothing pairs against hemibrain's "AL-VP1d(L)".

    REPORTS rather than asserts. A large separation may be a bridging error or
    a genuine disagreement between segmentations; deciding which is the
    scientific question this application exists to support.
    """

    def index(ms: MeshSet, default_side: str | None) -> dict[tuple[str, str | None], int]:
        out = {}
        for i, name in enumerate(ms.names):
            glom, side = parse_roi(name)
            out[(glom.upper(), side or default_side)] = i
        return out

    ia, ib = index(a, a_side), index(b, b_side)
    pairs: list[Pairing] = []
    for key, i in sorted(ia.items()):
        j = ib.get(key)
        if j is None:
            continue
        d = float(np.linalg.norm(a.centroid(i) - b.centroid(j)))
        pairs.append(Pairing(key[0], a.names[i], b.names[j], d))

    if not pairs:
        return pairs, Check(
            f"correspondence {a_label} vs {b_label}", False, "no shared names"
        )
    ds = np.array([p.distance_um for p in pairs])
    return pairs, Check(
        f"correspondence {a_label} vs {b_label}",
        True,
        f"{len(pairs)} shared, centroid separation median "
        f"{np.median(ds):.1f} um, p90 {np.percentile(ds, 90):.1f} um, "
        f"max {ds.max():.1f} um ({max(pairs, key=lambda p: p.distance_um).canonical})",
    )
