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
    the clear it makes there is skipped. A change of scale, translate or
    affine -- the mirror is one -- clears the extent as before. So does a
    change of data, hidden or not: napari's `refresh` clears the extent
    only of a layer it slices then, and leaves a hidden one's to its next
    slice, which no longer clears it, so a refresh asked to update the
    extent of a hidden layer clears it here.
    """
    slice_dims, clear, refresh = layer._slice_dims, layer._clear_extent, layer.refresh
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

    def _refresh(*args, extent: bool = True, **kwargs):
        if extent and not layer.visible:
            clear()
        return refresh(*args, extent=extent, **kwargs)

    layer._clear_extent = _clear_extent
    layer._slice_dims = _slice_dims
    layer.refresh = _refresh


def clear_extent(layer) -> None:
    """Make napari measure `layer`'s extent again from its data.

    A hidden layer given new data keeps its old extent: napari's `refresh`
    clears the extent only of a layer it slices then, and slices no hidden
    one. For geometry that MOVED while hidden -- a surface reflected by its
    own vertices, `AtlasSurface._present` -- the old extent is wrong, where
    a hidden layer's extent otherwise only goes stale by shrinking.
    """
    layer._clear_extent()


def before_slicing(viewer, callback) -> None:
    """Call `callback` whenever the viewer is about to slice its layers.

    Before any layer is sliced, which no event handler can be: napari runs
    its own handlers of a dims event first, and slicing is one of them.
    Wraps the viewer's layer slicer once; the callback is kept for the
    viewer's life, so it must stay cheap and must not hold on to a scene.
    """
    slicer = viewer._layer_slicer
    hooks = getattr(slicer, "_lobemap_before", None)
    if hooks is None:
        hooks = []
        submit = slicer.submit

        def _submit(*args, **kwargs):
            for hook in hooks:
                hook()
            return submit(*args, **kwargs)

        slicer.submit = _submit
        slicer._lobemap_before = hooks
    if callback not in hooks:
        hooks.append(callback)


def no_scene_update(viewer, layer):
    """A context in which hiding or showing `layer` does not redraw napari's scene.

    napari updates its scene graph on every change of a layer's visibility,
    and that syncs the viewer's camera from vispy's. Inside a change of
    mode, vispy's camera is already the new mode's and the viewer's is not:
    a mesh hidden there, before napari slices for 2D, set the 2D plane to
    the 2D camera's depth, 0. The next visibility change updates it.
    """
    canvas = viewer.window._qt_viewer.canvas
    return layer.events.visible.blocker(canvas._update_scenegraph)


def shown_unsliced(layer):
    """A context in which showing `layer` does not slice it or rebuild its visual."""
    return layer._block_refresh()


def data_from_world(layer):
    """`layer.world_to_data` as it is now, as a function any thread can call.

    Called with the layer's own coordinates -- `list(np.asarray(world)[-ndim:])`
    -- it gives what `world_to_data` gives, to the last bit: it is the very
    transform that method builds and applies, copied.
    """
    return layer._transforms[1:].simplified.inverse


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
    "before_slicing",
    "clear_extent",
    "data_from_world",
    "gl_state",
    "keep_extent_while_slicing",
    "layer_visual",
    "no_scene_update",
    "shown_unsliced",
    "text_visual",
    "triangulate_edge",
    "triangulate_face",
]
