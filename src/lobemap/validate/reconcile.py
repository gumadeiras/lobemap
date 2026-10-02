"""Geometric reconciliation of nomenclature between atlases in one space.

Matching compartments by name is not safe. Bates 2020 and Benton 2025 share
essentially identical geometry but relabel it in a chain -- Bates VC3l/VC3m/VC5
are Benton VC3/VC5/VM6 -- so a name-based join silently pairs Bates VC3m with
Benton VC3m's *successor* and reports a spurious disagreement, while hiding the
real one.

Pairing by geometry first and comparing names second turns that into a finding.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..core.meshfmt import MeshSet
from ..core.names import normalize, parse_roi


@dataclass
class Match:
    a_name: str
    b_name: str
    distance_um: float
    agrees: bool

    @property
    def relation(self) -> str:
        return "exact" if self.agrees else "renamed"


def reconcile(
    a: MeshSet,
    b: MeshSet,
    max_distance_um: float = 5.0,
    ambiguity_ratio: float = 0.5,
) -> tuple[list[Match], list[str], list[str]]:
    """Mutually-nearest centroid matching between two meshsets.

    Returns (matches, unmatched_a, unmatched_b).

    A match must be mutually nearest, within `max_distance_um`, AND
    unambiguous: the nearest candidate must be closer than
    `ambiguity_ratio` x the second-nearest. Without that last test the method
    is only safe when the two atlases share geometry. Neighboring glomeruli
    sit ~10 um apart, so for atlases from different animals -- where
    corresponding glomeruli are already 6-8 um apart after bridging -- plain
    nearest-centroid matching confidently pairs the wrong structures and
    reports them as renames. Requiring a clear margin makes the method decline
    instead of guessing.
    """
    ca = np.array([a.centroid(i) for i in range(a.n_compartments)])
    cb = np.array([b.centroid(i) for i in range(b.n_compartments)])
    if not len(ca) or not len(cb):
        return [], list(a.names), list(b.names)

    d = np.linalg.norm(ca[:, None, :] - cb[None, :, :], axis=2)
    nearest_b = d.argmin(axis=1)
    nearest_a = d.argmin(axis=0)

    matches: list[Match] = []
    used_b: set[int] = set()
    for i, j in enumerate(nearest_b):
        if nearest_a[j] != i or d[i, j] > max_distance_um:
            continue
        # Ambiguity test against the runner-up in each direction.
        row = np.sort(d[i])
        col = np.sort(d[:, j])
        second = min(row[1] if len(row) > 1 else np.inf,
                     col[1] if len(col) > 1 else np.inf)
        if second <= 0 or d[i, j] > ambiguity_ratio * second:
            continue
        name_a = parse_roi(a.names[i])[0]
        name_b = parse_roi(b.names[j])[0]
        matches.append(
            Match(
                a.names[i],
                b.names[j],
                float(d[i, j]),
                normalize(name_a) == normalize(name_b),
            )
        )
        used_b.add(j)

    matched_a = {m.a_name for m in matches}
    return (
        matches,
        [n for n in a.names if n not in matched_a],
        [n for j, n in enumerate(b.names) if j not in used_b],
    )


def format_report(
    matches: list[Match],
    unmatched_a: list[str],
    unmatched_b: list[str],
    a_label: str = "A",
    b_label: str = "B",
) -> str:
    disagree = [m for m in matches if not m.agrees]
    header = (
        f"{a_label} vs {b_label}: {len(matches)} geometric matches, "
        f"{len(disagree)} name disagreements"
    )
    lines = [header]
    for m in sorted(disagree, key=lambda m: m.a_name):
        lines.append(
            f"    RENAMED  {m.a_name:<10} -> {m.b_name:<10} ({m.distance_um:.2f} um apart)"
        )
    if unmatched_a:
        lines.append(f"    only in {a_label}: {', '.join(sorted(unmatched_a))}")
    if unmatched_b:
        lines.append(f"    only in {b_label}: {', '.join(sorted(unmatched_b))}")
    return "\n".join(lines)
