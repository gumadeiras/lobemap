"""A scene turned by three angles: the 3D camera, and the 2D section.

`SceneSession` owns one `TurnedView`; `rotation` has the arithmetic.

- **3D** turns the camera from Home (`view.orient_anterior`), and no layer
  changes. Free dragging still works; setting an angle puts the camera back
  at Home turned by the angles.
- **2D** shows the plane through the pivot -- the point at the center of the
  view, on the slider's plane -- perpendicular to the turned line of sight.
  napari's world is then the unturned world moved by a rigid turn `T`
  (`rotation.Turn`): every layer 2D draws is placed in it. Spin alone keeps
  the plane on the image grid, and `T` goes on the images and contours as a
  world affine after the mirror, so napari slices them as it always does.

At rest -- zero angles, no alignment -- none of this is installed, and the
scene is exactly as `main` shows it. Leaving rest records the view
(`_rest`), and coming back puts it back to the bit.

napari's sliders and its fit are read from the layers' extents, which a
turn would move: the image's box turned in plane is wider, so its slider
ranges grew, hidden sliders were clamped, and Home zoomed out. So while a
turn is shown napari is handed the unturned extent instead
(`napari_private.hook_extent`): the sliders keep their ranges, and Home
frames the section as it would unturned, about where the turn puts the
scene's middle.
"""

from __future__ import annotations

import contextlib

import numpy as np

from . import napari_private, rotation
from .rotation import ZERO, Turn, turn_matrix
from .view import mirror_matrix, orient_anterior


class TurnedView:
    """What one scene's angles move, and how to put it back."""

    def __init__(self, session) -> None:
        self.session = session
        self.viewer = session.viewer
        #: (spin, tilt, turn), degrees.
        self.angles = ZERO
        #: Whether 2D's base view is the anatomy rather than the image grid.
        self.aligned = False
        #: The 2D turn, once 2D has shown it; None at rest, and while the
        #: angles were changed in 3D, until 2D is entered again.
        self.turn: Turn | None = None
        #: The turn the layers carry now, or None.
        self._applied: Turn | None = None
        #: Each layer this has moved: its unturned (extent, augmented extent).
        self._unturned: dict = {}
        #: The view as it was at rest; see `_leave_rest`.
        self._rest: dict | None = None
        self._handlers: list[tuple] = []
        self._hooked = False
        #: The 2D focus left for 3D, and the 3D camera center left for 2D.
        self._left_2d = None
        self._left_3d = None
        #: (axis, point) the next 2D entry puts the slider on; see `take_plane`.
        self._plane = None
        rotation.register(self.viewer, self)

    # -- state ---------------------------------------------------------------

    @property
    def at_rest(self) -> bool:
        return self.angles == ZERO and not self.aligned

    @property
    def kind(self) -> str | None:
        """What a 2D view of these angles is: None at rest, else "spin".

        2D shows the spin; tilt and turn are 3D's.
        """
        return None if self.at_rest else "spin"

    @property
    def shown(self):
        """What the 2D view shows now: None, ("spin", degrees) or ("oblique", None)."""
        if self._applied is None:
            return None
        return ("spin", self.angles[0]) if self.kind == "spin" else ("oblique", None)

    def _two_d(self) -> bool:
        return self.viewer.dims.ndisplay == 2 and self.viewer.dims.ndim == 3

    def _space(self):
        return self.session.registry.spaces.get(self.session.space)

    def _q(self) -> np.ndarray:
        """The 2D turn's rotation for the current slice."""
        return turn_matrix((self.angles[0], 0.0, 0.0), self.viewer.dims.order)

    def _mirror(self) -> np.ndarray:
        s = self.session
        return mirror_matrix(3, s.mirror_center) if s.mirrored else np.eye(4)

    def _focus(self) -> np.ndarray:
        """The world point at the center of the 2D view, on the slider's plane."""
        dims = self.viewer.dims
        point = np.array(dims.point, float)
        shown = list(dims.order)[-2:]
        point[shown] = np.asarray(self.viewer.scene.camera.center, float)[-2:]
        return point

    # -- changing the angles -------------------------------------------------

    def set(self, angles, aligned: bool | None = None) -> None:
        """Turn the scene to `angles`, and the 2D base view to the anatomy or not."""
        angles = tuple(float(a) for a in angles)
        aligned = self.aligned if aligned is None else bool(aligned)
        was_rest = self.at_rest
        if was_rest and (angles != ZERO or aligned):
            self._leave_rest()
        self.angles, self.aligned = angles, aligned
        if self.at_rest:
            if not was_rest:
                self._come_to_rest()
            return
        if not self._two_d():
            # The 2D turn is pivoted afresh about where 3D looks, on entry.
            self.turn = None
            self._hook()
            self._orient()
            return
        self._turn_2d(self._focus())
        # The next entry into 3D faces Home turned by these angles.
        self.session.oriented = False

    def _orient(self) -> None:
        space = self._space()
        if space is not None:
            self.session.oriented = orient_anterior(
                self.viewer, space, reflect_axis=self.session.reflect_axis(),
                angles=self.angles)

    def _turn_2d(self, focus) -> None:
        """Show the 2D turn of the current angles, keeping the specimen at `focus`."""
        turn = Turn.about(self._q(), focus, self.turn)
        if self.kind == "spin":
            turn = self._on_plane(turn)
        self.turn = turn
        self._apply()

    def _on_plane(self, turn: Turn) -> Turn:
        """A spin keeps every point's depth: the pivot goes on the slider's grid.

        Then `T(x)[axis] = x[axis]`, so the slider steps through the planes
        it steps through unturned, and moving it there moves the plane.
        """
        dims = self.viewer.dims
        axis = int(dims.order[0])
        start, _stop, step = dims.range[axis]
        depth = start + round((float(turn.pivot[axis]) - start) / step) * step
        pivot, focus = turn.pivot.copy(), turn.focus.copy()
        pivot[axis] = focus[axis] = depth
        if float(dims.point[axis]) != depth:
            dims.set_point(axis, depth)
        return Turn(turn.q, pivot, focus)

    # -- placing the layers ---------------------------------------------------

    def _layers(self) -> list:
        return self.session.affine_layers()

    def _apply(self) -> None:
        """Place every layer 2D draws by the current turn."""
        turn = self.turn
        if turn is None or not self._two_d():
            return
        matrix = turn.affine() @ self._mirror()
        q2 = turn.q[np.ix_(list(self.viewer.dims.displayed), list(self.viewer.dims.displayed))]
        layers = self._layers()
        for layer in layers:
            self._keep_unturned(layer)
        # Before anything moves, so napari never sees a turned extent.
        self._applied = turn
        self._hook()
        for layer in layers:
            self._set_affine(layer, matrix, q2)
        self._redraw()

    def _keep_unturned(self, layer) -> None:
        """Record napari's own extent of `layer`, to the bit: what the
        sliders and the fit read while it is turned. And its pyramid level
        and region, which rest gives back as they were."""
        if layer not in self._unturned:
            self._unturned[layer] = (
                layer.extent, napari_private.augmented_extent(layer),
                napari_private.level_of(layer))

    def _set_affine(self, layer, matrix, q2=None, sliced: bool = True,
                    level=None) -> None:
        """Put `matrix` on `layer`; an image picks its level as unturned (`q2`).

        An image is sliced once, at the level and region napari's draw picks
        for the new transform -- or at `level`, as `napari_private.level_of`
        gives it -- rather than at the old ones and again on the next draw.
        """
        image = layer.metadata.get("lobemap", {}).get("kind") in ("image", "labels")
        if np.array_equal(np.asarray(layer.affine.affine_matrix), matrix):
            if image:
                napari_private.level_as_unturned(layer, q2)
            return
        # A contour layer holds no shapes: its slice visuals ride on the
        # layer's node transform, which the affine sets, and are cut by
        # `ContourOverlay` itself.
        with napari_private.shown_unsliced(layer):
            layer.affine = matrix
            if image:
                napari_private.level_as_unturned(layer, q2)
                if level is not None:
                    napari_private.put_level(layer, level)
                elif sliced and self._two_d():
                    napari_private.update_draw(self.viewer, layer)
        if sliced and image:
            napari_private.slice_now(self.viewer, layer)

    def adopt(self, layer) -> None:
        """Place a layer built while turned -- a part realized -- as the rest are."""
        turn = self._applied
        if turn is None:
            return
        shown = list(self.viewer.dims.displayed)
        self._keep_unturned(layer)
        napari_private.refresh_extent(self.viewer)
        self._set_affine(layer, turn.affine() @ self._mirror(), turn.q[np.ix_(shown, shown)])

    def _unapply(self, sliced: bool = True, rest: bool = False) -> None:
        """Give every moved layer back its unturned transform.

        With `sliced` false the layers are not sliced here: napari is about to
        slice them all, on a change of mode. At `rest` each image also gets
        back the level and region it had.
        """
        if self._applied is None and not self._unturned:
            return
        matrix = self._mirror()
        for layer, kept in list(self._unturned.items()):
            with contextlib.suppress(Exception):
                self._set_affine(layer, matrix, None, sliced=sliced,
                                 level=kept[2] if rest else None)
        self._unturned = {}
        self._applied = None

    def _redraw(self) -> None:
        space = self._space()
        if space is not None:
            from .axes import apply_axis_mode

            apply_axis_mode(self.viewer, space, mirror_axis=self.session.reflect_axis())
        for overlay in self.session.contours.values():
            with contextlib.suppress(Exception):
                overlay.refresh()

    def around(self, change) -> None:
        """Run `change` -- a new mirror or slice axis -- on the unturned scene,
        then turn it again about the same specimen point."""
        if self._applied is None:
            change()
            if self.turn is not None and not self._two_d():
                self._repivot()
            return
        before = self.session.reflect_axis(), self.session.mirror_center
        focus = self._focus()
        specimen = self.turn.inverse(focus)
        self._unapply()
        change()
        if before != (self.session.reflect_axis(), self.session.mirror_center):
            specimen = self._reflected(specimen, before)
        self.turn = Turn(self._q(), specimen, focus)
        if self.kind == "spin":
            self.turn = self._on_plane(self.turn)
        axis = int(self.viewer.dims.order[0])
        if float(self.viewer.dims.point[axis]) != float(self.turn.focus[axis]):
            self.viewer.dims.set_point(axis, float(self.turn.focus[axis]))
        self._apply()

    def _reflected(self, point, before) -> np.ndarray:
        """`point` of the world mirrored as `before` was, in the world as it is."""
        from .view import MIRROR_AXIS

        out = np.array(point, float)
        axis, center = before
        if axis is not None:
            out[MIRROR_AXIS] = 2.0 * center - out[MIRROR_AXIS]
        if self.session.mirrored:
            out[MIRROR_AXIS] = 2.0 * self.session.mirror_center - out[MIRROR_AXIS]
        return out

    def _repivot(self) -> None:
        """A kept 2D turn whose world changed in 3D: pivot it again on entry."""
        self.turn = None
        self._hook()

    # -- the sliders and the fit ----------------------------------------------

    def _hook(self) -> None:
        """Hand napari the unturned extent while a turn exists, or its own."""
        want = self.turn is not None
        if want != self._hooked:
            self._hooked = want
            napari_private.hook_extent(
                self.viewer, *((self._ranges, self._fit) if want else (None, None)))
        elif want:
            napari_private.refresh_extent(self.viewer)

    def _extents(self, augmented: bool) -> list:
        """Every layer's extent as it is unturned: what napari would union."""
        out = []
        for layer in self.viewer.layers:
            kept = self._unturned.get(layer)
            if kept is not None:
                out.append(kept[1 if augmented else 0])
            else:
                out.append(napari_private.augmented_extent(layer) if augmented
                           else layer.extent)
        return out

    def _union(self, augmented: bool, world) -> np.ndarray:
        """The extent of every layer as it is unturned, as napari unions it.

        `world` is napari's own, for a viewer with no layer.
        """
        extents = self._extents(augmented)
        if not extents:
            return world
        lo = [np.asarray(e.world[0], float) for e in extents]
        hi = [np.asarray(e.world[1], float) for e in extents]
        with warnings_quiet():
            low, high = np.nanmin(lo, axis=0), np.nanmax(hi, axis=0)
        return np.vstack([np.nan_to_num(low, nan=-0.5), np.nan_to_num(high, nan=511.5)])

    def _ranges(self, world, step):
        """The slider ranges and steps: the unturned ones."""
        extents = self._extents(False) if self._unturned else []
        if not extents:
            return world, step
        with warnings_quiet():
            step = np.nanmin([np.asarray(e.step, float) for e in extents], axis=0)
        return self._union(False, world), step

    def _fit(self, world) -> np.ndarray:
        """The extent Home fits in 2D: the unturned one, about the turned middle."""
        if self._applied is None or not self._two_d():
            return world
        box = self._union(True, world)
        middle = box.mean(axis=0)
        return box + (self._applied(middle) - middle)

    # -- rest ------------------------------------------------------------------

    def _leave_rest(self) -> None:
        """Record the view as it is at rest, and start following the mode."""
        viewer = self.viewer
        camera = viewer.scene.camera
        self._rest = {
            "point": tuple(viewer.dims.point),
            "ndisplay": viewer.dims.ndisplay,
            "axis": self.session.slice_axis,
            "center": tuple(camera.center),
            "zoom": float(camera.zoom),
            "angles": tuple(camera.angles),
            "oriented": self.session.oriented,
        }
        events = viewer.dims.events.ndisplay
        events.connect(self._before_mode, position="first")
        events.connect(self._after_mode)
        self._handlers = [(events, self._before_mode), (events, self._after_mode)]

    def _come_to_rest(self) -> None:
        """Put back the view `_leave_rest` recorded, and remove everything."""
        self._unapply(rest=self._two_d())
        self.turn = None
        self._disconnect()
        if self._hooked:
            self._hooked = False
            napari_private.hook_extent(self.viewer)
        rest, self._rest = self._rest, None
        viewer, camera = self.viewer, self.viewer.scene.camera
        if rest is None:
            return
        viewer.dims.point = rest["point"]
        two_d = viewer.dims.ndisplay == 2
        if two_d and rest["axis"] != self.session.slice_axis:
            # As `set_slice_axis` leaves it, which ran while turned.
            self.session.populate_plane()
            from .view import fit_view

            fit_view(viewer)
        elif viewer.dims.ndisplay == rest["ndisplay"]:
            camera.center = rest["center"]
            camera.zoom = rest["zoom"]
            camera.angles = rest["angles"]
            self.session.oriented = rest["oriented"]
        elif not two_d:
            if rest["oriented"]:
                camera.angles = rest["angles"]
                self.session.oriented = True
            else:
                self._orient()
        if not two_d:
            # napari will put back the plane 2D left on, which was turned.
            axis = self.session.slice_axis
            self._plane = (axis, float(rest["point"][axis]))
        self._redraw()

    def take_plane(self):
        """(axis, point) for the slider on entering 2D, once; or None."""
        plane, self._plane = self._plane, None
        return plane

    # -- changes of mode -------------------------------------------------------

    def _before_mode(self, event=None) -> None:
        """Before napari changes the camera or slices for the new mode."""
        dims = self.viewer.dims
        if dims.ndisplay == 3:
            # Leaving 2D: the camera is still 2D's, the order still 2D's.
            point = np.array(dims.point, float)
            shown = list(dims.order)[-2:]
            point[shown] = np.asarray(self.viewer.scene.camera.center, float)[-2:]
            self._left_2d = point
            # 3D shows the layers unturned; napari slices them right after.
            self._unapply(sliced=False)
        else:
            self._left_3d = np.array(self.viewer.scene.camera.center, float)

    def _after_mode(self, event=None) -> None:
        """After napari and the display mode have set up the new mode."""
        dims, camera = self.viewer.dims, self.viewer.scene.camera
        if dims.ndisplay == 3:
            if self.turn is not None and self._left_2d is not None:
                center = self.turn.inverse(self._left_2d)
                camera.center = tuple(center[list(dims.displayed)])
            self._left_2d = None
            self._hook()
            return
        if dims.ndim != 3:
            return
        left, self._left_3d = self._left_3d, None
        shown = list(dims.displayed)
        axis = int(dims.order[0])
        if self.turn is None:
            # Pivoted on the point 3D was centered on.
            focus = np.array(dims.point, float) if left is None else left
            self.turn = Turn(self._q(), focus.copy(), focus.copy())
            if self.kind == "spin":
                self.turn = self._on_plane(self.turn)
            if float(dims.point[axis]) != float(self.turn.focus[axis]):
                dims.set_point(axis, float(self.turn.focus[axis]))
            center = self.turn.focus
        else:
            center = self.turn(left) if left is not None else self._focus()
        camera.center = tuple(np.asarray(center, float)[shown])
        self._apply()

    def _disconnect(self) -> None:
        for event, handler in self._handlers:
            with contextlib.suppress(Exception):
                event.disconnect(handler)
        self._handlers = []

    def close(self) -> None:
        """The scene is going: leave nothing of the turn behind."""
        self._disconnect()
        for layer in list(self._unturned):
            with contextlib.suppress(Exception):
                napari_private.level_as_unturned(layer, None)
        self._unturned, self._applied = {}, None
        if self._hooked:
            self._hooked = False
            with contextlib.suppress(Exception):
                napari_private.hook_extent(self.viewer)
        rotation.unregister(self.viewer, self)


@contextlib.contextmanager
def warnings_quiet():
    """nanmin and nanmax warn on an axis no layer has a number for."""
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        yield


__all__ = ["TurnedView"]
