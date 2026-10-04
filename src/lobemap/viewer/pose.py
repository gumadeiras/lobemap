"""How a loaded scene is posed: turned, mirrored, flipped, and sliced along an axis.

`SceneSession` holds what a space put in the viewer; this is how that scene
is looked at, which the View dock sets. Split out of `scene` along that line:
nothing here adds or removes a layer, and nothing there turns, mirrors or
flips one. `ScenePose` is a mixin of `SceneSession`, and reads the layers,
the registry and the turn (`turned.TurnedView`) the session holds.
"""

from __future__ import annotations

import contextlib

from .axes import apply_axis_mode
from .slicing import order_for
from .view import (
    MIRROR_AXIS,
    apply_mirror,
    fit_view,
    mirror_center,
    show_upside_down,
    upside_down,
)


class ScenePose:
    """The turn, the mirror, the flip and the slice axis of one session."""

    # -- turning the view -------------------------------------------------

    @property
    def rotation(self) -> tuple[float, float, float]:
        """(spin, tilt, turn) in degrees; see `rotation`."""
        return tuple(self.turned.angles)

    def set_rotation(self, spin: float, tilt: float, turn: float) -> None:
        """Turn the scene: in 3D the camera from Home, in 2D the section.

        Spin turns about the line of sight, counterclockwise on screen;
        tilt about the screen's horizontal, top toward the viewer; turn
        about its vertical, front toward the viewer's right. Each is
        relative to the mode's base view. All three zero, without the
        alignment, gives back the view exactly as it was at zero.
        """
        self.turned.set((spin, tilt, turn))

    @property
    def aligned(self) -> bool:
        """Whether 2D's base view is the anatomy rather than the image grid."""
        return self.turned.aligned

    def set_aligned(self, on: bool) -> None:
        """Cut 2D along the brain's own planes rather than the image grid's.

        The 2D base view becomes the anatomical frame nearest the grid's,
        the one 3D's Home uses for that direction; the angles turn from it.
        """
        self.turned.set(self.turned.angles, bool(on))

    def home(self) -> None:
        """Home: in 3D the anatomy turned by the angles, in 2D napari's fit."""
        self.viewer.reset_view()

    @property
    def flipped(self) -> bool:
        """Whether the picture is upside down (`set_flip`)."""
        return upside_down(self.viewer)

    def set_flip(self, on: bool) -> None:
        """Turn the picture upside down after the turn and the mirror, or back,
        by the viewer's camera (`view.show_upside_down`): no layer moves."""
        show_upside_down(self.viewer, on)

    # -- the mirror -------------------------------------------------------

    def reflect_axis(self) -> int | None:
        """The array axis the scene is shown mirrored along, or None."""
        return MIRROR_AXIS if self.mirrored else None

    @property
    def mirror_center(self) -> float:
        """The plane the mirror reflects about: the mid-plane of the scene.

        Every part counts, built or not, so the plane is the same whichever
        tabs have been opened: a part not built yet lies within the layers
        there are, or has a stand-in that spans it (`deferred`). It is also
        the mid-plane of the sliders, which span the same layers, so the
        reflected slider grid is the same grid and the plane stays on it.
        Measured while nothing is mirrored, because `extent.world` includes
        the reflection, and held while the mirror is on.
        """
        if self.mirrored and self._mirror_center is not None:
            return self._mirror_center
        return mirror_center(self.all_layers())

    def set_mirror(self, on: bool) -> None:
        """Show the space reflected, or stop.

        The triads are re-derived rather than left alone: a mirror
        reverses handedness, so an unmirrored anatomical triad over
        mirrored data would name the wrong side, which is the single
        error this project has had to correct most often.

        A turned view is turned again about the same specimen point.
        """
        self.turned.around(lambda: self._set_mirror(on))

    def _set_mirror(self, on: bool) -> None:
        if on and not self.mirrored:
            self._mirror_center = self.mirror_center
        self.mirrored = bool(on)
        # Two routes on purpose: the surfaces reflect their own vertices, so
        # their node transform stays proper and they are lit from outside,
        # and so do their stand-ins, to the bit; the contours and images
        # ride on `affine`.
        for surface in self.surfaces.values():
            with contextlib.suppress(Exception):
                surface.set_mirror(self.reflect_axis(), self.mirror_center)
        if self.deferred is not None:
            self.deferred.set_mirror(self.reflect_axis(), self.mirror_center)
        apply_mirror(self.affine_layers(), self.mirrored, self.mirror_center)
        space = self.registry.spaces.get(self.space)
        if space is not None:
            apply_axis_mode(self.viewer, space, mirror_axis=self.reflect_axis())
        for overlay in self.contours.values():
            with contextlib.suppress(Exception):
                overlay.refresh()

    # -- the slice axis ---------------------------------------------------

    def set_slice_axis(self, axis: int) -> None:
        """Step 2D along another array axis; image and contours follow.

        Remembered for the session, so 3D and back keeps it. The contours
        read the axis from `dims.order` and redraw when it changes. The view
        is refitted, since the camera was framing the other plane's axes.
        A turned view is turned the same way from the new axis's base view.
        """
        self.slice_axis = int(axis)
        if self.viewer.dims.ndisplay == 3:
            return

        def _change() -> None:
            order = order_for(self.slice_axis)
            # Not a reason to stop: napari's roll button sets the order
            # first, and the new plane still has to be found.
            if tuple(self.viewer.dims.order) != order:
                self.viewer.dims.order = order
            self.populate_plane()

        self.turned.around(_change)
        space = self.registry.spaces.get(self.space)
        if space is not None:
            apply_axis_mode(self.viewer, space, mirror_axis=self.reflect_axis())
        fit_view(self.viewer)


__all__ = ["ScenePose"]
