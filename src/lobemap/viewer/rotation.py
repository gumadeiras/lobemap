"""Turning the view: three angles that mean the same thing in 2D and in 3D.

The angles turn the SCENE, in degrees, about the axes of the screen as the
mode's base view shows it -- right, up, and toward the viewer:

- **spin** about the line of sight; positive turns the picture
  counterclockwise on screen.
- **tilt** about the screen's horizontal axis; positive brings the top
  toward the viewer.
- **turn** about the screen's vertical axis; positive brings the front
  toward the viewer's right.

They compose as turn first, then tilt, then spin, each about the fixed
screen axes (`screen_matrix`), so spin is always a plain turn of the
picture whatever the other two are. Each is a right-handed rotation about
its axis, and the screen frame is right-handed, so the sense on screen is
the same whichever axis 2D slices along, and in either mode.

The base view of 3D is the anatomical Home (`view.orient_anterior`), and the
camera is turned by the inverse of the scene rotation (`turned_view`): no
layer moves. The base view of 2D is the image grid as the slider cuts it --
or, with the alignment option, the anatomy nearest it (`aligned_frame`) --
and the 2D section is the plane through the pivot perpendicular to the
turned line of sight (`Turn`, `viewer.turned`).

This module is arithmetic, plus the record of which scene owns a viewer's
view (`register`), which `view` and `axes` read so that Home and the
triads follow the turn without being handed it.
"""

from __future__ import annotations

import weakref
from dataclasses import dataclass
from itertools import permutations, product

import numpy as np

#: (spin, tilt, turn) at rest.
ZERO = (0.0, 0.0, 0.0)


def _about(axis: int, degrees: float) -> np.ndarray:
    """A right-handed rotation about one axis of (right, up, toward viewer)."""
    t = np.radians(float(degrees))
    c, s = np.cos(t), np.sin(t)
    i, j = [(1, 2), (2, 0), (0, 1)][axis]
    m = np.eye(3)
    m[i, i], m[i, j], m[j, i], m[j, j] = c, -s, s, c
    return m


def screen_matrix(angles) -> np.ndarray:
    """The scene rotation in screen coordinates (right, up, toward viewer)."""
    spin, tilt, turn = (float(a) for a in angles)
    return _about(2, spin) @ _about(0, tilt) @ _about(1, turn)


def turned_view(view, up, angles) -> tuple[np.ndarray, np.ndarray]:
    """The camera's view and up directions once the scene is turned.

    `view` and `up` are Home's, in the world's displayed axes. Screen right
    is `view x up` in napari's convention, and (right, up, -view) is a
    right-handed frame. Turning the scene by R about the camera's center is
    turning the camera by R's inverse.
    """
    view = np.asarray(view, float)
    up = np.asarray(up, float)
    basis = np.column_stack([np.cross(view, up), up, -view])
    world = basis @ screen_matrix(angles) @ basis.T
    return world.T @ view, world.T @ up


def grid_frame(order) -> np.ndarray:
    """The 2D base view of an unturned slice, as columns (right, up, toward).

    `order` is `dims.order` in 2D: the sliced axis, then rows, then
    columns. napari draws columns to the right and rows down, so up is
    minus the row axis, and toward the viewer completes a right-handed
    frame: minus z when slicing z, as napari's 2D view looks along +z.
    """
    _axis, row, col = (int(a) for a in list(order)[-3:])
    right, up = np.zeros(3), np.zeros(3)
    right[col], up[row] = 1.0, -1.0
    return np.column_stack([right, up, np.cross(right, up)])


def aligned_frame(base: np.ndarray, anatomy: np.ndarray) -> np.ndarray:
    """The anatomical frame nearest a grid frame, as a proper rotation.

    `anatomy` holds the anatomical directions A, D and R as columns, in
    the world the base frame is in (reflected with the scene). Of the 24
    signed arrangements of them that a rotation can reach from `base`, the
    nearest -- largest trace of `base.T @ frame` -- keeps the view on the
    side of the brain the grid view is on and turns it by the 15-32
    degrees between grid and anatomy, and no further.
    """
    anatomy = np.asarray(anatomy, float)
    best, score = None, -np.inf
    for perm in permutations(range(3)):
        for signs in product((1.0, -1.0), repeat=3):
            frame = anatomy[:, perm] * np.asarray(signs)
            if np.linalg.det(frame) < 0:
                continue
            got = float(np.trace(base.T @ frame))
            if got > score:
                best, score = frame, got
    return best


@dataclass(frozen=True)
class Turn:
    """The rigid map `T(x) = focus + q (x - pivot)` of the unturned world.

    The unturned world is napari's world as `main` shows it, mirror
    included; T(world) is what napari's world holds while 2D is turned.
    `pivot` is the specimen point kept at `focus`, the world point at the
    center of the view on the slider's plane. Both are kept exact, so
    `T(pivot)` and `inverse(focus)` round-trip to the bit.
    """

    q: np.ndarray
    pivot: np.ndarray
    focus: np.ndarray

    @classmethod
    def about(cls, q, focus, before: Turn | None = None) -> Turn:
        """`q`, keeping the specimen point now shown at `focus` there.

        `before` is the turn shown now, or None for the unturned world.
        """
        focus = np.array(focus, float)
        pivot = focus.copy() if before is None else before.inverse(focus)
        return cls(np.array(q, float), pivot, focus)

    def __call__(self, points) -> np.ndarray:
        x = np.asarray(points, float)
        return self.focus + (x - self.pivot) @ self.q.T

    def inverse(self, points) -> np.ndarray:
        y = np.asarray(points, float)
        return self.pivot + (y - self.focus) @ self.q

    def affine(self) -> np.ndarray:
        """T as a 4x4 world affine."""
        out = np.eye(4)
        out[:3, :3] = self.q
        out[:3, 3] = self.focus - self.q @ self.pivot
        return out

    def depth(self, axis: int) -> tuple[np.ndarray, float]:
        """(direction, offset) with `T(x)[axis] = direction . x + offset`."""
        row = self.q[axis].copy()
        return row, float(self.focus[axis] - row @ self.pivot)


def base_frame(order, anatomy=None) -> np.ndarray:
    """The 2D base view for `order`: the grid's, or the anatomy's nearest it."""
    grid = grid_frame(order)
    return grid if anatomy is None else aligned_frame(grid, anatomy)


def turn_matrix(angles, order, anatomy=None) -> np.ndarray:
    """`q` for the 2D view: points in the base frame, turned, shown in the grid's.

    Exactly the identity at zero angles without the alignment option, and
    exactly a rotation about the sliced axis when only spin is set.
    """
    grid = grid_frame(order)
    base = grid if anatomy is None else aligned_frame(grid, anatomy)
    return grid @ screen_matrix(angles) @ base.T


# -- which scene a viewer is showing -----------------------------------------

_OWNERS: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()


def register(viewer, owner) -> None:
    """Record `owner` -- a scene's `turned.TurnedView` -- as the viewer's view.

    The scene built last owns it; a switch that fails gives it back to the
    scene it kept (`SceneSession.reassert`).
    """
    _OWNERS[viewer] = weakref.ref(owner)


def unregister(viewer, owner) -> None:
    """Forget `owner`, if it still owns the viewer's view."""
    ref = _OWNERS.get(viewer)
    if ref is not None and ref() in (owner, None):
        del _OWNERS[viewer]


def owner(viewer):
    """The `TurnedView` of the scene the viewer shows, or None."""
    ref = _OWNERS.get(viewer)
    return None if ref is None else ref()


def angles_of(viewer) -> tuple[float, float, float]:
    """The angles the viewer's scene is turned by: what Home faces."""
    view = owner(viewer)
    return ZERO if view is None else tuple(view.angles)


__all__ = [
    "ZERO",
    "Turn",
    "aligned_frame",
    "angles_of",
    "base_frame",
    "grid_frame",
    "owner",
    "register",
    "screen_matrix",
    "turn_matrix",
    "turned_view",
    "unregister",
]
