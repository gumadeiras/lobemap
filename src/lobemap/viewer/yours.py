"""Your own data in a scene: images placed by hand, and neurons.

`SceneSession` holds what a space put in the viewer; this is what you add
to it, and is a mixin of it, as `pose` is. Your data is drawn as the
brain is: in the scene's stack (`scene.scene_ranks`), under its mirror and
its turn. So each change goes through the turned view (`turned.moved`),
which puts back what a turn placed, runs the change on the unturned scene,
and turns the scene again, yours with it.

Your images are `placed.PlacedImage`s: their slice layers join the scene's
images, which the mirror and a turn move as they move the brain's, and
their 3D layers carry the mirror themselves. Your neurons are a part of
the scene like an atlas, under a key no part of the space has: an
`AtlasSurface` and its contours, built with the mirror as it is.

Your data is left out of the extent napari reads its slider ranges and its
fit from (`leave_out`): the sliders, Fit to window and the mirror's plane
span the brain. Your data moves, and each change of the slider ranges made
napari slice every layer again -- 0.6 s in 3D, where every mesh rebuilt its
normals -- for one move of one image.

A scene torn down takes your layers with it (`SceneSession.teardown`);
the Your data tab keeps what they show and builds them again in the next
scene of the same brain.
"""

from __future__ import annotations

import contextlib
import weakref

from . import napari_private
from .stacking import stack
from .view import MIRROR_AXIS, apply_mirror

#: The layers that draw your data, known before napari adds them; see
#: `leave_out`. Held weakly.
_YOURS: weakref.WeakSet = weakref.WeakSet()


def counted(layer) -> bool:
    """Whether `layer` is the brain's, which the sliders and the fit span:
    not one of yours, as `leave_out` or its maker's mark says."""
    return layer not in _YOURS and not layer.metadata.get("lobemap", {}).get("yours")


def leave_out(viewer, layers=()) -> None:
    """Leave `layers`, and every layer marked as yours, out of the extent
    napari reads its sliders and its fit from (`napari_private.count_in_extent`).

    Given before napari adds them, they never change the sliders: a layer
    is marked only once napari has added it (`guards`).
    """
    _YOURS.update(layers)
    if viewer.layers.__dict__.get("_lobemap_counted") is not counted:
        napari_private.count_in_extent(viewer, counted)


class SceneYours:
    """Your images and neurons in one session."""

    # -- images ---------------------------------------------------------------

    def add_placed(self, image) -> None:
        """Put `image` -- a `placed.PlacedImage`, made hidden -- in the scene."""

        def _add() -> None:
            self.images.extend(image.slices)
            self.placed.append(image)
            if self.mirrored:
                apply_mirror(image.slices, True, self.mirror_center)
            image.set_mirror(self.reflect_axis(), self.mirror_center)
            stack(self.viewer, self.ranks())

        self.turned.moved(_add)

    def place(self, image, matrix) -> None:
        """Put `image` where `matrix` places it."""
        self.turned.moved(lambda: image.place(matrix), image.slices)

    def drop_placed(self, image) -> None:
        """Take `image` out of the scene, and its layers out of the viewer."""

        def _drop() -> None:
            image.stop()
            if image in self.placed:
                self.placed.remove(image)
            for layer in image.layers:
                if layer in self.images:
                    self.images.remove(layer)
                with contextlib.suppress(Exception):
                    if layer in self.viewer.layers:
                        self.viewer.layers.remove(layer)

        self.turned.moved(_drop)

    # -- neurons ----------------------------------------------------------------

    def mirror_args(self) -> tuple[int, float] | None:
        """(axis, center) for a surface built now, as `AtlasSurface` takes it."""
        return (MIRROR_AXIS, self.mirror_center) if self.mirrored else None

    def set_part(self, key: str, build) -> None:
        """Put the part `build` makes -- (surface, contours) -- under `key`,
        in place of the one there; `build` None takes it out.

        `build` is called on the unturned scene, as the surfaces it makes
        are built for the mirror as it is then (`mirror_args`).
        """

        def _change() -> None:
            self._drop_part(key)
            if build is None:
                return
            surface, contour = build()
            self.surfaces[key] = surface
            if contour is not None:
                self.contours[key] = contour
            self._seat(key, surface, contour)
            # Counted while napari added them, before their maker marked them.
            napari_private.refresh_extent(self.viewer)

        self.turned.moved(_change)

    def _drop_part(self, key: str) -> None:
        surface = self.surfaces.pop(key, None)
        contour = self.contours.pop(key, None)
        if surface is not None:
            surface.stop()
        if contour is not None:
            with contextlib.suppress(Exception):
                contour.stop()
        for item in (surface, contour):
            layer = getattr(item, "layer", None)
            with contextlib.suppress(Exception):
                if layer is not None and layer in self.viewer.layers:
                    self.viewer.layers.remove(layer)


__all__ = ["SceneYours", "counted", "leave_out"]
