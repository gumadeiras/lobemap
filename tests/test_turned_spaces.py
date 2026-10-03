"""Turning the view in the real spaces, as `lobemap view` opens them.

The rules are proven on synthetic data in `test_turned_view.py`; here each
space is opened with its own meshes and images and checked for what can go
wrong only with real data: the contours against trimesh on a real atlas,
the image and contours sharing one placement, Home and the triads in 3D,
rest given back to the bit, a switch, and a scene torn down while turned.
"""

from __future__ import annotations

import numpy as np
import pytest
import turned_harness as th
from viewer_harness import SPACES, launched, pump, session, switch_to

napari = pytest.importorskip("napari")

pytestmark = pytest.mark.requires_data


def _open(registry, space, ndisplay):
    from lobemap.viewer.app import load_space

    viewer = napari.Viewer(show=False, ndisplay=ndisplay)
    sess = load_space(viewer, registry, space, fit=False)
    th.settle_canvas(viewer)
    return viewer, sess


def _contour_vs_trimesh(viewer, sess, to_mesh=None, tol_um=2e-4) -> int:
    """Every loop of the primary atlas against trimesh; the count compared."""
    name = sess.registry.primary_atlas(sess.space).id
    contour = sess.contours[name]
    axis = int(viewer.dims.order[0])
    shown = list(viewer.dims.displayed)
    world = np.zeros((3, 3))
    world[:, axis] = float(viewer.dims.point[axis])
    world[1, shown[0]] += 10.0
    world[2, shown[1]] += 10.0
    plane = np.array([contour.layer.world_to_data(w) for w in world], float)
    if to_mesh is not None:
        plane = to_mesh(plane)
    normal = np.cross(plane[1] - plane[0], plane[2] - plane[0])
    by_owner: dict[int, list] = {}
    for owner, loop in th.loops_in_mesh(contour, to_mesh):
        by_owner.setdefault(owner, []).append(loop)
    for owner, drawn in by_owner.items():
        want = th.trimesh_loops(contour.meshset, owner, plane[0], normal)
        assert want and th.hausdorff(drawn, want) <= tol_um, (sess.space, owner)
    return len(by_owner)


@pytest.mark.parametrize("space", SPACES)
def test_a_spun_section_in_every_space(registry, space):
    """Exact contours, the images placed with them, and rest to the bit."""
    viewer, sess = _open(registry, space, 2)
    try:
        before, pixels = th.state(viewer), th.render(viewer)
        for mirrored in (False, True):
            sess.set_mirror(mirrored)
            for spin in (37.0, 90.0, 180.0):
                sess.set_rotation(spin, 0, 0)
                th.settle_canvas(viewer)
                assert _contour_vs_trimesh(viewer, sess) > 0
                name = sess.registry.primary_atlas(space).id
                contour = sess.contours[name]
                m = contour.meshset.vertices[:: max(1, len(contour.meshset.vertices) // 50)]
                for image in sess.images:
                    got = np.array([image.world_to_data(contour.layer.data_to_world(p))
                                    for p in m])
                    want = (np.asarray(m, float) - np.asarray(image.translate)) / np.asarray(
                        image.scale)
                    assert np.allclose(got, want, atol=1e-6), (space, image.name)
            sess.set_rotation(0, 0, 0)
        sess.set_mirror(False)
        th.settle_canvas(viewer)
        assert th.state(viewer) == before
        assert np.array_equal(th.render(viewer), pixels)
    finally:
        viewer.close()
        pump()


@pytest.mark.parametrize("space", SPACES)
def test_3d_faces_home_turned_in_every_space(registry, space):
    from lobemap.core.model import anatomical_axes
    from lobemap.viewer.rotation import turned_view

    viewer, sess = _open(registry, space, 3)
    try:
        camera = viewer.scene.camera
        frame = anatomical_axes(registry.spaces[space])
        view0, up0 = -np.asarray(frame["A"]), np.asarray(frame["D"])
        placed = [np.asarray(layer.affine.affine_matrix) for layer in viewer.layers]
        before = th.state(viewer)
        for angles in ((37, 0, 0), (0, 37, 0), (15, -60, 120)):
            sess.set_rotation(*angles)
            v, u = turned_view(view0, up0, angles)
            assert np.allclose(camera.view_direction, v, atol=1e-6)
            assert np.allclose(camera.up_direction, u, atol=1e-6)
            assert all(np.array_equal(p, layer.affine.affine_matrix)
                       for p, layer in zip(placed, viewer.layers, strict=True))
        sess.set_rotation(0, 0, 0)
        assert th.state(viewer) == before
    finally:
        viewer.close()
        pump()


def test_a_turn_is_set_right_after_a_switch_and_torn_down_with_its_scene(monkeypatch):
    """The switcher hands the new scene the old one's angles; nothing of a
    scene torn down while turned stays behind."""
    from napari.components.layerlist import LayerList
    from viewer_harness import handler_counts

    from lobemap.viewer import rotation

    with launched(monkeypatch, "view", "GRABE", "--ndisplay", "2") as (code, viewer):
        assert code == 0
        old = session(viewer)
        th.settle_canvas(viewer)
        counts = handler_counts(viewer)
        old.set_rotation(30, 0, 0)
        assert rotation.owner(viewer) is old.turned
        for target, ndisplay in (("JRCFIB2018F", 2), ("GRABE", 3), ("FAFB14", 2)):
            viewer.dims.ndisplay = ndisplay
            switch_to(viewer, target)
            new = session(viewer)
            assert new is not old and new.space == target
            assert type(viewer.layers) is LayerList
            assert rotation.owner(viewer) is new.turned
            new.set_rotation(*old.rotation)
            th.settle_canvas(viewer)
            assert new.rotation == (30.0, 0.0, 0.0)
            if ndisplay == 2:
                assert _contour_vs_trimesh(viewer, new) > 0
            old = new
        old.set_rotation(0, 0, 0)
        viewer.dims.ndisplay = 2
        assert handler_counts(viewer) == counts
