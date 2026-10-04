"""Fit to window, and napari's home, frame the whole brain in 3D.

The brain is the box around every layer, built or not. Each of its corners is
mapped to the canvas through vispy's own transform -- the camera, the zoom
and the perspective as they are drawn -- and must land inside the canvas with
a margin, while the corners together span most of it. napari's home fitted
the box seen down the image's axes before lobemap turned the camera to the
front, and zoomed FAFB14 from 0.68 to 1.97 pixels per micrometer, its sides
cut; under perspective, a fit for a flat camera put the near corners off the
canvas.
"""

from __future__ import annotations

import numpy as np
import pytest
from viewer_harness import SPACES, canvas_position, launched, pump, session, switcher

pytestmark = pytest.mark.requires_data
napari = pytest.importorskip("napari")


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


def _drawn(viewer) -> tuple[np.ndarray, np.ndarray]:
    """The brain's box as drawn: its corners' (left, top) and (right, bottom)
    on the canvas, in pixels, and the canvas's (width, height)."""
    box = np.asarray(viewer.layers.get_extent(list(viewer.layers)).world, float)
    corners = [np.where(bits, box[1], box[0]) for bits in np.ndindex(2, 2, 2)]
    points = np.array([canvas_position(viewer, corner) for corner in corners])
    size = np.asarray(viewer.window._qt_viewer.canvas.view.rect.size, float)
    return np.array([points.min(axis=0), points.max(axis=0)]), size


def assert_framed(viewer, what) -> None:
    """Every corner inside the canvas, half a percent from its edges at
    least, and the corners spanning nine tenths of it, or more, one way."""
    pump()
    (low, high), size = _drawn(viewer)
    assert np.all(low >= 0.005 * size) and np.all(high <= 0.995 * size), (
        what, low.round(1), high.round(1), size)
    assert np.max((high - low) / size) >= 0.9, (what, ((high - low) / size).round(3))


@pytest.mark.parametrize("space", SPACES)
def test_fit_to_window_frames_the_whole_brain_in_3d(monkeypatch, space):
    context, viewer = _shown(monkeypatch, space)
    try:
        sw, camera = switcher(viewer), viewer.scene.camera
        home = viewer.window._qt_viewer.viewerButtons.resetViewButton
        assert_framed(viewer, "at open")
        opened = camera.zoom
        sw.home.click()
        assert_framed(viewer, "Fit to window")
        # The open was already framed: Fit to window frames it the same.
        assert camera.zoom == pytest.approx(opened, rel=1e-6)
        for angles, flip, perspective in (((0, 0, 0), False, 45),
                                          ((25, 35, -50), False, 0),
                                          ((25, 35, -50), True, 0),
                                          ((25, 35, -50), True, 60),
                                          ((-120, 70, 160), False, 90)):
            for i, angle in enumerate(("spin", "tilt", "turn")):
                sw.rotation.box[angle].setValue(angles[i])
            sw.flip.setChecked(flip)
            sw.camera.perspective.setValue(perspective)
            camera.zoom = camera.zoom * 3              # the user zooms in
            sw.home.click()
            assert_framed(viewer, ("Fit to window", angles, flip, perspective))
            camera.zoom = camera.zoom / 3
            home.click()
            assert_framed(viewer, ("napari's home", angles, flip, perspective))
        sw.flip.setChecked(False)
        sw.camera.perspective.setValue(0)
        sw.rotation.reset.click()
        pump()
        assert session(viewer).rotation == (0.0, 0.0, 0.0)
    finally:
        context.__exit__(None, None, None)
