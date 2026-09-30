"""The private napari internals the 2D slice relies on, in one place.

napari has no public way to draw a custom visual under a layer, or to keep
a slice step from recomputing every layer's extent, so these reach into
it. pyproject pins napari to the minor version they were written against,
and `tests/test_napari_private.py` fails with the name of whatever here is
missing or has changed shape, so a napari upgrade breaks a test rather than
the viewer.
"""

from __future__ import annotations


def layer_visual(viewer, layer):
    """napari's vispy visual for `layer`: its `.node` and its `.font_info`."""
    return viewer.window._qt_viewer.canvas.layer_to_visual[layer]


def text_visual(parent, font_info):
    """napari's Text visual, which draws with the font napari's own labels use."""
    from napari._vispy.visuals.text import Text

    return Text(parent=parent, font_info=font_info)


def gl_state(blending: str) -> dict:
    """The vispy GL state napari gives a layer blended `blending`."""
    from napari._vispy.utils.gl import BLENDING_MODES

    return dict(BLENDING_MODES[blending])


def keep_extent_while_slicing(layer) -> None:
    """Stop a slice step from discarding `layer`'s cached extent.

    napari clears every sliced layer's extent on every step, and the layer
    list then recomputes the extent of every layer -- with unit conversions
    through pint, about a millisecond for a scene here -- although a slice
    moves no layer. The saving only arrives once no visible layer clears
    it, since one clear recomputes them all, so every image and contour
    layer gets this.

    Only the slice step is held back: napari slices in `_slice_dims`, and
    the clear it makes there is skipped. A change of data, scale, translate
    or affine -- the mirror is one -- clears the extent as before.
    """
    slice_dims, clear = layer._slice_dims, layer._clear_extent
    slicing = [False]

    def _clear_extent() -> None:
        if not slicing[0]:
            clear()

    def _slice_dims(*args, **kwargs):
        slicing[0] = True
        try:
            return slice_dims(*args, **kwargs)
        finally:
            slicing[0] = False

    layer._clear_extent = _clear_extent
    layer._slice_dims = _slice_dims


def triangulate_edge(ring):
    """napari's own stroke of a closed 2D path, for when bermuda is missing."""
    from napari.layers.shapes._shapes_utils import triangulate_edge as edge

    return edge(ring, closed=True)


def triangulate_face(ring):
    """napari's own polygon fill of a 2D ring, for when bermuda is missing."""
    from napari.layers.shapes._accelerated_triangulate_dispatch import (
        normalize_vertices_and_edges,
    )
    from napari.layers.shapes._shapes_utils import triangulate_face_vispy

    raw, edges = normalize_vertices_and_edges(ring, close=True)
    return triangulate_face_vispy(raw, edges, ring)


__all__ = [
    "gl_state",
    "keep_extent_while_slicing",
    "layer_visual",
    "text_visual",
    "triangulate_edge",
    "triangulate_face",
]
