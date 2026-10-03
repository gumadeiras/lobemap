"""How a scene is looked at: the camera, the fit, the home button, the mirror
and the flip.

None of this changes the data. The camera is turned onto each space's
measured anatomy, the view is fitted to the canvas as the window settles,
the home button restores the anatomical view rather than napari's array
view, the mirror reflects every layer, the surfaces by their own vertices
(`AtlasSurface._present`) and the rest by a world transform, and the flip
turns the picture upside down by the camera (`show_upside_down`). A failed
space switch gives the view back through `capture_view` and `restore_view`.
"""

from __future__ import annotations

import contextlib
import weakref

import numpy as np

#: napari's camera orientation along the screen's vertical: "down", the
#: way napari draws array rows and `rotation.grid_frame` reads them, or
#: "up", which shows the picture upside down (`show_upside_down`).
UPRIGHT, UPSIDE_DOWN = "down", "up"

#: napari's camera orientation along the screen's depth and horizontal,
#: the only ones lobemap shows (`keep_orientation`).
TOWARD, RIGHT = "towards", "right"

#: The viewers whose camera `keep_orientation` watches.
_KEPT: weakref.WeakSet = weakref.WeakSet()

#: The array axis a mirror reflects along.
#:
#: napari names the axes x/y/z in array order (`viewer.axes.VOXEL_LABELS`),
#: so this is x -- and x is the left-right axis in all four spaces, 1.0 deg
#: off in the hemibrain, 1.3 in the male CNS, 3.7 in FAFB14 and 5.5 in
#: GRABE. So the mirror is a left-right flip and not an arbitrary one,
#: though it is about the ARRAY axis rather than the measured lateral
#: direction: exactly so a 2D slice keeps cutting the voxel grid squarely.
MIRROR_AXIS = 0


def orient_anterior(viewer, space, reflect_axis: int | None = None,
                    angles=None) -> bool:
    """Face the anterior surface of the brain, dorsal up. True if applied.

    Uses the space's MEASURED anatomy, so the view really is down the
    antero-posterior axis rather than down the nearest array axis to it
    -- which differs by 15-18 degrees in the EM volumes and 31 in GRABE.

    `reflect_axis` is the array axis the scene is shown mirrored along, or
    None. The frame is reflected with it, so a mirrored scene is looked at
    from its own reflected front, the mirror image of the unmirrored view.

    `angles` turn the scene from there, (spin, tilt, turn) degrees about
    the screen's axes (`rotation`): the camera is this view turned by their
    inverse, so no layer moves. None takes the angles of the scene the
    viewer shows (`rotation.angles_of`), which is what Home faces. A picture
    shown upside down (`show_upside_down`) is this view upside down.

    Needs the whole frame. A view direction alone leaves the roll free,
    so a camera built from anterior without dorsal would face the right
    way at an arbitrary tilt -- worse than an obvious default, because
    it looks deliberate. A space with no rotation declared is left
    alone.
    """
    from ..core.model import anatomical_axes

    frame = anatomical_axes(space)
    if viewer.dims.ndisplay != 3 or frame is None:
        return False
    anterior, dorsal = np.array(frame["A"]), np.array(frame["D"])
    if reflect_axis is not None:
        anterior[reflect_axis] *= -1.0
        dorsal[reflect_axis] *= -1.0

    from .rotation import ZERO, angles_of, turned_view

    view, up = -anterior, dorsal
    angles = angles_of(viewer) if angles is None else tuple(angles)
    if tuple(float(a) for a in angles) != ZERO:
        view, up = turned_view(view, up, angles)
    if upside_down(viewer):
        # The angles stay the upright view's: napari draws its up at the
        # top of the screen, and the view's up is now at the bottom.
        up = -up
    camera = viewer.scene.camera
    camera.set_view_direction(view_direction=tuple(view), up_direction=tuple(up))
    # Up is what napari's angle round trip can lose, so that is what is
    # checked; see `tests/test_default_view.py`.
    return bool(np.dot(np.asarray(camera.up_direction), up) > 0.99)


def upside_down(viewer) -> bool:
    """Whether the camera shows the picture upside down (`show_upside_down`)."""
    return str(viewer.scene.camera.orientation[1]) == UPSIDE_DOWN


def show_upside_down(viewer, on: bool) -> None:
    """Show the picture upside down, or upright again. Display only.

    A flip of the screen, top to bottom about the middle of the view, after
    every turn and mirror of the scene, made by napari's camera: its
    vertical axis is turned to point up rather than down. Nothing else
    moves -- no layer, slider, plane or pick -- and the camera's center,
    zoom and angles are kept. In 2D that is the flip itself. In 3D napari
    keeps the screen's up as the camera's up and reverses the handedness,
    so the same angles show the scene mirrored left to right and turned
    180 degrees, which is upside down: the angles keep meaning the upright
    view, and Home (`orient_anterior`), a turn, a trip through 2D or a
    failed switch put back the same picture, flipped. Off, the picture is
    exactly what it was.

    What napari does not do itself, `keep_orientation` does, whoever turns
    the picture over: this, or the up/down menu of napari's camera popup.
    """
    keep_orientation(viewer)
    camera = viewer.scene.camera
    depth, vertical, horizontal = (str(o) for o in camera.orientation)
    want = UPSIDE_DOWN if on else UPRIGHT
    if vertical == want:
        return
    camera.orientation = (depth, want, horizontal)


def keep_orientation(viewer) -> None:
    """Follow every change of the camera's orientation with what napari
    leaves undone, and refuse the ones no control of lobemap's shows.

    napari's camera popup sets the orientation of each screen axis. Up or
    down is the flip (`show_upside_down`), which the View dock shows. Left
    along the horizontal, or away along the depth, would mirror the picture
    with no control to say so -- napari's preferences can ask for either
    too -- so each is put back to napari's default, right and toward.

    After a flip, two things napari does not do are done here. It hands its
    3D camera the new handedness but not the turn its angles mean under it,
    and its next draw read the angles back from the stale turn, which lost
    the view: so the angles are announced again. And a reversed handedness
    winds every face the other way on screen, which vispy's shading takes
    for the inside: so each surface takes its clockwise faces for its front
    ones (`face_front`), and is lit from outside. The light turns over with
    the picture, so in 3D too the picture is the upright one upside down.

    Connected after napari's own handlers, so they have turned the camera
    first. Installed once per viewer; later calls do nothing.
    """
    if viewer in _KEPT:
        return
    _KEPT.add(viewer)
    camera = viewer.scene.camera
    ref = weakref.ref(viewer)

    def _settle(event=None) -> None:
        live = ref()
        if live is None:
            return
        depth, vertical, horizontal = (str(o) for o in camera.orientation)
        if (depth, horizontal) != (TOWARD, RIGHT):
            # Its own change of orientation does the rest.
            camera.orientation = (TOWARD, vertical, RIGHT)
            return
        camera.events.angles(value=camera.angles)
        face_front(live)

    camera.events.orientation.connect(_settle, position="last")
    depth, vertical, horizontal = (str(o) for o in camera.orientation)
    if (depth, horizontal) != (TOWARD, RIGHT):
        camera.orientation = (TOWARD, vertical, RIGHT)


def face_front(viewer, layers=None) -> None:
    """Wind the front faces of every surface (or of `layers`) as the camera
    shows them: clockwise while the picture is upside down."""
    from napari.layers import Surface

    from .napari_private import front_face

    clockwise = upside_down(viewer)
    for layer in viewer.layers if layers is None else layers:
        if isinstance(layer, Surface):
            with contextlib.suppress(Exception):
                front_face(viewer, layer, clockwise)


def maximize(viewer) -> bool:
    """Open filling the screen. True if the request was made.

    napari exposes no public API for this, so it goes through the Qt window,
    and it is allowed to fail: headless runs and the tests have no window
    manager, and a viewer that cannot be maximized is still a usable viewer.

    Two quirks, both of which produce a window that *reports* itself
    maximized at 933x700:

    - Called before the event loop turns, `showMaximized` sets the window
      state without the window manager ever resizing anything. So it is also
      deferred with a zero-delay timer.
    - Once that state is set, a second `showMaximized` is a no-op, because Qt
      believes the window is already maximized. `showNormal` first clears the
      state so the next call actually takes effect.
    """
    window = getattr(getattr(viewer, "window", None), "_qt_window", None)
    if window is None:
        return False

    def _apply():
        window.showNormal()
        window.showMaximized()

    try:
        _apply()
        from qtpy.QtCore import QTimer

        QTimer.singleShot(0, _apply)
    except Exception:            # noqa: BLE001 - cosmetic, never fatal
        return False
    return True


def fit_view(viewer, margin: float = 0.02) -> None:
    """Fill the canvas with the data, without disturbing the orientation.

    `reset_view` resets the camera angles by default, which would undo
    `orient_anterior`.
    """
    try:
        viewer.reset_view(margin=margin, reset_camera_angle=False)
    except TypeError:                     # older napari: neither keyword
        viewer.reset_view()


def install_home_orientation(viewer, space, reflect_axis=None) -> bool:
    """Make the home button restore the anatomical view, not napari's.

    `ViewerModel.reset_view` sets the camera angles to (0, 0, 0) before
    fitting, which is a view down the ARRAY axes. Those are not the
    anatomical ones -- antero-posterior is z in FAFB and y in the
    hemibrain -- so "Reset view to original state" left the brain at an
    arbitrary attitude, and the orientation `orient_anterior` sets at
    load could not be got back without reopening the scene.

    `reflect_axis` is a callable returning the axis the scene is mirrored
    along, or None, read on every press: the mirror is toggled long after
    this is installed, and home has to face the scene as it is shown.

    Wrapped on the viewer INSTANCE rather than on `ViewerModel`: the class
    is shared by every viewer in the process, including the ones tests
    make. The viewer is a pydantic model and refuses unknown attributes,
    so the assignment goes through `object.__setattr__`; a bound method
    found in the instance dict still wins over the class, which is what
    makes the button -- verified -- go through this.

    Re-orienting only when napari reset the angles, so `fit_view`, which
    asks it not to, keeps preserving whatever the user is looking at. Home
    faces the scene turned by its angles (`orient_anterior`); in 2D it fits
    the view, as napari's own does, and a turned 2D view is fitted as it
    would be unturned (`turned.TurnedView`).
    """
    existing = viewer.__dict__.get("reset_view")
    if getattr(existing, "_lobemap_home", False):
        # A scene switch: same wrapper, new space.
        existing._lobemap_space = space
        existing._lobemap_reflect = reflect_axis
        return True

    original = type(viewer).reset_view.__get__(viewer)

    def reset(*args, **kwargs):
        original(*args, **kwargs)
        if kwargs.get("reset_camera_angle", True):
            axis = reset._lobemap_reflect
            orient_anterior(viewer, reset._lobemap_space,
                            reflect_axis=axis() if callable(axis) else axis)

    reset._lobemap_home = True
    reset._lobemap_space = space
    reset._lobemap_reflect = reflect_axis
    try:
        object.__setattr__(viewer, "reset_view", reset)
    except Exception:                       # noqa: BLE001 - cosmetic
        return False
    return True


def install_initial_fit(viewer, margin: float = 0.02) -> bool:
    """Keep refitting until the window settles, then stop at the first touch.

    Maximizing is asynchronous, and the canvas can still report a zero width
    while the layout resolves, so *when* the usable size appears varies from
    run to run. A single fit, or a one-shot on the first resize, therefore
    lands on the right size only sometimes: measured across two spaces, Grabe
    refitted correctly and FAFB never refitted at all, keeping the zoom it
    had at 900x700.

    Refitting on every resize until the user does something removes the
    timing from the question. After the first click, scroll or keypress the
    view is theirs and this stops touching it.

    Installed once per canvas. Every scene load calls this, and each call
    used to connect five more handlers, so they piled up one set per space
    switch; a canvas that is already watched is only fitted to the new scene.
    """
    canvas = getattr(getattr(viewer.window, "_qt_viewer", None), "canvas", None)
    events = getattr(canvas, "events", None)
    if events is None:
        fit_view(viewer, margin)
        return False
    if getattr(canvas, "_lobemap_fit", None) is not None:
        fit_view(viewer, margin)
        return True

    state = {"touched": False, "size": None}

    def _size():
        # napari's OWN canvas size, not the Qt widget's. `fit_to_view` divides
        # by `viewer.canvas.size`, and that model value is updated after the
        # resize callbacks run -- so the widget can already read 987x944 while
        # a fit still computes against 900x700. Watching the widget is how
        # FAFB kept its startup zoom while Grabe happened to refit correctly.
        got = getattr(getattr(viewer, "canvas", None), "size", None)
        return tuple(got) if got is not None else None

    def _refit(event=None):
        # Driven by draws, not only by resize: the resize arrives while
        # napari's own canvas size is still stale, so a fit done there is
        # computed against the old size and no second resize comes to correct
        # it -- which is how FAFB kept the zoom it had at 900x700. Refitting
        # whenever the size CHANGES converges on the settled size and costs
        # nothing once it stops moving.
        if state["touched"]:
            return
        now = _size()
        if now is None or min(now) <= 0 or now == state["size"]:
            return
        state["size"] = now
        fit_view(viewer, margin)

    def _release(event=None):
        state["touched"] = True

    fit_view(viewer, margin)
    connected = False
    for name in ("resize", "draw"):
        with contextlib.suppress(Exception):
            getattr(events, name).connect(_refit)
            connected = True
    for name in ("mouse_press", "mouse_wheel", "key_press"):
        with contextlib.suppress(Exception):
            getattr(events, name).connect(_release)
    canvas._lobemap_fit = state
    return connected


def capture_view(viewer) -> dict:
    """The viewer's own state that building a scene can move.

    A scene switch builds the new scene beside the open one, and building
    it moves things that belong to the viewer rather than to either scene:
    the slice axis and plane (`dims`), the camera, which layer is selected,
    and the window title. `restore_view` puts them back when that build
    fails, so the scene the user had is looked at exactly as before.
    """
    camera = viewer.scene.camera
    selection = viewer.layers.selection
    return {
        "order": tuple(viewer.dims.order),
        "point": tuple(viewer.dims.point),
        "center": tuple(camera.center),
        "zoom": float(camera.zoom),
        "angles": tuple(camera.angles),
        "perspective": float(camera.perspective),
        "selected": list(selection),
        "active": selection.active,
        "title": viewer.title,
    }


def restore_view(viewer, state: dict) -> None:
    """Put back what `capture_view` recorded, the dims before the camera.

    The order first, because the camera and the plane are read through
    it; the camera last, because a change of order moves it.
    """
    dims = viewer.dims
    if tuple(dims.order) != state["order"] and len(dims.order) == len(state["order"]):
        dims.order = state["order"]
    if len(dims.point) == len(state["point"]):
        dims.point = state["point"]
    camera = viewer.scene.camera
    camera.center = state["center"]
    camera.zoom = state["zoom"]
    camera.angles = state["angles"]
    camera.perspective = state["perspective"]
    kept = [layer for layer in state["selected"] if layer in viewer.layers]
    selection = viewer.layers.selection
    selection.clear()
    selection.update(kept)
    if state["active"] in kept:
        selection.active = state["active"]
    viewer.title = state["title"]


def center_sliders(viewer, lo, hi, step, keep=()) -> None:
    """Put every slider where napari puts it when the first layer it is given
    spans `lo` to `hi` in steps of `step`.

    That is the layer's middle step (`Dims._go_to_center_step`), put on the
    viewer's own slider grid, where napari snapped it once more layers had
    been added. The axes in `keep` stay where they are, on that grid.
    """
    lo, hi = np.asarray(lo, float), np.asarray(hi, float)
    step = np.broadcast_to(np.asarray(step, float), lo.shape)
    middle = lo + np.floor(np.floor((hi - lo) / step) / 2) * step
    dims = viewer.dims
    dims.current_step = tuple(
        now if axis in keep else round((m - r.start) / (r.step or 1))
        for axis, (now, m, r) in enumerate(zip(dims.current_step, middle, dims.range,
                                               strict=True)))


def mirror_center(layers, axis: int = MIRROR_AXIS) -> float:
    """Mid-point of `layers` along one axis, in world micrometers.

    Reflecting about zero would be a reflection too: it would also throw
    the scene to the far side of the origin, which for spaces published
    at x 192-853 um means off screen. So the mid-plane of the data is
    what it reflects about, and the scene stays where it was.

    Read once while nothing is mirrored, because `extent.world` already
    includes each layer's affine -- measuring it again with the mirror on
    would give back the same number only by luck, and any error in it
    doubles on the next toggle.
    """
    lo, hi = [], []
    for layer in layers:
        with contextlib.suppress(Exception):
            extent = layer.extent.world
            a, b = float(extent[0][axis]), float(extent[1][axis])
            if np.isfinite(a) and np.isfinite(b):
                lo.append(a)
                hi.append(b)
    if not lo:
        return 0.0
    return (min(lo) + max(hi)) / 2.0


def mirror_matrix(ndim: int, center: float, axis: int = MIRROR_AXIS):
    """The (ndim+1, ndim+1) world reflection x -> 2c - x."""
    m = np.eye(ndim + 1)
    m[axis, axis] = -1.0
    m[axis, -1] = 2.0 * center
    return m


def reflect_vertices(vertices, center: float, axis: int = MIRROR_AXIS) -> np.ndarray:
    """`vertices` reflected x -> 2c - x along `axis`, in float64.

    For the layers that reflect their own geometry rather than ride on
    `layer.affine` -- the surfaces and their stand-ins (`AtlasSurface._present`).
    Kept in float64, as napari works an affine: a mesh and the stand-in
    holding its corners then get the same reflected bounds to the bit, and
    those bounds meet an affine-reflected image's exactly. Rounded to float32
    instead, the male CNS's x range came out 1.5e-6 um under the stain's and
    its plane off the slider grid. napari still uploads float32.
    """
    v = np.array(vertices, dtype=np.float64, copy=True)
    v[:, axis] = 2.0 * float(center) - v[:, axis]
    return v


def apply_mirror(layers, on: bool, center: float,
                 axis: int = MIRROR_AXIS) -> None:
    """Reflect layers that carry no normals, or put them back.

    Set on `layer.affine`, which napari applies in WORLD space after the
    layer's own scale and translate. That is what lets one matrix serve
    contours in micrometers and images in voxels alike: each keeps the
    scale and translate that place it, and the reflection composes on top
    rather than replacing it.

    Not for the surfaces: napari loads the affine into the vispy node
    transform, and a determinant -1 transform there inverts their shading
    (`AtlasSurface._present`, which reflects their vertices instead).
    """
    for layer in layers:
        ndim = int(getattr(layer, "ndim", 3) or 3)
        with contextlib.suppress(Exception):
            layer.affine = (
                mirror_matrix(ndim, center, axis) if on else np.eye(ndim + 1)
            )


__all__ = [
    "MIRROR_AXIS",
    "RIGHT",
    "TOWARD",
    "UPRIGHT",
    "UPSIDE_DOWN",
    "apply_mirror",
    "capture_view",
    "center_sliders",
    "face_front",
    "fit_view",
    "install_home_orientation",
    "install_initial_fit",
    "keep_orientation",
    "maximize",
    "mirror_center",
    "mirror_matrix",
    "orient_anterior",
    "reflect_vertices",
    "restore_view",
    "show_upside_down",
    "upside_down",
]
