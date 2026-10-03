"""The View dock's zoom and perspective, and the view under perspective.

The zoom box is the camera's zoom, in screen pixels per micrometer, both
ways, in 2D and 3D, and the dock holds still while the mouse zooms. The
perspective box is the camera's field of view, 3D only. Under perspective,
hover names the compartment drawn under the cursor -- read from the picture
itself, each compartment drawn in a color of its own -- and the triads, Fit
to window, the rotation and the flip stay right, in every brain.
"""

from __future__ import annotations

import numpy as np
import pytest
import turned_harness as th
from chrome_harness import assert_no_hidden_mirror, baseline, layout
from viewer_harness import SPACES, canvas_position, launched, pump, session, switcher

pytestmark = pytest.mark.requires_data
napari = pytest.importorskip("napari")

#: Screen right, up and toward the viewer, upside down.
FLIP = np.array([[1.0], [-1.0], [1.0]])


def _shown(monkeypatch, space):
    """`lobemap view` on `space`, laid out at 1440 x 900, as a context."""
    from qtpy.QtCore import Qt

    context = launched(monkeypatch, "view", space)
    code, viewer = context.__enter__()
    assert code == 0
    window = viewer.window._qt_window
    window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    window.resize(1440, 900)
    window.show()
    pump(300)
    return context, viewer


def _wheel(viewer, clicks: int) -> None:
    """Turn the mouse wheel over the middle of the canvas, through Qt."""
    from qtpy.QtCore import QPoint, QPointF, Qt
    from qtpy.QtGui import QWheelEvent
    from qtpy.QtWidgets import QApplication

    native = viewer.window._qt_viewer.canvas.native
    middle = QPointF(native.width() / 2, native.height() / 2)
    glob = QPointF(native.mapToGlobal(QPoint(int(middle.x()), int(middle.y()))))
    for _ in range(abs(clicks)):
        QApplication.sendEvent(native, QWheelEvent(
            middle, glob, QPoint(0, 0), QPoint(0, 120 if clicks > 0 else -120),
            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.NoScrollPhase, False))
        pump()


def test_the_zoom_box_is_the_cameras_zoom_in_pixels_per_micrometer(monkeypatch):
    context, viewer = _shown(monkeypatch, "FAFB14")
    try:
        sw = switcher(viewer)
        box, camera = sw.camera.zoom, viewer.scene.camera
        assert box.suffix() == " pixels per µm"
        for ndisplay in (3, 2):
            viewer.dims.ndisplay = ndisplay
            pump(200)
            assert box.value() == pytest.approx(camera.zoom, abs=5e-4)
            # The box moves the camera.
            box.setValue(2.0)
            pump()
            assert camera.zoom == pytest.approx(2.0)
            # In 2D, 100 micrometers along the screen are 200 pixels.
            if ndisplay == 2:
                a = np.asarray(viewer.dims.point, float)
                b = a.copy()
                b[int(viewer.dims.displayed[1])] += 100.0
                gap = np.subtract(canvas_position(viewer, b), canvas_position(viewer, a))
                assert np.linalg.norm(gap) == pytest.approx(200.0, rel=1e-6)
            # The mouse moves both, and nothing in the docks moves with it.
            before = layout(viewer)
            for clicks in (3, -5, 2):
                zoom = camera.zoom
                _wheel(viewer, clicks)
                assert (camera.zoom > zoom) is (clicks > 0)
                assert box.value() == pytest.approx(camera.zoom, abs=5e-4)
                assert layout(viewer) == before
            # Fit to window shows the fitted zoom.
            sw.home.click()
            pump()
            assert box.value() == pytest.approx(camera.zoom, abs=5e-4)
            assert layout(viewer) == before
        # With napari's cameras unsynced, each mode has a zoom of its own:
        # the box shows the one on screen.
        camera.synced = False
        for ndisplay, zoom in ((2, 3.0), (3, 0.5), (2, None), (3, None)):
            viewer.dims.ndisplay = ndisplay
            pump()
            if zoom is not None:
                box.setValue(zoom)
                pump()
            assert box.value() == pytest.approx(camera.zoom, abs=5e-4), ndisplay
        camera.synced = True
    finally:
        context.__exit__(None, None, None)


def test_the_perspective_box_is_the_cameras_and_3d_only(monkeypatch):
    from lobemap.viewer.camera_rows import FLAT, THREE_D_ONLY

    context, viewer = _shown(monkeypatch, "GRABE")
    try:
        sw = switcher(viewer)
        box, camera = sw.camera.perspective, viewer.scene.camera
        assert box.value() == 0 and box.text() == FLAT and camera.perspective == 0
        assert (box.minimum(), box.maximum()) == (0, 90)
        box.setValue(45)
        pump()
        assert camera.perspective == 45
        camera.perspective = 70
        pump()
        assert box.value() == 70
        viewer.dims.ndisplay = 2
        pump()
        assert not box.isEnabled()
        assert sw.camera.note.isVisible() and sw.camera.note.text() == THREE_D_ONLY
        assert "3D only" in box.toolTip()
        sw.three_d.click()
        pump()
        assert box.isEnabled() and not sw.camera.note.isVisible()
        assert camera.perspective == 70 and box.value() == 70
        # Another brain is shown with the same perspective, as with the angles.
        combo = sw.combo
        combo.setCurrentIndex(combo.findData("FAFB14"))
        pump(300)
        assert session(viewer).space == "FAFB14"
        assert camera.perspective == 70 and box.value() == 70
    finally:
        context.__exit__(None, None, None)


# -- the view under perspective -----------------------------------------------


def _ids(viewer, surface) -> np.ndarray:
    """Which compartment of `surface` each pixel of the canvas draws, or -1:
    the picture rendered with each compartment in a flat color of its own."""
    from lobemap.viewer.layers import step_colormap

    layer = surface.layer
    n = surface.meshset.n_compartments
    k = np.arange(n) + 1
    colors = np.c_[(k % 16) * 16, (k // 16 % 16) * 16, (k // 256 % 16) * 16,
                   np.full(n, 255)] / 255.0
    kept = (layer.colormap, layer.shading, layer.blending, layer.opacity)
    layer.colormap = step_colormap(colors, name="compartment ids")
    layer.shading, layer.blending, layer.opacity = "none", "opaque", 1.0
    try:
        pixels = np.rint(th.picture(viewer).astype(int) / 16).astype(int)
    finally:
        layer.colormap, layer.shading, layer.blending, layer.opacity = kept
    return pixels[..., 0] + 16 * pixels[..., 1] + 256 * pixels[..., 2] - 1


def _hover_pixel(viewer, x: float, y: float) -> str:
    from vispy.app.canvas import MouseEvent

    viewer.status = ""
    viewer.window._qt_viewer.canvas._on_mouse_move(
        MouseEvent(type="mouse_move", pos=(x, y), modifiers=(), buttons=[]))
    pump()
    return str(viewer.status)


@pytest.mark.parametrize("space", SPACES)
def test_hover_and_the_triads_are_right_under_perspective(registry, space):
    """Over a grid of pixels, hover names the compartment drawn there --
    fitted, and zoomed in until the eye is among the glomeruli -- at 0, 45
    and 90 degrees. Zoomed in under perspective, hover named compartments
    behind the eye, about half the time."""
    viewer, sess = th.open_space(registry, space, 3)
    try:
        surface = sess.surfaces[registry.primary_atlas(space).id]
        tab = sess.panel.tabs[registry.primary_atlas(space).id]
        for image in sess.images:
            image.visible = False
        camera = viewer.scene.camera
        width, height = viewer.window._qt_viewer.canvas._scene_canvas.size
        for perspective in (0.0, 45.0, 90.0):
            for zoom in (1.0, 4.0):
                viewer.reset_view()
                camera.perspective = perspective
                camera.zoom = camera.zoom * zoom
                th.settle_canvas(viewer)
                if zoom == 1.0:
                    th.assert_triads_point_where_they_say(viewer, registry.spaces[space])
                ids = _ids(viewer, surface)
                scale = ids.shape[1] / width
                agree, asked = 0, 0
                for x in np.linspace(0.1 * width, 0.9 * width, 9):
                    for y in np.linspace(0.1 * height, 0.9 * height, 7):
                        r, c = int(y * scale), int(x * scale)
                        patch = ids[r - 3:r + 4, c - 3:c + 4]
                        if np.unique(patch).size != 1:
                            continue            # on an edge between two
                        drawn = int(patch[0, 0])
                        want = tab.describe(drawn) if drawn >= 0 else ""
                        asked += 1
                        agree += _hover_pixel(viewer, x, y) == want
                assert asked >= 30, (perspective, zoom, asked)
                # A grazing ray can still meet an edge a pixel misses.
                assert agree >= 0.95 * asked, (space, perspective, zoom, agree, asked)
    finally:
        viewer.close()
        pump()


def test_home_rotation_and_the_flip_are_right_under_perspective(monkeypatch):
    """Under perspective, Fit to window faces where it faces without, turned
    by the angles; the flip turns the picture over; nothing is mirrored and
    the triads say where each pole is."""
    context, viewer = _shown(monkeypatch, "FAFB14")
    try:
        sw, sess = switcher(viewer), session(viewer)
        camera = viewer.scene.camera
        signs = baseline(viewer, sess, sw)
        space = sess.registry.spaces["FAFB14"]

        def facing():
            return np.r_[camera.view_direction, camera.up_direction]

        for angles in ((0.0, 0.0, 0.0), (25.0, 35.0, -50.0)):
            for i, angle in enumerate(("spin", "tilt", "turn")):
                sw.rotation.box[angle].setValue(angles[i])
            sw.camera.perspective.setValue(0)
            sw.home.click()
            pump()
            flat = facing()
            sw.camera.perspective.setValue(60)
            camera.angles = (12.0, -33.0, 71.0)            # a drag
            sw.home.click()
            pump()
            assert camera.perspective == 60
            assert np.allclose(facing(), flat, atol=1e-6), angles
            th.settle_canvas(viewer)
            th.assert_triads_point_where_they_say(viewer, space)
            assert_no_hidden_mirror(viewer, sess, sw, signs)
            th.settle_canvas(viewer)
            upright = th.screen_axes(viewer)
            sw.flip.setChecked(True)
            camera.angles = (12.0, -33.0, 71.0)
            sw.home.click()
            pump()
            th.settle_canvas(viewer)
            # The same view, the screen's up turned over.
            assert np.allclose(th.screen_axes(viewer), FLIP * upright, atol=1e-6), angles
            assert sess.flipped
            th.settle_canvas(viewer)
            th.assert_triads_point_where_they_say(viewer, space)
            assert_no_hidden_mirror(viewer, sess, sw, signs)
            sw.flip.setChecked(False)
            pump()
        sw.rotation.reset.click()
        sw.camera.perspective.setValue(0)
        pump()
    finally:
        context.__exit__(None, None, None)
