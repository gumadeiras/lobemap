"""The picture upside down in the real spaces, as `lobemap view` opens them.

The rules are proven on synthetic data in `test_flip.py`; here each space
is opened with its own meshes and images, in 3D and in 2D, upright and
turned, with and without the mirror, and checked on what is drawn and
where the camera looks: the picture is the upright one upside down, lit
from outside; the camera, the sliders and every layer stay put; the triads
point where they say; hover names what it named upright at the same
specimen point; the contours are exact sections; Fit to window and trips
keep the flip; off gives back the view exactly; and with the mirror, a
front view is turned 180 degrees.

And the regression route C's prototype had: a brain opened fresh in 3D,
flipped, faced the wrong way after two trips through 2D, and with its
second flip the back of the brain.
"""

from __future__ import annotations

import numpy as np
import pytest
import turned_harness as th
from viewer_harness import SPACES, assert_renders_loops, hover, launched, pump, switcher

napari = pytest.importorskip("napari")

pytestmark = pytest.mark.requires_data

#: Screen right, up and toward the viewer, flipped.
FLIP = np.array([[1.0], [-1.0], [1.0]])


def _on_surface(sess, point) -> np.ndarray:
    """Where the surfaces draw a mesh point: reflected with the scene."""
    from lobemap.viewer.view import MIRROR_AXIS

    out = np.array(point, float)
    if sess.mirrored:
        out[MIRROR_AXIS] = 2.0 * sess.mirror_center - out[MIRROR_AXIS]
    return out


def _levels_read(sess, timeout_s: float = 60.0) -> None:
    """Wait for each image's 3D level read in the background
    (`images.FineLevel`), which swaps the level of a layer when it arrives."""
    import time

    from lobemap.viewer import images

    end = time.perf_counter() + timeout_s
    while any(getattr(images._FINE.get(layer), "array", 0) is None
              for layer in sess.images):
        assert time.perf_counter() < end, "a 3D level was never read"
        pump(30)


def _half_turned(plain, turned) -> None:
    """`turned` is `plain` turned 180 degrees about one point of the screen."""
    plain, turned = np.asarray(plain, float), np.asarray(turned, float)
    pivot = (plain + turned).mean(axis=0) / 2.0
    assert np.abs(turned - (2.0 * pivot - plain)).max() < 1e-3
    assert np.ptp(plain, axis=0).min() > 20, "too few pixels to tell"


@pytest.mark.parametrize("space", SPACES)
def test_3d_upside_down_in_every_space(registry, space):
    from viewer_harness import canvas_position

    viewer, sess = th.open_space(registry, space, 3)
    try:
        _levels_read(sess)
        for image in sess.images:
            image.visible = False
        primary = sess.surfaces[registry.primary_atlas(space).id]
        shown = sorted(primary.selection)
        meshes = np.asarray(primary.meshset.vertices, float)[::997]
        plain = None
        for mirrored in (False, True):
            sess.set_mirror(mirrored)
            for angles in ((0.0, 0.0, 0.0), (25.0, 35.0, -50.0)):
                sess.set_rotation(*angles)
                sess.home()
                th.settle_canvas(viewer)
                axes, placed, upright = th.screen_axes(viewer), th.placed(viewer), th.picture(
                    viewer)
                points = [_on_surface(sess, primary.meshset.centroid(i))
                          for i in shown[:: max(1, len(shown) // 8)]]
                said = [hover(viewer, p) for p in points]
                assert sum(bool(s) for s in said) >= len(points) // 2, said
                if not mirrored and not any(angles):
                    plain = [canvas_position(viewer, _on_surface(sess, m)) for m in meshes]

                sess.set_flip(True)
                th.settle_canvas(viewer)
                assert np.allclose(th.screen_axes(viewer), FLIP * axes, atol=1e-6), angles
                assert th.placed(viewer) == placed, angles
                flipped = th.picture(viewer)
                th.assert_upside_down(flipped, upright, at_most=0.03)
                assert th.brightness(flipped) == pytest.approx(th.brightness(upright),
                                                              rel=0.05)
                assert th.assert_triads_point_where_they_say(
                    viewer, registry.spaces[space]) >= 4
                assert [hover(viewer, p) for p in points] == said
                if mirrored and not any(angles):
                    _half_turned(plain, [canvas_position(viewer, _on_surface(sess, m))
                                         for m in meshes])
                sess.set_flip(False)
                th.settle_canvas(viewer)
                assert th.placed(viewer) == placed, angles
                assert np.array_equal(th.picture(viewer), upright), angles

                # Fit to window, and trips through 2D, keep it.
                sess.set_flip(True)
                viewer.scene.camera.angles = (12.0, -33.0, 71.0)
                sess.home()
                th.settle_canvas(viewer)
                assert np.allclose(th.screen_axes(viewer), FLIP * axes, atol=1e-6), angles
                for _ in range(2):
                    viewer.dims.ndisplay = 2
                    th.settle_canvas(viewer)
                    viewer.dims.ndisplay = 3
                    th.settle_canvas(viewer)
                    assert np.allclose(th.screen_axes(viewer), FLIP * axes,
                                       atol=1e-6), angles
                sess.set_flip(False)
            sess.set_rotation(0, 0, 0)
    finally:
        viewer.close()
        pump()


@pytest.mark.parametrize("space", SPACES)
def test_a_slice_upside_down_in_every_space(registry, space):
    from viewer_harness import canvas_position

    viewer, sess = th.open_space(registry, space, 2)
    try:
        contour = sess.contours[registry.primary_atlas(space).id]
        plain = None
        for mirrored in (False, True):
            sess.set_mirror(mirrored)
            th.center_on_the_atlas(viewer, sess)
            for angles in ((0.0, 0.0, 0.0), (20.0, 37.0, 15.0)):
                sess.set_rotation(*angles)
                th.settle_canvas(viewer)
                before, upright = th.state(viewer), th.picture(viewer)
                paths = list(contour.paths)
                points = [contour.layer.data_to_world(np.asarray(path, float).mean(axis=0))
                          for path in paths[:: max(1, len(paths) // 8)]]
                said = [hover(viewer, p) for p in points]
                # A loop's middle can fall outside it, in a concave glomerulus.
                assert sum(bool(s) for s in said) >= len(points) // 2, said
                on_plane = [contour.layer.data_to_world(m)
                            for path in paths for m in np.asarray(path, float)[::40]]
                if not mirrored and not any(angles):
                    plain = [canvas_position(viewer, w) for w in on_plane]
                    kept = [contour.layer.world_to_data(w) for w in on_plane]

                sess.set_flip(True)
                th.settle_canvas(viewer)
                assert th.state(viewer) == before, angles
                th.assert_upside_down(th.picture(viewer), upright)
                to_mesh = th.to_mesh(contour)
                assert th.contour_vs_trimesh(viewer, sess, to_mesh) > 0
                assert_renders_loops(contour)
                checked = th.assert_triads_point_where_they_say(viewer, registry.spaces[space])
                # The poles' arrows on the section; napari's x/y arrows step aside.
                assert checked >= 2, angles
                assert [hover(viewer, p) for p in points] == said
                if mirrored and not any(angles):
                    # The same specimen points: mirrored now, upside down.
                    _half_turned(plain, [canvas_position(viewer, contour.layer.data_to_world(
                        np.asarray(m, float))) for m in kept])
                sess.set_flip(False)
                th.settle_canvas(viewer)
                assert th.state(viewer) == before, angles
                assert np.array_equal(th.picture(viewer), upright), angles
            sess.set_rotation(0, 0, 0)
    finally:
        viewer.close()
        pump()


@pytest.mark.parametrize("angles", [(0.0, 0.0, 0.0), (10.0, 84.0, 0.0)])
@pytest.mark.parametrize("mirror", [False, True])
def test_a_brain_opened_in_3d_and_flipped_keeps_its_view_through_trips(monkeypatch, mirror,
                                                                        angles):
    """Route C's repro, through the View dock: GRABE opened fresh in 3D, at
    0 degrees and at the 84-degree elevation where its camera lost the view,
    flipped -- with the mirror, a front view turned 180 degrees, which with
    route C faced the back of the brain -- then four trips through 2D. Each
    time 3D comes back, the camera looks where it looked before the trips,
    the screen's up turned over: at 0 degrees unmirrored, down the anterior
    axis with dorsal at the bottom of the screen."""
    from lobemap.core.model import anatomical_axes

    with launched(monkeypatch, "view", "GRABE") as (code, viewer):
        assert code == 0
        sw = switcher(viewer)
        th.settle_canvas(viewer)
        for name, value in zip(("spin", "tilt", "turn"), angles, strict=True):
            sw.rotation.box[name].setValue(value)
        if mirror:
            sw.mirror.click()
        pump(100)
        axes = th.screen_axes(viewer)
        sw.flip.click()
        pump(100)
        th.settle_canvas(viewer)
        assert sw.session.flipped
        assert np.allclose(th.screen_axes(viewer), FLIP * axes, atol=1e-6)
        if not mirror and not any(angles):
            frame = anatomical_axes(sw.session.registry.spaces["GRABE"])
            right, up, toward = th.screen_axes(viewer)
            assert toward @ np.asarray(frame["A"]) > 0.99
            assert up @ np.asarray(frame["D"]) < -0.99
        for trip in range(4):
            sw.slice_view.click()
            pump(100)
            th.settle_canvas(viewer)
            sw.three_d.click()
            pump(100)
            th.settle_canvas(viewer)
            assert np.allclose(th.screen_axes(viewer), FLIP * axes, atol=1e-6), trip
