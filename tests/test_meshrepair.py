"""Tests for watertight repair."""

from __future__ import annotations

import numpy as np
import pytest

from lobemap.core.meshfmt import MeshSet
from lobemap.core.meshrepair import repair_meshset, watertight_status

trimesh = pytest.importorskip("trimesh")


def closed_box(size=10.0, offset=(0.0, 0.0, 0.0)):
    m = trimesh.creation.box(extents=(size, size, size))
    return np.asarray(m.vertices) + np.asarray(offset), np.asarray(m.faces)


def open_box(size=10.0, drop=2):
    """A box with `drop` faces removed: a hole trimesh can close."""
    v, f = closed_box(size)
    return v, f[drop:]


def test_closed_mesh_is_left_alone():
    ms = MeshSet.from_parts([("AL-A(R)", *closed_box())])
    fixed, rep = repair_meshset(ms)
    assert rep.already_watertight == ["AL-A(R)"]
    assert rep.repaired == []
    assert np.allclose(fixed.vertices, ms.vertices)


def test_hole_is_repaired():
    ms = MeshSet.from_parts([("AL-A(R)", *open_box())])
    assert not all(watertight_status(ms).values())
    fixed, rep = repair_meshset(ms)
    assert rep.repaired == ["AL-A(R)"]
    assert rep.still_open == []
    assert all(watertight_status(fixed).values())


def test_repair_preserves_names_order_and_count():
    names = ("AL-A(R)", "AL-B(R)", "AL-C(L)")
    ms = MeshSet.from_parts(
        [
            ("AL-A(R)", *open_box()),
            ("AL-B(R)", *closed_box(offset=(30, 0, 0))),
            ("AL-C(L)", *open_box(drop=3)),
        ]
    )
    fixed, rep = repair_meshset(ms)
    assert tuple(fixed.names) == names
    assert fixed.n_compartments == 3
    assert rep.n_total == 3
    # Compartment 1 was already closed and must be untouched.
    assert np.allclose(fixed.compartment(1)[0], ms.compartment(1)[0])


def test_repair_is_recorded_in_meta():
    ms = MeshSet.from_parts([("AL-A(R)", *open_box())])
    fixed, _ = repair_meshset(ms)
    rec = fixed.meta["repaired"]
    assert rec["n_repaired"] == 1
    assert rec["n_still_open"] == 0
    assert rec["methods"]


def test_volume_change_is_measured_for_open_meshes():
    """Regression: `before` volume must not be gated on is_volume.

    trimesh reports is_volume False for an open mesh, so gating on it made the
    change metric read 0.0 for every repair -- hiding the large ones.
    """
    ms = MeshSet.from_parts([("AL-A(R)", *open_box(drop=4))])
    _, rep = repair_meshset(ms)
    assert rep.volume_change_pct, "no volume change recorded for a repair"
    assert rep.volume_change_pct["AL-A(R)"] != 0.0


def test_large_change_is_flagged():
    from lobemap.core.meshrepair import VOLUME_CHANGE_WARN_PCT, RepairReport

    r = RepairReport()
    r.volume_change_pct = {"small": 1.0, "big": -VOLUME_CHANGE_WARN_PCT - 1}
    assert set(r.large_changes) == {"big"}


def two_disconnected_open_boxes():
    """Mimics a glomerulus split into separate bodies by a segmentation break."""
    v1, f1 = open_box(size=10.0)
    v2, f2 = open_box(size=6.0)
    v2 = v2 + np.array([14.0, 0.0, 0.0])
    v = np.vstack([v1, v2])
    f = np.vstack([f1, f2 + len(v1)])
    return v, f


def test_disconnected_components_are_kept_not_discarded():
    """Regression: MeshFix keeps only the largest component by default, which
    silently deleted 35% of male CNS VP1l. Every real body must survive."""
    import trimesh

    v, f = two_disconnected_open_boxes()
    before = abs(trimesh.Trimesh(vertices=v, faces=f, process=False).volume)
    ms = MeshSet.from_parts([("AL-VP1l(R)", v, f)])
    fixed, rep = repair_meshset(ms)

    fv, ff = fixed.compartment(0)
    out = trimesh.Trimesh(vertices=fv, faces=ff, process=False)
    assert out.is_watertight, "union of closed components must be watertight"
    assert len(out.split()) == 2, "a whole body was discarded"
    assert abs(abs(out.volume) - before) / before < 0.10
    assert not rep.large_changes, rep.volume_change_pct
