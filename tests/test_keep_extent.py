"""A slice step leaves every layer's extent, and so the scene's, where it was.

napari clears a sliced layer's extent on every step, and the layer list then
recomputes all of them. Nothing a step does moves a layer, so the image,
labels and contour layers keep theirs; a real move still recomputes it.
"""

from __future__ import annotations

import numpy as np
import pytest

from lobemap.viewer.napari_private import keep_extent_while_slicing

napari = pytest.importorskip("napari")


def test_a_step_does_not_recompute_the_scene_extent_but_a_move_does():
    viewer = napari.Viewer(show=False)
    try:
        layer = viewer.add_image(np.zeros((20, 8, 8), np.uint8), scale=(2, 1, 1))
        keep_extent_while_slicing(layer)
        before = viewer.layers.extent
        viewer.dims.set_current_step(0, 5)
        assert np.asarray(layer._slice.image.raw).shape == (8, 8)
        assert viewer.layers.extent is before, "a step recomputed the extent"
        layer.translate = (10, 0, 0)
        assert viewer.layers.extent.world[0][0] == pytest.approx(10.0)
    finally:
        viewer.close()


@pytest.mark.requires_data
@pytest.mark.requires_data("fafb_stain")
def test_stepping_a_scene_recomputes_no_extent_and_the_mirror_still_does(registry):
    from qtpy.QtWidgets import QApplication

    from lobemap.viewer.app import load_space

    viewer = napari.Viewer(show=False, ndisplay=2)
    try:
        session = load_space(viewer, registry, "FAFB14", fit=False)
        QApplication.processEvents()
        shown = [layer for layer in viewer.layers if layer.visible]
        kinds = {layer.metadata.get("lobemap", {}).get("kind") for layer in shown}
        assert {"image", "contours"} <= kinds, kinds
        axis = int(viewer.dims.order[0])
        before = viewer.layers.extent
        for step in range(3):
            viewer.dims.set_current_step(axis, viewer.dims.current_step[axis] + 1 + step)
        assert viewer.layers.extent is before, "a step recomputed every extent"
        # The mirror moves every layer: that extent is recomputed, and the
        # slider range with it.
        session.set_mirror(True)
        assert viewer.layers.extent is not before
        mirrored = viewer.layers.extent.world
        expect = 2.0 * session.mirror_center - before.world[::-1, 0]
        np.testing.assert_allclose(mirrored[:, 0], expect, atol=1e-6)
    finally:
        viewer.close()
