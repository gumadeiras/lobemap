"""The 2D slice: which plane it opens on, which axis it steps, the mirror.

Checked against what is drawn: the contour shapes on the plane, the image
array napari is displaying, the triad's own geometry, the camera.
"""

from __future__ import annotations

import numpy as np
import pytest
from viewer_harness import (
    SPACES,
    assert_renders_loops,
    contour_loops,
    launched,
    pump,
    session,
    switch_to,
    switcher,
)

pytestmark = pytest.mark.requires_data
pytest.importorskip("napari")


def _primary(viewer):
    sess = session(viewer)
    return sess.contours[sess.registry.primary_atlas(sess.space).id]


def _on_plane(viewer, overlay) -> None:
    """Every contour is drawn, and lies on the plane the slider is at."""
    axis = int(viewer.dims.order[0])
    point = float(viewer.dims.point[axis])
    assert overlay.layer.visible
    loops = contour_loops(overlay)
    assert loops, "no contour on this plane"
    for _owner, path in loops:
        assert np.allclose(path[:, axis], point), (axis, point)
    assert_renders_loops(overlay)


@pytest.mark.parametrize("space", SPACES)
def test_2d_opens_on_a_plane_the_primary_atlas_crosses(monkeypatch, space):
    with launched(monkeypatch, "view", space, "--ndisplay", "2") as (code, viewer):
        assert code == 0
        _on_plane(viewer, _primary(viewer))


@pytest.mark.parametrize("space", SPACES)
def test_entering_2d_moves_off_an_empty_plane(monkeypatch, space):
    with launched(monkeypatch, "view", space) as (code, viewer):
        viewer.dims.ndisplay = 2
        pump()
        _on_plane(viewer, _primary(viewer))


@pytest.mark.parametrize("axis", [0, 1, 2])
@pytest.mark.parametrize("space", ["FAFB14", "GRABE"])
def test_a_populated_plane_the_user_chose_is_kept(monkeypatch, space, axis):
    """On every slice axis, through 3D and back.

    napari puts the slider of the first axis in the order at the camera's
    depth on the way back to 2D; in 3D's order that is x, so x lost it.
    """
    with launched(monkeypatch, "view", space, "--ndisplay", "2") as (code, viewer):
        menu = switcher(viewer).slice
        menu.setCurrentIndex(menu.findData(axis))
        pump()
        assert int(viewer.dims.order[0]) == axis
        overlay = _primary(viewer)
        spans = [overlay.meshset.compartment(i)[0][:, axis] for i in range(5)]
        chosen = float(np.median([s.mean() for s in spans]))
        viewer.dims.set_point(axis, chosen)
        pump()
        kept = float(viewer.dims.point[axis])
        _on_plane(viewer, overlay)
        viewer.dims.ndisplay = 3
        pump()
        viewer.dims.ndisplay = 2
        pump()
        assert int(viewer.dims.order[0]) == axis
        assert float(viewer.dims.point[axis]) == kept
        _on_plane(viewer, overlay)


def _nearest_plane(space, axis):
    """The plane a slider on `axis` steps through, and its angle to the anatomy:
    stepping anterior-posterior cuts frontal sections, and so on."""
    from lobemap.core.model import anatomical_axes

    frame = anatomical_axes(space)
    names = {"A": "Frontal", "D": "Horizontal", "R": "Sagittal"}
    cosines = {names[p]: abs(float(np.asarray(frame[p])[axis])) for p in names}
    name = max(cosines, key=cosines.get)
    return name, float(np.degrees(np.arccos(cosines[name])))


@pytest.mark.parametrize("space", SPACES)
def test_the_sections_menu_names_each_axis_by_its_nearest_plane(monkeypatch, space):
    with launched(monkeypatch, "view", space, "--ndisplay", "2") as (code, viewer):
        menu = switcher(viewer).slice
        registry = session(viewer).registry
        seen = []
        for i in range(menu.count()):
            axis = int(menu.itemData(i))
            name, degrees = _nearest_plane(registry.spaces[space], axis)
            axis_name = {"Frontal": "anterior–posterior", "Horizontal": "dorsal–ventral",
                         "Sagittal": "medial–lateral"}[name]
            assert menu.itemText(i) == f"{name} ({degrees:.1f}° off {axis_name})"
            seen.append(name)
        assert seen == ["Frontal", "Horizontal", "Sagittal"]
        assert menu.toolTip().startswith("Which sections the slider steps through,")


def _assert_image_slices(layer, axis) -> None:
    """napari slices the image across the other two axes at this plane.

    For a single-scale stack the array it displays is checked too. A
    multiscale stain renders only the tile the canvas last drew, and a
    hidden canvas never draws, so for those the slice request is the check.
    """
    request = layer._slice_input
    assert axis in list(request.not_displayed), (axis, request)
    if not layer.multiscale:
        shown = np.asarray(layer._slice.image.view).shape
        assert shown == tuple(layer.data.shape[d] for d in request.displayed)


#: The reference image each space slices; the EM stains are optional data.
IMAGE_ASSET = {"FAFB14": "fafb_stain", "JRCFIB2018F": "hemibrain_stain",
               "JRCFIB2022M": "malecns_stain", "GRABE": "grabe2015_stack"}


@pytest.mark.parametrize("space", [
    pytest.param(s, marks=pytest.mark.requires_data(IMAGE_ASSET[s])) for s in SPACES])
def test_a_slice_axis_moves_image_and_contours_together(monkeypatch, space):
    with launched(monkeypatch, "view", space, "--ndisplay", "2") as (code, viewer):
        menu = switcher(viewer).slice
        image = next(layer for layer in viewer.layers
                     if layer.metadata.get("lobemap", {}).get("kind") == "image")
        for i in range(menu.count()):
            menu.setCurrentIndex(i)
            pump()
            axis = int(menu.itemData(i))
            assert viewer.dims.order[0] == axis
            # The image displays the plane across the other two axes...
            assert list(image._slice_input.displayed) == list(viewer.dims.displayed)
            _assert_image_slices(image, axis)
            # ... and the contours cut that same plane, and cut something.
            _on_plane(viewer, _primary(viewer))


def test_the_slice_axis_survives_3d_and_follows_its_anatomy_to_another_space(
    monkeypatch,
):
    with launched(monkeypatch, "view", "GRABE", "--ndisplay", "2") as (code, viewer):
        menu = switcher(viewer).slice
        menu.setCurrentIndex(menu.findText("Frontal", flags=_starts()))
        pump()
        assert viewer.dims.order[0] == 1               # A-P is y in GRABE
        viewer.dims.ndisplay = 3
        assert not menu.isEnabled(), "the slice axis does nothing in 3D"
        viewer.dims.ndisplay = 2
        assert menu.isEnabled()
        assert viewer.dims.order[0] == 1
        switch_to(viewer, "FAFB14")
        assert menu.currentText().startswith("Frontal")
        assert viewer.dims.order[0] == 2               # and z in FAFB14
        _on_plane(viewer, _primary(viewer))


def _starts():
    from qtpy.QtCore import Qt

    return Qt.MatchFlag.MatchStartsWith


def _x_arrow_tip(viewer) -> np.ndarray:
    """Where napari's x arrow points, in the triad's own vispy frame."""
    from lobemap.viewer.axes import _vispy_axes_overlay

    node = _vispy_axes_overlay(viewer).node.axes
    k = list(viewer.dims.displayed)[::-1].index(0)
    tip = np.zeros(4)
    tip[k], tip[3] = 1.0, 1.0
    return np.asarray(node.transform.map(tip))[:3], k


def test_the_mirror_reflects_the_x_arrow_in_2d(monkeypatch):
    with launched(monkeypatch, "view", "GRABE", "--ndisplay", "2") as (code, viewer):
        mirror = switcher(viewer).mirror
        mirror.setChecked(True)
        pump()
        tip, k = _x_arrow_tip(viewer)
        assert tip[k] == pytest.approx(-1.0), tip
        viewer.dims.ndisplay = 3
        tip, k = _x_arrow_tip(viewer)
        assert tip[k] == pytest.approx(-1.0), tip
        viewer.dims.ndisplay = 2
        mirror.setChecked(False)
        pump()
        tip, k = _x_arrow_tip(viewer)
        assert tip[k] == pytest.approx(1.0), tip


@pytest.mark.parametrize("space", SPACES)
def test_a_scene_opened_in_2d_is_oriented_on_first_entering_3d(monkeypatch, space):
    from lobemap.core.model import anatomical_axes

    with launched(monkeypatch, "view", space, "--ndisplay", "2") as (code, viewer):
        viewer.dims.ndisplay = 3
        frame = anatomical_axes(session(viewer).registry.spaces[space])
        view = np.asarray(viewer.scene.camera.view_direction)
        up = np.asarray(viewer.scene.camera.up_direction)
        assert float(np.dot(view, frame["A"])) < -0.99, view
        assert float(np.dot(up, frame["D"])) > 0.99, up


def test_home_faces_the_mirrored_anatomy(monkeypatch):
    from lobemap.core.model import anatomical_axes

    with launched(monkeypatch, "view", "GRABE") as (code, viewer):
        switcher(viewer).mirror.setChecked(True)
        pump()
        viewer.scene.camera.angles = (17, 42, -63)
        switcher(viewer).home.click()
        frame = anatomical_axes(session(viewer).registry.spaces["GRABE"])
        reflect = np.array([-1.0, 1.0, 1.0])
        view = np.asarray(viewer.scene.camera.view_direction)
        up = np.asarray(viewer.scene.camera.up_direction)
        assert float(np.dot(view, frame["A"] * reflect)) < -0.999, view
        assert float(np.dot(up, frame["D"] * reflect)) > 0.999, up


def test_mirrored_contours_follow_a_slice_along_the_mirror_axis(monkeypatch):
    with launched(monkeypatch, "view", "GRABE", "--ndisplay", "2") as (code, viewer):
        menu = switcher(viewer).slice
        menu.setCurrentIndex(menu.findText("Sagittal", flags=_starts()))
        switcher(viewer).mirror.setChecked(True)
        pump()
        overlay = _primary(viewer)
        plane = float(overlay.layer.world_to_data(viewer.dims.point)[0])
        loops = contour_loops(overlay)
        assert loops
        for _owner, path in loops:
            assert np.allclose(path[:, 0], plane)
        assert_renders_loops(overlay)


def test_napari_roll_shortcut_is_a_slice_axis_choice(monkeypatch):
    """napari's roll-dims button, hidden now but still a shortcut, changed the
    slice axis behind the menu: the menu kept its old name and the new plane
    showed no contour. In 3D a roll broke the identity order that keeps the
    image and meshes aligned. The shortcut runs `viewer.dims.roll()`."""
    with launched(monkeypatch, "view", "GRABE", "--ndisplay", "2") as (code, viewer):
        menu = switcher(viewer).slice
        sess = session(viewer)
        overlay = _primary(viewer)
        before = menu.currentText()
        viewer.dims.roll()
        pump()
        axis = viewer.dims.order[0]
        assert sess.slice_axis == axis
        assert menu.currentData() == axis and menu.currentText() != before
        _on_plane(viewer, overlay)

        viewer.dims.ndisplay = 3
        pump()
        viewer.dims.roll()
        pump()
        assert tuple(viewer.dims.order) == (0, 1, 2)
