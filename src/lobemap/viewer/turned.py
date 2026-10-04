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
  Tilt or turn cut across the grid: each image is handed its data resampled
  in the turned world (`resample.TurnedImage`), which napari slices along
  its axes, and the contours cut the meshes in the turned frame
  (`sections.PlaneFrame`). The slider then steps along the turned line of
  sight, over the scene's extent along it.
- **Aligned**, 2D's base view is not the image grid but the anatomical frame
  nearest it -- the anatomy 3D's Home is turned onto -- so at zero angles the
  section is the brain's own frontal, horizontal or sagittal plane, not one
  15 to 32 degrees off it. It is a fixed turn composed with the angles, and
  takes the path across the grid.

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

from . import images, napari_private, rotation
from .rotation import ZERO, Turn, turn_matrix
from .sections import PlaneFrame
from .view import fit_view, mirror_matrix, orient_anterior


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
        #: Each layer this has moved: its unturned (extent, augmented extent,
        #: level and region).
        self._unturned: dict = {}
        #: What the layers show: None, "spin" or "oblique".
        self._applied_kind = None
        #: Each image shown resampled: its own (levels, translate, scale), and
        #: the `resample.TurnedImage` it shows.
        self._virtual: dict = {}
        #: (turn, low, high): the scene's extent along the turned line of
        #: sight; see `_depth_range`.
        self._depth = None
        #: The view as it was at rest; see `_leave_rest`.
        self._rest: dict | None = None
        self._handlers: list[tuple] = []
        self._hooked = False
        #: The 3D camera's center, as 3D was left for 2D.
        self._left_3d = None
        #: The display mode the last slice was for; see `_before_slice`.
        self._mode = None
        #: (axis, point) the next 2D entry puts the slider on; see `take_plane`.
        self._plane = None
        rotation.register(self.viewer, self)

    # -- state ---------------------------------------------------------------

    @property
    def at_rest(self) -> bool:
        return self.angles == ZERO and not self.aligned

    @property
    def kind(self) -> str | None:
        """What a 2D view of these angles is: None, "spin" or "oblique".

        Spin alone keeps the plane on the image grid; tilt, turn or the
        alignment cut across it.
        """
        if self.at_rest:
            return None
        _spin, tilt, turn = self.angles
        return "oblique" if tilt or turn or self._anatomy() is not None else "spin"

    @property
    def shown(self):
        """What the 2D view shows now: None, ("spin", degrees) or ("oblique", None)."""
        if self._applied is None:
            return None
        if self._applied_kind == "spin":
            return ("spin", self.angles[0])
        return ("oblique", None)

    def _two_d(self) -> bool:
        return self.viewer.dims.ndisplay == 2 and self.viewer.dims.ndim == 3

    def _space(self):
        return self.session.registry.spaces.get(self.session.space)

    def _q(self) -> np.ndarray:
        """The 2D turn's rotation for the current slice."""
        return turn_matrix(self.angles, self.viewer.dims.order, self._anatomy())

    def _anatomy(self):
        """With the alignment, the anatomical directions A, D and R as columns,
        reflected with the scene; else None, as for a space with no anatomy."""
        if not self.aligned:
            return None
        from ..core.model import anatomical_axes
        from .view import MIRROR_AXIS

        space = self._space()
        frame = anatomical_axes(space) if space is not None else None
        if frame is None:
            return None
        anatomy = np.column_stack([frame["A"], frame["D"], frame["R"]]).astype(float)
        if self.session.mirrored:
            anatomy[MIRROR_AXIS] *= -1.0
        return anatomy

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
        same_angles, was_aligned = angles == self.angles, self.aligned
        was_rest = self.at_rest
        if was_rest and (angles != ZERO or aligned):
            self._leave_rest()
        self.angles, self.aligned = angles, aligned
        if self.at_rest:
            if not was_rest:
                self._come_to_rest()
            elif not self._two_d():
                # At rest already, as after a drag: 3D faces the front view
                # again, as any setting of the angles does.
                self._orient()
            return
        if not self._two_d():
            # The 2D turn is pivoted afresh about where 3D looks, on entry.
            self.turn = None
            self._hook()
            if not (same_angles and aligned != was_aligned):
                # 3D's base view is Home, whatever 2D's is.
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
        self.turn = Turn.about(self._q(), focus, self.turn)
        self._apply()

    def _on_plane(self, turn: Turn) -> Turn:
        """A spin keeps every point's depth: the pivot goes on the slider's grid.

        Then `T(x)[axis] = x[axis]`, so the slider steps through the planes
        it steps through unturned. The grid is the unturned one, which the
        sliders have while spun (`_ranges`).
        """
        dims = self.viewer.dims
        axis = int(dims.order[0])
        start, _stop, step = dims.range[axis]
        depth = start + round((float(turn.pivot[axis]) - start) / step) * step
        pivot, focus = turn.pivot.copy(), turn.focus.copy()
        pivot[axis] = focus[axis] = depth
        return Turn(turn.q, pivot, focus)

    # -- placing the layers ---------------------------------------------------

    def _layers(self) -> list:
        return self.session.affine_layers()

    def _apply(self) -> None:
        """Place every layer 2D draws by the current turn."""
        turn = self.turn
        if turn is None or not self._two_d():
            return
        kind = self.kind
        if self._applied_kind not in (None, kind):
            self._unapply()
        layers = self._layers()
        for layer in layers:
            self._keep_unturned(layer)
        # Before anything moves, so napari never sees a turned extent.
        self._applied, self._applied_kind = turn, kind
        self._hook()
        if kind == "spin":
            self.turn = self._applied = turn = self._on_plane(turn)
        self._on_pivot_plane()
        if kind == "spin":
            matrix = turn.affine() @ self._mirror()
            shown = list(self.viewer.dims.displayed)
            for layer in layers:
                self._set_affine(layer, matrix, turn.q[np.ix_(shown, shown)])
        else:
            self._place_oblique(turn)
        self._redraw()

    def _on_pivot_plane(self) -> None:
        """Put the slider on the plane through the pivot.

        A new range along the turned line of sight moves the slider: napari's
        slider keeps its index, not its position. The range is on a grid
        through the pivot's plane, so the plane is one of its positions.
        """
        dims = self.viewer.dims
        axis = int(dims.order[0])
        depth = float(self.turn.focus[axis])
        if float(dims.point[axis]) != depth:
            dims.set_point(axis, depth)

    def _frame(self, turn: Turn) -> PlaneFrame:
        """The contours' frame: the turn, in the layer's data before the mirror."""
        mirror = self._mirror()
        return PlaneFrame(np.linalg.inv(mirror) @ turn.affine() @ mirror)

    def _place_oblique(self, turn: Turn) -> None:
        """Cut the contours in the turned frame; hand each image its turned data."""
        frame = self._frame(turn)
        for overlay in self.session.contours.values():
            overlay.set_frame(frame)
        mirror = self._mirror()
        dims = self.viewer.dims
        axis = int(dims.order[0])
        # The slice position in the layers' data before the mirror, which
        # is the contours' `slice_position`.
        position = float((np.linalg.inv(mirror) @ np.r_[np.asarray(dims.point, float),
                                                         1.0])[axis])
        for layer in self.session.images:
            self._virtualize(layer, turn, mirror, position)

    def _virtualize(self, layer, turn: Turn, mirror, position: float) -> None:
        from .resample import TurnedImage

        held = self._virtual.get(layer)
        if held is None:
            sources = list(layer.data) if layer.multiscale else [layer.data]
            held = (sources, np.array(layer.translate, float), np.array(layer.scale, float))
            images.hold(layer, sources)
        sources, translate, scale = held[:3]
        labels = layer.metadata.get("lobemap", {}).get("kind") == "labels"
        dims = self.viewer.dims
        step = float(dims.range[int(dims.order[0])].step)
        image = TurnedImage(sources, layer.multiscale, scale, translate, mirror, turn,
                            dims.order, position, step, labels)
        self._virtual[layer] = (sources, translate, scale, image)
        with napari_private.shown_unsliced(layer):
            layer.data = image.data
            layer.translate = image.translate
            layer.scale = image.scale
            napari_private.update_draw(self.viewer, layer)
        napari_private.slice_now(self.viewer, layer)
        if len(held) > 3:
            held[3].close()

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

    def adopt(self, overlay) -> None:
        """Place the contours of a part realized while turned as the rest are."""
        turn = self._applied
        if turn is None:
            if self.turn is not None and self.kind == "oblique":
                # In 3D: its frame for the next entry into 2D.
                overlay.set_frame(self._frame(self.turn))
            return
        if self._applied_kind == "oblique":
            overlay.set_frame(self._frame(turn))
            return
        shown = list(self.viewer.dims.displayed)
        self._keep_unturned(overlay.layer)
        napari_private.refresh_extent(self.viewer)
        self._set_affine(overlay.layer, turn.affine() @ self._mirror(),
                         turn.q[np.ix_(shown, shown)])

    def _unapply(self, sliced: bool = True, rest: bool = False, frames: bool = True) -> None:
        """Give every moved layer back its own data and transform.

        With `sliced` false the layers are not sliced here: napari is about to
        slice them all, on a change of mode. At `rest` each image also gets
        back the level and region it had. With `frames` false the contours
        keep their turned frame: they draw nothing in 3D, and 2D comes back
        to the same turn.
        """
        if frames:
            for overlay in self.session.contours.values():
                with contextlib.suppress(Exception):
                    overlay.set_frame(None)
        if self._applied is None and not self._unturned and not self._virtual:
            return
        matrix = self._mirror()
        for layer, (sources, translate, scale, image) in list(self._virtual.items()):
            images.release(layer)
            image.close()
            kept = self._unturned.get(layer)
            with contextlib.suppress(Exception), napari_private.shown_unsliced(layer):
                layer.data = sources if layer.multiscale else sources[0]
                layer.translate = translate
                layer.scale = scale
                if rest and kept is not None:
                    napari_private.put_level(layer, kept[2])
                elif sliced and self._two_d():
                    napari_private.update_draw(self.viewer, layer)
            if sliced:
                with contextlib.suppress(Exception):
                    napari_private.slice_now(self.viewer, layer)
        self._virtual = {}
        for layer, kept in list(self._unturned.items()):
            with contextlib.suppress(Exception):
                self._set_affine(layer, matrix, None, sliced=sliced,
                                 level=kept[2] if rest else None)
        self._unturned = {}
        self._applied = self._applied_kind = None

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
        self._hook()
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
        """The slider ranges and steps: the unturned ones, and across the grid
        the scene's extent along the turned line of sight."""
        extents = self._extents(False) if self._unturned else []
        if extents:
            with warnings_quiet():
                step = np.nanmin([np.asarray(e.step, float) for e in extents], axis=0)
            world = self._union(False, world)
        turn = self.turn
        if turn is None or self.kind != "oblique" or not len(self.viewer.layers):
            return world, step
        axis = self.session.slice_axis
        low, high = self._depth_range(turn)
        anchor, size = float(turn.focus[axis]), float(np.asarray(step)[axis])
        # On a grid through the pivot's plane, so the plane it opens on is
        # one of the slider's.
        world = np.array(world, float, copy=True)
        world[0, axis] = anchor - np.ceil((anchor - min(low, anchor)) / size - 1e-9) * size
        world[1, axis] = anchor + np.ceil((max(high, anchor) - anchor) / size - 1e-9) * size
        return world, step

    def _depth_range(self, turn: Turn) -> tuple[float, float]:
        """The scene's extent along the turned line of sight, in the turned world.

        Every mesh by its vertices, built or not -- a part not read yet by
        its corners -- and every image by its box: the brain's extent, not
        the box around a box.
        """
        if self._depth is not None and self._depth[0] is turn:
            return self._depth[1], self._depth[2]
        s = self.session
        direction, offset = turn.depth(s.slice_axis)
        mirror = self._mirror()
        # Through the mirror, as the meshes are drawn.
        on_mesh = mirror[:3, :3].T @ direction
        mesh_offset = offset + float(direction @ mirror[:3, 3])
        low, high = np.inf, -np.inf

        def take(values, shift) -> None:
            nonlocal low, high
            if len(values):
                low, high = min(low, float(values.min()) + shift), max(
                    high, float(values.max()) + shift)

        clouds = [surface.meshset.vertices for surface in s.surfaces.values()]
        for name in s.pending:
            vertices = s.deferred.vertices(name) if s.deferred is not None else None
            if vertices is None and s.deferred is not None:
                bounds = s.deferred.bounds(name)
                if bounds is not None:
                    vertices = np.array([np.where(bits, bounds[1], bounds[0])
                                         for bits in np.ndindex(2, 2, 2)], float)
            if vertices is not None:
                clouds.append(vertices)
        for vertices in clouds:
            take(np.asarray(vertices) @ on_mesh.astype(np.asarray(vertices).dtype),
                 mesh_offset)
        for layer in s.images:
            kept = self._unturned.get(layer)
            box = np.asarray((kept[0] if kept is not None else layer.extent).world, float)
            corners = np.array([np.where(bits, box[1], box[0])
                                for bits in np.ndindex(2, 2, 2)])
            take(corners @ direction, offset)
        if not np.isfinite(low):
            low = high = float(turn.focus[s.slice_axis])
        self._depth = (turn, low, high)
        return low, high

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
            #: Changes of mode since: napari fits the view on each.
            "trips": 0,
        }
        self._mode = viewer.dims.ndisplay
        napari_private.before_slicing(viewer, self._before_slice)
        events = viewer.dims.events.ndisplay
        events.connect(self._after_mode)
        self._handlers = [(events, self._after_mode)]

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
            fit_view(viewer)
        elif not rest["trips"]:
            camera.center = rest["center"]
            camera.zoom = rest["zoom"]
        elif two_d:
            # napari fitted 2D as it was entered, about the turned scene's
            # middle; unturned it fits it about the middle.
            viewer.fit_to_view()
        if two_d:
            # The 3D camera's angles, which napari keeps through 2D.
            camera.angles = rest["angles"]
            self.session.oriented = rest["oriented"]
        else:
            # The front view, whatever a drag had made of it. A change of
            # mode fitted the turned view as 3D was entered; the same trip
            # unturned fits the front view.
            self._orient()
            if rest["trips"]:
                fit_view(viewer)
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

    def _before_slice(self) -> None:
        """Before napari slices anything for a new mode, or moves the camera.

        napari runs its own handlers of a change of mode before any other,
        and slices first: an image left resampled would be read whole for
        3D. So this runs before every slice while a turn is installed, and
        acts once per change of mode.
        """
        dims = self.viewer.dims
        if dims.ndisplay == self._mode:
            return
        self._mode = dims.ndisplay
        if self._rest is not None:
            self._rest["trips"] += 1
        if dims.ndisplay == 3:
            # 3D shows the layers unturned; napari slices them right after.
            self._unapply(sliced=False, frames=False)
        else:
            self._left_3d = np.array(self.viewer.scene.camera.center, float)

    def _after_mode(self, event=None) -> None:
        """After napari and the display mode have set up the new mode.

        The camera is napari's: once every handler of a change of mode has
        run, napari announces the new axis order and fits the view to it,
        and a turned 2D view is fitted as unturned (`_fit`). The 2D view
        keeps its turn and its plane; a turn the angles changed in 3D is
        pivoted on the point 3D was looking at, and the plane goes through it.
        """
        dims = self.viewer.dims
        if dims.ndisplay == 3:
            self._hook()
            return
        if dims.ndim != 3:
            return
        left, self._left_3d = self._left_3d, None
        axis = int(dims.order[0])
        if self.turn is None:
            focus = np.array(dims.point, float) if left is None else left
            self.turn = Turn(self._q(), focus.copy(), focus.copy())
            self._hook()
            if float(dims.point[axis]) != float(self.turn.focus[axis]):
                dims.set_point(axis, float(self.turn.focus[axis]))
        self._apply()

    def _disconnect(self) -> None:
        for event, handler in self._handlers:
            with contextlib.suppress(Exception):
                event.disconnect(handler)
        self._handlers = []
        with contextlib.suppress(Exception):
            napari_private.stop_before_slicing(self.viewer, self._before_slice)

    def close(self) -> None:
        """The scene is going: leave nothing of the turn behind."""
        self._disconnect()
        for layer in list(self._unturned):
            with contextlib.suppress(Exception):
                napari_private.level_as_unturned(layer, None)
        for layer, held in list(self._virtual.items()):
            images.release(layer)
            held[3].close()
        self._unturned, self._virtual, self._applied = {}, {}, None
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
