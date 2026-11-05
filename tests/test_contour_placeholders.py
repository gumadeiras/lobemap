"""An empty Shapes carrier draws only lobemap's own slice visuals."""

import numpy as np
import pytest
import trimesh

from lobemap.core.meshfmt import MeshSet
from lobemap.viewer.contours import ContourOverlay
from lobemap.viewer.napari_private import layer_visual

napari = pytest.importorskip("napari")


def test_the_shapes_carrier_does_not_draw_its_empty_placeholders():
    from qtpy.QtWidgets import QApplication

    mesh = trimesh.creation.box(extents=(10, 10, 10))
    meshset = MeshSet.from_parts([("box", mesh.vertices, mesh.faces)])
    viewer = napari.Viewer(show=False, ndisplay=2)
    viewer.add_image(np.zeros((10, 10, 10), np.uint8))
    viewer.dims.set_point(0, 1)
    overlay = ContourOverlay(viewer, meshset, "sections", "red")
    try:
        overlay.layer.visible = True
        overlay.refresh()
        node = layer_visual(viewer, overlay.layer).node
        placeholders = (node.shape_faces, node.shape_highlights,
                        node.highlight_lines, node.highlight_vertices)
        assert all(not v.visible for v in placeholders), "empty native shapes were drawn"
        assert overlay.visual.mesh.visible
        canvas = viewer.window._qt_viewer.canvas._scene_canvas
        original = canvas.render()
        # The native stand-ins draw no pixels; disabling them changes no geometry.
        for visual in placeholders:
            visual.visible = True
        np.testing.assert_array_equal(canvas.render(), original)
        for visual in placeholders:
            visual.visible = False
        for axis in (0, 1, 2):
            viewer.dims.order = (axis, *(d for d in range(3) if d != axis))
            viewer.dims.set_point(axis, 1)
            overlay.layer.opacity = .5
            overlay.layer.blending = "additive"
            QApplication.processEvents()
            assert all(not v.visible for v in placeholders)
    finally:
        overlay.stop()
        viewer.close()
