"""The 3D camera after Reset rotation, a trip through Slice view, the mirror,
the flip and napari's camera sync, read from what is drawn.

Each test drives the View dock and napari's own controls in a brain opened as
`lobemap view` opens it, and reads the picture: vispy's mapping of the world
to the canvas (`turned_harness.screen_axes`), the light the surfaces are
shaded with, and the rendered pixels.
"""

from __future__ import annotations

import numpy as np
import pytest
import turned_harness as th
from viewer_harness import SPACES, launched, pump, session, switcher

pytestmark = pytest.mark.requires_data
napari = pytest.importorskip("napari")

#: Angles about the screen's axes: (spin, tilt, turn).
ANGLES = (15.0, 25.0, 35.0)


def _set(sw, angles) -> None:
    for i, angle in enumerate(("spin", "tilt", "turn")):
        sw.rotation.box[angle].setValue(angles[i])
    pump()


def _drag(viewer) -> None:
    """Turn the camera as a drag does, leaving the angle boxes alone."""
    camera = viewer.scene.camera
    camera.angles = tuple(a + d for a, d in zip(camera.angles, (12.0, -9.0, 21.0),
                                                strict=True))
    pump()


def _picture(viewer) -> np.ndarray:
    th.settle_canvas(viewer)
    return th.render(viewer).astype(int)


def _light_on_screen(viewer, surface) -> np.ndarray:
    """The light a surface is shaded with, on the screen's right, up and
    toward the viewer, as drawn."""
    from lobemap.viewer.napari_private import layer_visual

    th.settle_canvas(viewer)
    light = np.asarray(layer_visual(viewer, surface.layer).node.shading_filter.light_dir,
                       float)[::-1]
    return th.screen_axes(viewer) @ (light / np.linalg.norm(light))


@pytest.mark.parametrize("space", ["GRABE", "JRCFIB2018F"])
def test_reset_rotation_faces_the_front_after_a_drag(monkeypatch, space):
    """Reset rotation did nothing after a 3D drag, the angles being 0 already."""
    with launched(monkeypatch, "view", space) as (code, viewer):
        sw = switcher(viewer)
        th.settle_canvas(viewer)
        front = th.screen_axes(viewer)
        _drag(viewer)
        th.settle_canvas(viewer)
        assert not np.allclose(th.screen_axes(viewer), front, atol=1e-3)
        sw.rotation.reset.click()
        pump()
        th.settle_canvas(viewer)
        assert np.allclose(th.screen_axes(viewer), front, atol=1e-9)
        # Turned, then dragged: Reset faces the front again too.
        _set(sw, ANGLES)
        _drag(viewer)
        sw.rotation.reset.click()
        pump()
        th.settle_canvas(viewer)
        assert np.allclose(th.screen_axes(viewer), front, atol=1e-9)
        # In Slice view, it leaves 3D's camera to the next entry.
        viewer.dims.ndisplay = 2
        pump()
        sw.rotation.reset.click()
        viewer.dims.ndisplay = 3
        pump()
        th.settle_canvas(viewer)
        assert np.allclose(th.screen_axes(viewer), front, atol=1e-9)


def _trip(monkeypatch, space, steps) -> dict:
    """Open `space` in 3D, run `steps` on the View dock, and read the picture."""
    with launched(monkeypatch, "view", space) as (code, viewer):
        sw = switcher(viewer)
        pump()
        for step in steps:
            step(sw)
            pump(50)
        camera = viewer.scene.camera
        return {"zoom": float(camera.zoom), "center": np.asarray(camera.center, float),
                "screen": th.screen_axes(viewer), "picture": _picture(viewer),
                "boxes": sw.rotation.angles()}


TILT = lambda sw: sw.rotation.box["tilt"].setValue(25.0)
SLICE = lambda sw: sw.slice_view.click()
THREE_D = lambda sw: sw.three_d.click()
RESET = lambda sw: sw.rotation.reset.click()


@pytest.mark.parametrize("space", ["GRABE", "JRCFIB2018F"])
def test_reset_after_a_trip_gives_the_picture_the_trip_gives_unturned(monkeypatch, space):
    """Turned, to Slice view and back, then Reset rotation: the zoom was
    2.6909 against 2.8782 for the same trip unturned in GRABE, and a few
    thousand pixels were drawn otherwise. Orders that end in 3D, and one that
    resets in Slice view."""
    unturned = _trip(monkeypatch, space, [SLICE, THREE_D])
    for steps in ([TILT, SLICE, THREE_D, RESET], [TILT, SLICE, RESET, THREE_D]):
        turned = _trip(monkeypatch, space, steps)
        assert turned["boxes"] == (0.0, 0.0, 0.0)
        assert turned["zoom"] == unturned["zoom"], steps
        assert np.array_equal(turned["center"], unturned["center"]), steps
        assert np.allclose(turned["screen"], unturned["screen"], atol=1e-12), steps
        differ = np.abs(turned["picture"] - unturned["picture"]).max(axis=-1) > 0
        assert not differ.any(), (steps, int(differ.sum()))


def test_the_light_is_the_cameras_and_the_flips_alone(monkeypatch):
    """With the flip on, any move of the camera lit the surfaces from the top
    left, and the upright picture stayed lit so until its next move: 429,051
    pixels differed after flip on, Fit to window, flip off in GRABE."""
    with launched(monkeypatch, "view", "GRABE") as (code, viewer):
        sw, sess = switcher(viewer), session(viewer)
        surface = sess.surfaces[sess.registry.primary_atlas("GRABE").id]
        upright = np.ones(3) / np.sqrt(3)
        flipped = np.array([1.0, -1.0, 1.0]) / np.sqrt(3)
        # Fitted to the canvas as it is laid out, as every sequence ends.
        th.settle_canvas(viewer)
        sw.home.click()
        pump()
        base = _picture(viewer)
        assert np.allclose(_light_on_screen(viewer, surface), upright, atol=1e-6)
        flip_on = lambda: sw.flip.setChecked(True)
        flip_off = lambda: sw.flip.setChecked(False)
        fit = sw.home.click
        for steps in ([flip_on, fit, flip_off],
                      [flip_on, lambda: _drag(viewer), fit, flip_off],
                      [flip_on, lambda: _set(sw, ANGLES), sw.rotation.reset.click, flip_off],
                      [lambda: _set(sw, ANGLES), flip_on, sw.rotation.reset.click, flip_off]):
            for step in steps:
                step()
                pump()
                want = flipped if sw.flip.isChecked() else upright
                assert np.allclose(_light_on_screen(viewer, surface), want, atol=1e-6)
            differ = np.abs(_picture(viewer) - base).max(axis=-1) > 0
            assert not differ.any(), int(differ.sum())


def _specimen_map(viewer, sess) -> np.ndarray:
    """The 2 x 3 map of a micrometer's step along each axis of the specimen
    to the canvas, at the primary atlas, as drawn: through the outline
    layer's transform, which carries the mirror -- it is there in 3D too,
    hidden -- and vispy's to the canvas. Every brain has it, stain or not."""
    from viewer_harness import canvas_position

    name = sess.registry.primary_atlas(sess.space).id
    layer = sess.contours[name].layer
    middle = np.asarray(sess.surfaces[name].meshset.centroid(0), float)

    def at(point):
        return np.asarray(canvas_position(viewer, layer.data_to_world(point)), float)

    origin = at(middle)
    return np.column_stack([at(middle + step) - origin for step in np.eye(3)])


def _degrees(a, b) -> float:
    """The largest angle between matching columns of two maps."""
    worst = 0.0
    for u, v in zip(a.T, b.T, strict=True):
        cos = u @ v / np.linalg.norm(u) / np.linalg.norm(v)
        worst = max(worst, float(np.degrees(np.arccos(np.clip(cos, -1, 1)))))
    return worst


@pytest.mark.parametrize("space", SPACES)
def test_mirror_and_flip_in_3d_are_a_half_turn(monkeypatch, space):
    """Toggled in 3D, the mirror left the camera where it was, which faced
    11 degrees off the mirrored Home in GRABE: the mirror and the flip were
    no 180-degree turn until Fit to window. Now the camera faces Home turned
    by the angles, as a new angle puts it."""
    with launched(monkeypatch, "view", space) as (code, viewer):
        sw, sess = switcher(viewer), session(viewer)
        th.settle_canvas(viewer)
        sw.rotation.box["spin"].setValue(180.0)
        pump()
        th.settle_canvas(viewer)
        half_turn = _specimen_map(viewer, sess)
        sw.rotation.reset.click()
        pump()
        for first, second in ((sw.mirror, sw.flip), (sw.flip, sw.mirror)):
            first.setChecked(True)
            pump()
            second.setChecked(True)
            pump()
            th.settle_canvas(viewer)
            both = _specimen_map(viewer, sess)
            assert _degrees(both, half_turn) < 0.01, (space, _degrees(both, half_turn))
            # The same foreshortening of each axis, whatever the zoom.
            assert np.allclose(np.linalg.norm(both, axis=0) / np.linalg.norm(both),
                               np.linalg.norm(half_turn, axis=0) / np.linalg.norm(half_turn),
                               rtol=1e-4)
            sw.home.click()
            pump()
            th.settle_canvas(viewer)
            assert _degrees(_specimen_map(viewer, sess), both) < 0.01, "Home moved it"
            first.setChecked(False)
            second.setChecked(False)
            pump()
        # Turned, the mirror faces Home turned by the angles.
        _set(sw, ANGLES)
        sw.mirror.setChecked(True)
        pump()
        th.settle_canvas(viewer)
        toggled = _specimen_map(viewer, sess)
        sw.home.click()
        pump()
        th.settle_canvas(viewer)
        assert _degrees(_specimen_map(viewer, sess), toggled) < 0.01
