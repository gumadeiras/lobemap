"""Hover under perspective, in every brain.

Hover names the compartment drawn under the cursor -- read from the picture
itself, each compartment drawn in a color of its own -- and the triads say
where each pole is, fitted and zoomed in, at 0, 45 and 90 degrees.
"""

from __future__ import annotations

import numpy as np
import pytest
import turned_harness as th
from viewer_harness import SPACES, pump

pytestmark = pytest.mark.requires_data
napari = pytest.importorskip("napari")


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
