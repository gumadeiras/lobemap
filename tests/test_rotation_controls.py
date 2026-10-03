"""The View dock's rotation and alignment controls, by what they do to the scene.

Each test drives the dock's own widgets -- the angle boxes, Reset rotation,
the alignment box, Home view and the Brain menu -- in a space opened as
`lobemap view` opens it, and reads back the camera, the plane on screen
through napari's canvas mapping, and the contours drawn on it against
trimesh. A widget's own text is checked only where the text is the point.
"""

from __future__ import annotations

import numpy as np
import pytest
import turned_harness as th
from test_aligned_view import _shown_frame
from test_turned_spaces import _center_on_the_atlas, _contour_vs_trimesh
from viewer_harness import launched, pump, session, switch_to, switcher

pytestmark = pytest.mark.requires_data
pytest.importorskip("napari")


def _home(sess) -> tuple[np.ndarray, np.ndarray]:
    """3D Home's view and up directions: facing the front, dorsal up."""
    from lobemap.core.model import anatomical_axes

    frame = anatomical_axes(sess.registry.spaces[sess.space])
    return -np.asarray(frame["A"], float), np.asarray(frame["D"], float)


def _set(sw, spin=None, tilt=None, turn=None) -> None:
    """Enter angles in the boxes, as a user does: one value at a time."""
    for box, value in zip(sw.rotation.boxes, (spin, tilt, turn), strict=True):
        if value is not None:
            box.setValue(value)
            pump()


def _faces(viewer, sess, angles) -> None:
    from lobemap.viewer.rotation import turned_view

    view, up = turned_view(*_home(sess), angles)
    camera = viewer.scene.camera
    assert np.allclose(camera.view_direction, view, atol=1e-6), angles
    assert np.allclose(camera.up_direction, up, atol=1e-6), angles


def _primary_contour(sess):
    return sess.contours[sess.registry.primary_atlas(sess.space).id]


def _aligned_base(viewer, sess) -> np.ndarray:
    """The anatomical frame nearest the grid's, as columns (right, up, toward):
    each grid direction's nearest anatomical one, by its own sign."""
    from lobemap.core.model import anatomical_axes
    from lobemap.viewer.rotation import grid_frame

    frame = anatomical_axes(sess.registry.spaces[sess.space])
    anatomy = np.column_stack([frame["A"], frame["D"], frame["R"]]).astype(float)
    grid = grid_frame(viewer.dims.order)
    base = np.empty((3, 3))
    for k in range(3):
        cos = anatomy.T @ grid[:, k]
        j = int(np.argmax(np.abs(cos)))
        base[:, k] = np.sign(cos[j]) * anatomy[:, j]
    return base


def _through_the_atlas(viewer, sess) -> None:
    """Step the slider to the plane through the primary atlas's largest
    compartment, wherever the turned view put the pivot."""
    contour = _primary_contour(sess)
    meshset = contour.meshset
    largest = int(np.argmax(np.diff(meshset.vertex_offsets)))
    world = th.mesh_to_world(contour, meshset.centroid(largest))
    axis = int(viewer.dims.order[0])
    viewer.dims.set_point(axis, float(world[axis]))
    th.settle_canvas(viewer)


def test_the_group_opens_folded_and_its_header_says_the_angles(monkeypatch):
    with launched(monkeypatch, "view", "GRABE") as (code, viewer):
        assert code == 0
        group = switcher(viewer).rotation
        assert not group.body.isVisibleTo(group)
        assert group.header.text() == "Rotation  0°, 0°, 0°"
        group.header.click()
        assert group.body.isVisibleTo(group)
        labels = ["Spin (in the screen plane)", "Tilt (top toward you)",
                  "Turn (about the vertical)"]
        for box, label in zip(group.boxes, labels, strict=True):
            assert (box.minimum(), box.maximum()) == (-180.0, 180.0)
            assert box.wrapping() and box.singleStep() == 1.0
            assert box.decimals() == 1 and box.suffix() == "°"
            assert "Positive" in box.toolTip()
            assert group.body.layout().labelForField(box).text() == label
        # Stepping past 180 wraps to -180, the same angle.
        group.boxes[0].setValue(180.0)
        group.boxes[0].stepBy(1)
        assert group.boxes[0].value() == -180.0
        group.header.click()
        assert not group.body.isVisibleTo(group)
        # Folded, the header still says the view is turned.
        assert group.header.text() == "Rotation  -180°, 0°, 0°"
        assert session(viewer).rotation == (-180.0, 0.0, 0.0)


def test_the_boxes_turn_the_3d_camera_from_home_and_a_drag_leaves_them(monkeypatch):
    with launched(monkeypatch, "view", "GRABE") as (code, viewer):
        assert code == 0
        sw, sess = switcher(viewer), session(viewer)
        th.settle_canvas(viewer)
        before = th.state(viewer)
        placed = [np.asarray(layer.affine.affine_matrix) for layer in viewer.layers]

        _set(sw, spin=30)
        _faces(viewer, sess, (30, 0, 0))
        _set(sw, tilt=-20, turn=45)
        _faces(viewer, sess, (30, -20, 45))
        assert sw.rotation.header.text() == "Rotation  30°, -20°, 45°"
        # The camera turns; no layer moves.
        assert all(np.array_equal(p, layer.affine.affine_matrix)
                   for p, layer in zip(placed, viewer.layers, strict=True))

        # A drag turns the camera freely and the boxes stay as they are.
        viewer.scene.camera.angles = (5.0, 60.0, -100.0)
        pump()
        assert sw.rotation.angles() == (30.0, -20.0, 45.0)
        # Home view, and an arrow step, put it at Home turned by the boxes.
        sw.home.click()
        pump()
        _faces(viewer, sess, (30, -20, 45))
        sw.rotation.boxes[0].stepBy(1)
        pump()
        _faces(viewer, sess, (31, -20, 45))

        sw.rotation.reset.click()
        pump()
        assert sw.rotation.angles() == (0.0, 0.0, 0.0)
        assert sess.rotation == (0.0, 0.0, 0.0)
        assert th.state(viewer) == before


def test_the_boxes_and_the_alignment_cut_the_2d_section(monkeypatch):
    from lobemap.core.model import anatomical_axes
    from lobemap.viewer.rotation import grid_frame, screen_matrix

    with launched(monkeypatch, "view", "GRABE", "--ndisplay", "2") as (code, viewer):
        assert code == 0
        sw, sess = switcher(viewer), session(viewer)
        th.settle_canvas(viewer)
        _center_on_the_atlas(viewer, sess)
        before, pixels = th.state(viewer), th.render(viewer)
        contour = _primary_contour(sess)
        grid = grid_frame(viewer.dims.order)

        # A spin turns the picture counterclockwise, on the image grid.
        _set(sw, spin=30)
        th.settle_canvas(viewer)
        assert np.allclose(_shown_frame(viewer, contour),
                           grid @ screen_matrix((30, 0, 0)).T, atol=1e-6)
        assert contour.frame is None
        assert _contour_vs_trimesh(viewer, sess) > 0

        # Tilt and turn cut an oblique section; the slider steps in depth.
        _set(sw, tilt=25, turn=-15)
        th.settle_canvas(viewer)
        angles = (30, 25, -15)
        assert contour.frame is not None
        assert np.allclose(_shown_frame(viewer, contour),
                           grid @ screen_matrix(angles).T, atol=1e-6)
        assert _contour_vs_trimesh(viewer, sess, th.to_mesh(contour)) > 0
        assert viewer.dims.axis_labels[int(viewer.dims.order[0])] == "depth"
        assert not np.array_equal(th.render(viewer), pixels)

        # Aligned, the angles turn from the anatomy nearest the grid.
        sw.align.click()
        th.settle_canvas(viewer)
        assert sess.aligned
        assert [sw.slice.itemText(i) for i in range(sw.slice.count())] == [
            "Frontal (true plane)", "Horizontal (true plane)", "Sagittal (true plane)"]
        base = _aligned_base(viewer, sess)
        assert 1.0 < np.degrees(np.arccos(np.diag(base.T @ grid).min())) < 35.0
        assert np.allclose(_shown_frame(viewer, contour),
                           base @ screen_matrix(angles).T, atol=1e-6)
        assert _contour_vs_trimesh(viewer, sess, th.to_mesh(contour)) > 0

        # At zero angles, aligned, the section is the brain's true plane
        # nearest the grid's: perpendicular to an anatomical axis.
        sw.rotation.reset.click()
        th.settle_canvas(viewer)
        _origin, normal = th.plane_in_mesh(viewer, contour)
        frame = anatomical_axes(sess.registry.spaces["GRABE"])
        cos = max(abs(normal @ np.asarray(frame[pole], float)) for pole in "ADR")
        assert cos / np.linalg.norm(normal) == pytest.approx(1.0, abs=1e-9)

        # Off again, at zero: the view as it was, to the pixel.
        sw.align.click()
        th.settle_canvas(viewer)
        assert sess.turned.at_rest
        assert th.state(viewer) == before
        assert np.array_equal(th.render(viewer), pixels)

        # 3D disables the alignment and says why; it is kept for 2D.
        sw.align.click()
        sw.three_d.click()
        pump()
        assert not sw.align.isEnabled() and sw.align.isChecked()
        assert sw.slice_note.isVisibleTo(sw) and sw.slice_note.text() == "Slice view only"
        sw.slice_view.click()
        th.settle_canvas(viewer)
        assert sw.align.isEnabled() and sess.aligned and contour.frame is not None


def test_a_switch_carries_the_turn_and_a_failed_one_keeps_everything(monkeypatch):
    from lobemap.viewer.rotation import screen_matrix

    with launched(monkeypatch, "view", "GRABE", "--ndisplay", "2") as (code, viewer):
        assert code == 0
        sw = switcher(viewer)
        th.settle_canvas(viewer)
        sw.align.click()
        _set(sw, spin=10, tilt=25, turn=-15)
        angles = (10.0, 25.0, -15.0)

        switch_to(viewer, "FAFB14")
        th.settle_canvas(viewer)
        new = session(viewer)
        assert new.space == "FAFB14" and sw.status.text() == ""
        assert new.rotation == angles and new.aligned
        assert sw.rotation.angles() == angles and sw.align.isChecked()
        contour = _primary_contour(new)
        assert contour.frame is not None
        # The new brain's anatomical base view, turned by the same angles.
        assert np.allclose(_shown_frame(viewer, contour),
                           _aligned_base(viewer, new) @ screen_matrix(angles).T, atol=1e-6)
        _through_the_atlas(viewer, new)
        assert _contour_vs_trimesh(viewer, new, th.to_mesh(contour)) > 0

        # A switch that fails, its scene built beside this one and then
        # dropped, leaves the scene, its turn and the controls.
        th.settle_canvas(viewer)
        before, pixels = th.state(viewer), th.render(viewer)

        def fails(*args, **kwargs):
            raise RuntimeError("made to fail")

        monkeypatch.setattr("lobemap.viewer.app.show_main_layer", fails)
        switch_to(viewer, "JRCFIB2018F")
        th.settle_canvas(viewer)
        assert session(viewer) is new
        assert new.rotation == angles and new.aligned
        assert sw.rotation.angles() == angles and sw.align.isChecked()
        assert sw.combo.currentData() == "FAFB14"
        assert th.state(viewer) == before
        assert np.array_equal(th.render(viewer), pixels)
