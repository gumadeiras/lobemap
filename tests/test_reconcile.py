"""Tests for geometric reconciliation and curated-name cleaning."""

from __future__ import annotations

import numpy as np
import pytest

from lobemap.core.meshfmt import MeshSet
from lobemap.core.names import clean_reference_name
from lobemap.validate.reconcile import reconcile

trimesh = pytest.importorskip("trimesh")


def box(offset, size=8.0):
    m = trimesh.creation.box(extents=(size, size, size))
    return np.asarray(m.vertices) + np.asarray(offset), np.asarray(m.faces)


def grid(names, spacing=30.0, jitter=0.0):
    parts = []
    for i, n in enumerate(names):
        off = np.array([i * spacing, 0.0, 0.0]) + jitter
        parts.append((n, *box(off)))
    return MeshSet.from_parts(parts)


def test_identical_geometry_matches_and_detects_renames():
    a = grid(["VC3l", "VC3m", "VC5"])
    b = grid(["VC3", "VC5", "VM6"])  # the Bates -> Benton rename chain
    matches, ua, ub = reconcile(a, b)
    assert len(matches) == 3
    assert not ua and not ub
    assert [(m.a_name, m.b_name) for m in matches] == [
        ("VC3l", "VC3"), ("VC3m", "VC5"), ("VC5", "VM6")
    ]
    assert all(m.relation == "renamed" for m in matches)


def test_same_names_report_as_exact():
    a = grid(["DA1", "DM6"])
    b = grid(["DA1", "DM6"])
    matches, _, _ = reconcile(a, b)
    assert all(m.relation == "exact" for m in matches)


def test_ambiguous_pairings_are_declined():
    """Regression: without an ambiguity test this invented 10 renames between
    hemibrain and male CNS, which share one nomenclature."""
    a = grid(["A", "B", "C"], spacing=10.0)
    # Offset by nearly half the spacing: every match is ambiguous.
    b = grid(["A", "B", "C"], spacing=10.0, jitter=4.6)
    matches, ua, ub = reconcile(a, b, max_distance_um=8.0)
    assert matches == [], f"should have declined, got {matches}"
    assert len(ua) == 3 and len(ub) == 3


def test_unmatched_compartments_are_reported_not_forced():
    a = grid(["DA1", "DM6"])
    b = grid(["DA1"])
    matches, ua, ub = reconcile(a, b)
    assert len(matches) == 1
    assert ua == ["DM6"] and ub == []


@pytest.mark.parametrize(
    "raw,expect",
    [
        ("VM6l*(new)", "VM6l"),
        ("VM6m (new)", "VM6m"),
        ("VM6v (VM6)", "VM6v"),
        ("VC3", "VC3"),
        ("AL-DA1(R)", "AL-DA1(R)"),   # laterality must survive
    ],
)
def test_clean_reference_name(raw, expect):
    assert clean_reference_name(raw) == expect
