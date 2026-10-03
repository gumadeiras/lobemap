"""Refreshing a contour layer repeatedly must not mix 2D and 3D vertices.

This is a regression test for a crash that only appeared on the SECOND entry
into 2D, which is why it survived every single-pass check: viewing the FAFB
neuropils in slice mode raised

    ValueError: all the input array dimensions except for the concatenation
    axis must match exactly, but along dimension 1, the array at index 0 has
    size 2 and the array at index 1 has size 3

from `np.vstack` inside napari's `ShapeList._extend_meshes`. The cause was
assigning `layer.data` and then `layer.shape_type`: the `shape_type` setter
re-adds every shape onto a shape list that still holds the previous ones, and
once the layer had been displayed in 2D those carried 2D mesh vertices.
"""

from __future__ import annotations

import numpy as np
import pytest
from viewer_harness import assert_renders_loops, contour_loops

from lobemap.core.meshfmt import MeshSet
from lobemap.viewer.contours import ContourOverlay


def _cube_at(z0: float) -> tuple[np.ndarray, np.ndarray]:
    """A closed box spanning z in [z0, z0+2], so any plane inside it cuts."""
    import itertools

    v = np.array(list(itertools.product([0.0, 2.0], [0.0, 2.0], [z0, z0 + 2.0])),
                 dtype=np.float32)
    import scipy.spatial

    hull = scipy.spatial.ConvexHull(v.astype(float))
    return v, hull.simplices.astype(np.int32)


def _meshset() -> MeshSet:
    va, fa = _cube_at(0.0)
    vb, fb = _cube_at(1.0)
    return MeshSet(
        vertices=np.vstack([va, vb]),
        faces=np.vstack([fa, fb + len(va)]),
        vertex_offsets=np.array([0, len(va), len(va) + len(vb)]),
        face_offsets=np.array([0, len(fa), len(fa) + len(fb)]),
        names=["a", "b"],
        meta={},
    )


def test_cycling_between_2d_and_3d_keeps_redrawing():
    napari = pytest.importorskip("napari")
    viewer = napari.Viewer(show=False)
    try:
        overlay = ContourOverlay(viewer, _meshset(), "t", "#ff0000")
        # Contours ship hidden -- the display-mode hook reveals them in 2D --
        # and `refresh` is a no-op while hidden, so the test has to do what
        # that hook does or it would pass against a layer drawing nothing.
        overlay.layer.visible = True
        viewer.dims.ndisplay = 2
        viewer.dims.order = (2, 1, 0)
        viewer.dims.set_point(2, 1.5)

        drawn = []
        for _ in range(3):
            viewer.dims.ndisplay = 2
            overlay.refresh()
            drawn.append(len(contour_loops(overlay)))
            assert_renders_loops(overlay)
            viewer.dims.ndisplay = 3
            overlay.refresh()

        assert all(n > 0 for n in drawn), f"contours stopped being drawn: {drawn}"
        assert len(set(drawn)) == 1, (
            f"the same plane gave different contour counts across cycles: {drawn}"
            " -- shapes are accumulating instead of being replaced"
        )
    finally:
        viewer.close()


def test_refresh_replaces_rather_than_appends():
    """Two refreshes on one plane must leave one set of shapes, not two."""
    napari = pytest.importorskip("napari")
    viewer = napari.Viewer(show=False)
    try:
        overlay = ContourOverlay(viewer, _meshset(), "t", "#ff0000")
        overlay.layer.visible = True
        viewer.dims.ndisplay = 2
        viewer.dims.order = (2, 1, 0)
        viewer.dims.set_point(2, 1.5)
        overlay.refresh()
        once = len(contour_loops(overlay))
        overlay.refresh()
        assert len(contour_loops(overlay)) == once
        assert len(overlay._shape_index) == once
        assert_renders_loops(overlay)
    finally:
        viewer.close()


def test_the_slice_blends_and_fades_as_napari_draws_the_layer():
    """The contour visuals take the layer's blending and opacity as napari's
    own visual of that layer does: the GL state vispy draws them with, and the
    alpha their shaders apply."""
    napari = pytest.importorskip("napari")
    from vispy.scene.visuals import Text

    from lobemap.viewer.napari_private import layer_visual

    viewer = napari.Viewer(show=False)
    try:
        overlay = ContourOverlay(viewer, _meshset(), "t", "#ff0000")
        overlay.layer.visible = True
        viewer.dims.ndisplay = 2
        viewer.dims.order = (2, 1, 0)
        viewer.dims.set_point(2, 1.5)
        overlay.set_labels({0, 1})
        assert overlay.visual.mesh.visible and overlay.visual.text.visible
        own = layer_visual(viewer, overlay.layer).node
        shapes = next(v for v in own._subvisuals if not isinstance(v, Text))
        text = next(v for v in own._subvisuals if isinstance(v, Text))
        for blending in ("additive", "opaque", "minimum", "translucent_no_depth",
                         "translucent"):
            overlay.layer.blending = blending
            assert overlay.visual.mesh._vshare.gl_state == shapes._vshare.gl_state, blending
            assert overlay.visual.text._vshare.gl_state == text._vshare.gl_state, blending
        for opacity in (0.25, 0.8, 1.0):
            overlay.layer.opacity = opacity
            for visual in (overlay.visual.mesh, overlay.visual.text):
                assert visual.opacity == pytest.approx(own.opacity) == opacity
                assert visual._opacity_filter.alpha == pytest.approx(opacity)
    finally:
        viewer.close()


def _discs(n: int, points: int = 900) -> MeshSet:
    """`n` closed prisms over circles of `points` points, side by side on x-y,
    each a different size: every plane between z = 0 and 2 cuts all of them."""
    t = np.linspace(0.0, 2.0 * np.pi, points, endpoint=False)
    i = np.arange(points)
    j = np.roll(i, -1)
    bottom, top, cb, ct = i, i + points, 2 * points, 2 * points + 1
    faces = np.vstack([
        np.column_stack((bottom, bottom[j], top[j])),
        np.column_stack((bottom, top[j], top)),
        np.column_stack((np.full(points, cb), bottom[j], bottom)),
        np.column_stack((np.full(points, ct), top, top[j])),
    ])
    verts, tris = [], []
    side = int(np.ceil(np.sqrt(n)))
    for k in range(n):
        r = 1.0 + 0.01 * k
        x0, y0 = 3.0 * (k % side), 3.0 * (k // side)
        ring = np.column_stack((x0 + r * np.cos(t), y0 + r * np.sin(t)))
        v = np.vstack([np.column_stack((ring, np.zeros(points))),
                       np.column_stack((ring, np.full(points, 2.0))),
                       [[x0, y0, 0.0], [x0, y0, 2.0]]])
        tris.append(faces + sum(len(a) for a in verts))
        verts.append(v)
    vertex_offsets = np.cumsum([0] + [len(v) for v in verts])
    face_offsets = np.cumsum([0] + [len(f) for f in tris])
    return MeshSet(vertices=np.vstack(verts).astype(np.float32),
                   faces=np.vstack(tris).astype(np.int32),
                   vertex_offsets=vertex_offsets, face_offsets=face_offsets,
                   names=[f"d{k}" for k in range(n)], meta={})


@pytest.mark.parametrize("n", [18, 40])
def test_a_plane_drawing_more_than_65536_points_puts_every_triangle_in_place(n):
    """No triangle index wraps, under NumPy 1 or 2.

    18 discs: outlines indexed in 16 bits, offset past 65,535 by the fills
    drawn under them. 40: the fills alone pass it.
    """
    napari = pytest.importorskip("napari")
    from lobemap.viewer.layers import categorical_colors

    viewer = napari.Viewer(show=False)
    try:
        meshset = _discs(n)
        overlay = ContourOverlay(viewer, meshset, "t", "#ff0000",
                                 colors=categorical_colors(n))
        overlay.layer.visible = True
        viewer.dims.ndisplay = 2
        viewer.dims.order = (2, 1, 0)
        viewer.dims.set_point(2, 1.5)
        overlay.set_fills(range(n))
        assert len(contour_loops(overlay)) == n
        vertices = overlay.visual.mesh.mesh_data.get_vertices()
        assert len(vertices) > 2**16
        assert_renders_loops(overlay)
    finally:
        viewer.close()
