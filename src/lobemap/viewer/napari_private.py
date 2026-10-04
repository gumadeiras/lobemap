"""The private napari internals the 2D slice relies on, in one place.

napari has no public way to draw a custom visual under a layer, or to keep
a slice step from recomputing every layer's extent, so these reach into
it. pyproject pins napari to the minor version they were written against,
and `tests/test_napari_private.py` fails with the name of whatever here is
missing or has changed shape, so a napari upgrade breaks a test rather than
the viewer.
"""

from __future__ import annotations

import numpy as np


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


def stop_before_slicing(viewer, callback) -> None:
    """Stop calling `callback` before slicing (`before_slicing`)."""
    hooks = getattr(viewer._layer_slicer, "_lobemap_before", None)
    if hooks is not None and callback in hooks:
        hooks.remove(callback)


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


def fit_axis_labels(viewer) -> None:
    """Size the slider labels for their text, as napari does when one is edited.

    napari sizes them when the user edits one or a slider changes size, but
    not when `dims.axis_labels` is set; and it caps them at a fifth of the
    width of the first slider, shown or not, which hidden since the window
    opened is Qt's default 100 px. A turned 2D view's `depth` kept the width
    of an `x` and read `…`, and sized under that cap read `de…`. So each
    hidden slider is first given the width the shown ones have, which it
    keeps through napari's next sizing, on a resize.
    """
    qt_dims = getattr(getattr(viewer.window, "_qt_viewer", None), "dims", None)
    if qt_dims is None:
        return
    sliders = qt_dims.slider_widgets
    shown = [slider.width() for slider in sliders if slider.isVisible()]
    for slider in sliders:
        if shown and not slider.isVisible():
            slider.resize(max(shown), slider.height())
    qt_dims._resize_axis_labels()


def status_for_cursor(viewer, words) -> None:
    """Let `words(position, view_direction)` say what the cursor is over,
    before napari's own words for it; once per viewer.

    napari reckons the status bar's words in `_calc_status_from_cursor`:
    its status thread calls it on every move of the cursor over the canvas,
    and the viewer on a change of active layer. Wrapped on the viewer
    instance, as `view.install_home_orientation` wraps `reset_view`, so
    both go through it. Where `words` gives nothing, napari's words stand.
    It runs in napari's thread, where the scene can change under it: what
    fails there leaves napari's words, as napari leaves its own on a
    failure.
    """
    if getattr(viewer.__dict__.get("_calc_status_from_cursor"), "_lobemap", False):
        return
    reckon = type(viewer)._calc_status_from_cursor.__get__(viewer)

    def _calc_status_from_cursor():
        if viewer.mouse_over_canvas:
            try:
                said = words(viewer.cursor.position, viewer.cursor._view_direction)
            except Exception:                       # noqa: BLE001 - napari's words stand
                said = None
            if said:
                return said, said if viewer.tooltip.visible else ""
        return reckon()

    _calc_status_from_cursor._lobemap = True
    object.__setattr__(viewer, "_calc_status_from_cursor", _calc_status_from_cursor)


def shown_unsliced(layer):
    """A context in which showing `layer`, or changing its data or transform,
    does not slice it or rebuild its visual; the caller slices it after."""
    return layer._block_refresh()


# -- a turned 2D view (`viewer.turned`) -------------------------------------

#: The layer-list class with a hooked extent, per original class.
_HOOKED: dict[type, type] = {}


def _hooked_class(base: type) -> type:
    from functools import cached_property

    if base not in _HOOKED:
        class Hooked(base):
            """napari's layer list, whose extent a turned view rewrites."""

            @cached_property
            def extent(self):
                value = base.extent.func(self)
                world, step = self._lobemap_ranges(value.world, value.step)
                return type(value)(data=value.data, world=world, step=step,
                                   units=value.units)

            @cached_property
            def _extent_world_augmented(self):
                return self._lobemap_fit(base._extent_world_augmented.func(self))

        _HOOKED[base] = Hooked
    return _HOOKED[base]


def hook_extent(viewer, ranges=None, fit=None) -> None:
    """Rewrite the extent napari reads its slider ranges and its fit from, or stop.

    `ranges(world, step)` takes the (2, ndim) world extent and the step
    napari computed for `dims.range` and returns the ones to use; `fit(world)`
    does the same for the extent the camera is fitted to (`reset_view`,
    `fit_to_view`). Both None puts napari's own back. The slider ranges are recomputed at once, as napari
    recomputes them when a layer changes.

    napari has no public way to do this. Its layer list caches the extent
    in two cached properties, and the viewer reads them; the list's class is
    swapped for a subclass that passes them through these, and back.
    """
    layers = viewer.layers
    hooked = ranges is not None or fit is not None
    base = getattr(layers, "_lobemap_base", type(layers))
    if hooked:
        layers._lobemap_base = base
        layers._lobemap_ranges = ranges or (lambda world, step: (world, step))
        layers._lobemap_fit = fit or (lambda world: world)
        layers.__class__ = _hooked_class(base)
    elif type(layers) is not base:
        layers.__class__ = base
        for name in ("_lobemap_base", "_lobemap_ranges", "_lobemap_fit"):
            layers.__dict__.pop(name, None)
    refresh_extent(viewer)
    # napari sizes the 3D camera's depth range from the same extent, on a
    # change of mode only: entered while turned, it kept the turned scene's
    # depth after Reset rotation, and drew a few thousand edge pixels other
    # than the same trip unturned did.
    qt_viewer = getattr(viewer.window, "_qt_viewer", None)
    if qt_viewer is not None:
        qt_viewer._update_camera_depth()


def augmented_extent(layer):
    """`layer`'s extent with its pixels' size: what napari fits the view to."""
    return layer._extent_augmented


def refresh_extent(viewer) -> None:
    """Make napari measure the layer list's extent again and reset the sliders."""
    viewer.layers._clean_cache()
    viewer._on_layers_change()


def level_of(layer):
    """(pyramid level, region) a layer is sliced at, for `put_level`."""
    return (getattr(layer, "_data_level", None),
            np.array(getattr(layer, "corner_pixels", np.zeros((2, 0), int)), copy=True))


def put_level(layer, level) -> None:
    """Give `layer` back the level and region `level_of` recorded; not sliced."""
    data_level, corners = level
    if data_level is not None:
        layer._data_level = data_level
    if corners.shape == np.shape(layer.corner_pixels):
        layer.corner_pixels = corners


def slice_now(viewer, layer) -> None:
    """Slice `layer` now, at its level and region, for the viewer's dims.

    `refresh` alone reuses the slice input the layer last had, which can be
    from before a change of mode; it is made from the dims first.
    """
    if layer.visible:
        layer._slicing_state.set_slice_input_from_dims(viewer.dims, True)
        layer.refresh(extent=False)


def update_draw(viewer, layer) -> None:
    """Pick `layer`'s pyramid level and region for the canvas, as napari's draw does.

    A hidden canvas never draws, and a new data array leaves the layer on
    its coarsest level until it does; this asks the layer what napari's own
    draw would. The layer is not sliced here.
    """
    canvas = viewer.window._qt_viewer.canvas
    displayed = list(viewer.dims.displayed)
    with layer._block_refresh():
        layer._update_draw(
            scale_factor=1 / viewer.scene.camera.zoom,
            corner_pixels_displayed=canvas._viewbox_corners_in_world[:, displayed],
            shape_threshold=canvas._current_viewbox_size[::-1],
        )


def level_as_unturned(layer, turn_2x2=None) -> None:
    """Pick `layer`'s pyramid level as if its in-plane turn were not there, or stop.

    napari picks a level from the box, in data coordinates, that holds the
    canvas; turned in plane, that box is the turned canvas's bounding box,
    larger than the canvas, and napari went a level coarser at the same zoom.
    The box is still what is read. Only the threshold napari compares it
    with is scaled by the same growth, axis by axis, so each comparison is
    the one the unturned canvas would make. `turn_2x2` is the turn on the
    displayed axes, in their order; None stops.
    """
    if turn_2x2 is None:
        layer.__dict__.pop("_update_draw", None)
        return
    inverse = np.abs(np.asarray(turn_2x2, float).T)
    update = type(layer)._update_draw.__get__(layer)

    def _update_draw(scale_factor, corner_pixels_displayed, shape_threshold):
        size = np.abs(np.diff(np.asarray(corner_pixels_displayed, float), axis=0))[0]
        grow = (inverse @ size) / np.where(size > 0, size, 1.0)
        threshold = np.asarray(shape_threshold, float) * np.maximum(grow, 1.0)
        return update(scale_factor, corner_pixels_displayed, tuple(threshold))

    layer.__dict__["_update_draw"] = _update_draw


def keep_volume_texture(viewer, layer) -> None:
    """Upload `layer`'s 3D voxels to the GPU only when they change.

    On every entry into 3D napari gives its volume node the 3D slice two or
    three times -- at napari's own 3D level, at the pinned level in 2D's
    axis order, and then in 3D's -- and vispy uploads each, although the
    last is the very buffer the texture held when 3D was left: the stains'
    pinned levels are 255-613 MB, and uploading them was 0.35-0.55 s of the
    first frame. So the node takes its voxels at its next draw instead, the
    last ones it was given, and only if they are not that buffer -- same
    address, shape, strides and dtype -- which is kept alive meanwhile, as
    vispy keeps it, so no other array can take its address. Three go
    straight through: a contrast change vispy re-uploads for, a layer's
    first voxels, and voxels of another dtype. napari reads the texture's
    format straight after `set_data`, for the cutoffs of translucent and
    iso rendering, and from vispy's float32 placeholder it computed them
    unnormalized: on a first entry into 3D from 2D the stain drew nothing.
    """
    node = layer_visual(viewer, layer)._layer_node._volume_node
    upload, prepare = node.set_data, node._prepare_draw
    state: dict = {"pending": None, "held": None}

    def key(vol):
        return (vol.__array_interface__["data"][0], vol.shape, vol.strides, vol.dtype.str)

    def set_data(vol, clim=None, copy=True):
        if clim is not None or state["held"] is None or state["held"][1].dtype != vol.dtype:
            state["pending"] = None
            upload(vol, clim=clim, copy=copy)
            state["held"] = (key(vol), vol)
            return
        state["pending"] = (vol, copy)
        node.update()

    def _prepare_draw(*args, **kwargs):
        pending, state["pending"] = state["pending"], None
        if pending is not None:
            vol, copy = pending
            if state["held"] is None or state["held"][0] != key(vol):
                upload(vol, copy=copy)
                state["held"] = (key(vol), vol)
        return prepare(*args, **kwargs)

    # vispy freezes its visuals against new attributes.
    node.unfreeze()
    node.set_data = set_data
    node._prepare_draw = _prepare_draw
    node.freeze()


def front_face(viewer, layer, clockwise: bool) -> None:
    """Rasterize `layer`'s faces as front-facing when wound clockwise on
    screen, or counterclockwise, as GL does by default.

    vispy's smooth shading turns a normal around on a face the camera sees
    from behind (`gl_FrontFacing`), and a camera that mirrors the picture
    sees every face from behind: the surfaces came out lit from inside.
    The face is vispy's own GL state, but napari sets a layer's whole GL
    state anew whenever its blending, the layer order or the bottom visible
    layer changes (`_on_blending_change`), so the node's `set_gl_state` is
    wrapped, once, to put the face back after each.
    """
    node = layer_visual(viewer, layer).node
    face = "cw" if clockwise else "ccw"
    if getattr(node, "_lobemap_face", None) is None:
        if not clockwise:
            return                      # never turned: GL's own default
        set_state = node.set_gl_state

        def set_gl_state(*args, **kwargs):
            set_state(*args, **kwargs)
            node.update_gl_state(front_face=node._lobemap_face)

        # vispy freezes its visuals against new attributes.
        node.unfreeze()
        node.set_gl_state = set_gl_state
        node._lobemap_face = face
        node.freeze()
    node._lobemap_face = face
    node.update_gl_state(front_face=face)
    node.update()


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
    "augmented_extent",
    "before_slicing",
    "clear_extent",
    "data_from_world",
    "fit_axis_labels",
    "front_face",
    "gl_state",
    "hook_extent",
    "keep_extent_while_slicing",
    "keep_volume_texture",
    "layer_visual",
    "level_as_unturned",
    "level_of",
    "no_scene_update",
    "put_level",
    "refresh_extent",
    "shown_unsliced",
    "slice_now",
    "status_for_cursor",
    "stop_before_slicing",
    "text_visual",
    "triangulate_edge",
    "triangulate_face",
    "update_draw",
]
