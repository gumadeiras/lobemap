"""Tests for resolve() and the validation harness.

Cache-key and unit logic is tested offline with a fake transform backend;
only the tests that genuinely exercise navis are marked `needs_flybrains`.
"""

from __future__ import annotations

import numpy as np
import pytest

from lobemap.core import resolve as R
from lobemap.core.meshfmt import MeshSet
from lobemap.validate import geometry as G

needs_flybrains = pytest.mark.skipif(
    not __import__("lobemap.core.spaces", fromlist=["x"]).available(),
    reason="navis/flybrains not installed",
)


def cube(offset=(0.0, 0.0, 0.0), size=10.0):
    v = np.array(
        [
            [0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0],
            [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1],
        ],
        dtype=float,
    ) * size + np.asarray(offset)
    f = np.array(
        [
            [0, 1, 2], [0, 2, 3], [4, 6, 5], [4, 7, 6],
            [0, 4, 5], [0, 5, 1], [1, 5, 6], [1, 6, 2],
            [2, 6, 7], [2, 7, 3], [3, 7, 4], [3, 4, 0],
        ]
    )
    return v, f


def meshset(names=("AL-A(R)", "AL-B(R)")):
    return MeshSet.from_parts(
        [(n, *cube((i * 20.0, 0, 0))) for i, n in enumerate(names)],
        meta={"units": "um"},
    )


# -- cache key ----------------------------------------------------------


def base_key(**over):
    kw = {
        "source_hash": "abc",
        "source_space": "A",
        "target_space": "B",
        "mirror": False,
        "path": ("A", "B"),
        "tool_versions": (("navis", "1.0"),),
    }
    kw.update(over)
    return R.ResolveKey(**kw)


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_hash", "def"),
        ("target_space", "C"),
        ("mirror", True),
        ("path", ("A", "X", "B")),
        ("tool_versions", (("navis", "1.1"),)),
    ],
)
def test_cache_key_is_sensitive_to(field, value):
    """Each of these must miss the cache. A stale hit is silent corruption."""
    assert base_key().digest() != base_key(**{field: value}).digest()


def test_cache_key_is_stable():
    assert base_key().digest() == base_key().digest()


# -- validation harness (no transforms needed) --------------------------


def test_check_scale_catches_a_unit_error():
    ms = meshset()
    assert G.check_scale(ms, expect_um=(4.0, 45.0)).passed
    # The same geometry read as nanometers: 1000x too big.
    blown = ms.transformed(ms.vertices * 1000.0)
    bad = G.check_scale(blown, expect_um=(4.0, 45.0))
    assert not bad.passed
    assert "median compartment extent" in bad.detail


def test_containment_flags_a_glomerulus_outside_its_shell():
    shell = MeshSet.from_parts([("AL(R)", *cube(size=100.0))])
    inside = MeshSet.from_parts([("AL-A(R)", *cube((40, 40, 40), size=10.0))])
    outside = MeshSet.from_parts([("AL-A(R)", *cube((500, 500, 500), size=10.0))])
    assert G.check_containment(inside, shell).passed
    bad = G.check_containment(outside, shell)
    assert not bad.passed or "advisory" in bad.detail
    assert bad.offenders


def test_correspondence_pairs_by_name_and_side():
    a = meshset(("AL-DA1(R)", "AL-DM6(R)"))
    b_shift = 3.0
    b = MeshSet.from_parts(
        [
            ("AL-DA1(R)", *cube((b_shift, 0, 0))),
            ("AL-DM6(R)", *cube((20 + b_shift, 0, 0))),
            ("AL-VA1v(R)", *cube((99, 0, 0))),  # unmatched
        ]
    )
    pairs, chk = G.correspondence_report(a, b)
    assert {p.canonical for p in pairs} == {"DA1", "DM6"}
    assert all(abs(p.distance_um - b_shift) < 1e-6 for p in pairs)
    # Correspondence REPORTS; disagreement is a finding, not a failure.
    assert chk.passed


def test_correspondence_does_not_pair_across_sides():
    a = MeshSet.from_parts([("AL-DA1(R)", *cube())])
    b = MeshSet.from_parts([("AL-DA1(L)", *cube())])
    pairs, chk = G.correspondence_report(a, b)
    assert pairs == []
    assert not chk.passed


# -- transforms ---------------------------------------------------------


@needs_flybrains
def test_template_scale_to_um():
    assert R.template_scale_to_um("FAFB14") == pytest.approx(1e-3)
    assert R.template_scale_to_um("JRC2018U") == pytest.approx(1.0)
    with pytest.raises(KeyError):
        R.template_scale_to_um("NOT_A_TEMPLATE")


@needs_flybrains
def test_identity_bridge_is_a_noop():
    ms = meshset()
    out = R.resolve_meshset(
        ms, "S", "S", "FAFB14", "FAFB14", mirror=False, use_cache=False
    )
    assert out is ms


@needs_flybrains
def test_roundtrip_preserves_position():
    """um -> native -> transform -> back -> um must be self-consistent."""
    pts = np.array([[100.0, 120.0, 90.0], [110.0, 125.0, 95.0]])
    there, rec = R.resolve_points(pts, "JRCFIB2018F", "FAFB14")
    back, _ = R.resolve_points(there, "FAFB14", "JRCFIB2018F")
    assert rec["n_nonfinite"] == 0
    assert np.abs(back - pts).max() < 1.0  # um


@needs_flybrains
def test_bridge_records_the_resolved_route():
    ms = meshset()
    out = R.resolve_meshset(
        ms, "HB", "FAFB", "JRCFIB2018F", "FAFB14", use_cache=False
    )
    params = out.meta["derivation"]["params"]
    assert params["path"][0] == "JRCFIB2018F"
    assert params["path"][-1] == "FAFB14"
    assert params["n_warps"] >= 1
    assert out.meta["derivation"]["tool_versions"]["navis"]
    # Topology is preserved; only positions move.
    assert out.names == ms.names
    assert np.array_equal(out.faces, ms.faces)


@needs_flybrains
def test_mirror_is_applied_before_bridging():
    """Mirror-then-bridge must differ from bridge-then-mirror.

    Guards the ordering rule: hemibrain has no mirror registration, so a
    mirror applied on that side is a bounding-box reflection, not a midline
    one, and it fails silently.
    """
    pts = np.array([[100.0, 120.0, 90.0]])
    mirror_first, _ = R.resolve_points(
        pts, "FAFB14", "JRCFIB2018F", mirror=True
    )
    bridged, _ = R.resolve_points(pts, "FAFB14", "JRCFIB2018F")
    from lobemap.core import spaces as sp

    bridge_then_mirror = sp.mirror(bridged / 1e-3, "JRCFIB2018F") * 1e-3
    assert not np.allclose(mirror_first, bridge_then_mirror, atol=1.0)


# -- containment side fallback ------------------------------------------


def shell(name="AL(R)", size=100.0):
    return MeshSet.from_parts([(name, *cube((0, 0, 0), size=size))])


def test_containment_with_sideless_names_needs_a_default():
    """Regression: a check that examined nothing used to report 0/0 and PASS.

    Schlegel S11/S12 name their glomeruli bare ("DA1"), so laterality cannot
    be read from the name and every compartment was skipped.
    """
    gloms = MeshSet.from_parts([("DA1", *cube((40, 40, 40), size=10.0))])
    without = G.check_containment(gloms, shell())
    assert not without.passed, "a vacuous 0/0 must not pass"
    assert "0/0" in without.detail

    with_default = G.check_containment(gloms, shell(), glom_side="R")
    assert with_default.passed
    assert "1/1" in with_default.detail


def test_containment_default_side_can_still_fail():
    outside = MeshSet.from_parts([("DA1", *cube((500, 500, 500), size=10.0))])
    check = G.check_containment(outside, shell(), glom_side="R")
    assert check.offenders
    assert not check.passed or "advisory" in check.detail


def test_containment_single_unsided_shell_contains_everything():
    """A whole-brain mesh has no side; it should still constrain."""
    brain = MeshSet.from_parts([("brain", *cube((0, 0, 0), size=200.0))])
    inside = MeshSet.from_parts([("DA1", *cube((90, 90, 90), size=10.0))])
    check = G.check_containment(inside, brain)
    assert "1/1" in check.detail


# -- points a transform does not cover ------------------------------------


@pytest.fixture
def uncovered_point(monkeypatch):
    """A fake nm -> um bridge that leaves point 1 outside its field (NaN)."""
    import navis

    from lobemap.core import spaces as sp

    def xform(p, source, target, **kw):
        out = np.asarray(p, float) * 1e-3 + 1.0
        out[1] = np.nan
        return out

    monkeypatch.setattr(navis, "xform_brain", xform)
    monkeypatch.setattr(sp, "choose_path", lambda s, t, allow_binary=None: {
        "path": [s, t], "classes": ["h5reg"], "n_warps": 1, "needs_binary": False})
    monkeypatch.setattr(R, "template_scale_to_um",
                        lambda t: {"NM": 1e-3, "UM": 1.0}[t])
    return np.array([[100.0, 200.0, 50.0], [110.0, 210.0, 55.0], [120.0, 220.0, 60.0]])


def test_an_uncovered_point_is_counted(uncovered_point):
    _out, rec = R.resolve_points(uncovered_point, "NM", "UM")
    assert rec["n_nonfinite"] == 1
    assert rec["frac_nonfinite"] == pytest.approx(1 / 3)


def test_an_uncovered_point_keeps_its_position_in_micrometers(uncovered_point):
    """Not in the source template's nm, which lands it 1000x too far out."""
    out, _rec = R.resolve_points(uncovered_point, "NM", "UM")
    np.testing.assert_allclose(out[1], uncovered_point[1])
    np.testing.assert_allclose(out[0], uncovered_point[0] + 1.0)
