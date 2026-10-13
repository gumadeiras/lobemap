"""Moving an image of yours as you see it: on screen, through the mirror and
the turn the scene is shown with.

An image's placement is a matrix into the space (`core.placement`); what you
see is napari's world, which is the space mirrored, if the mirror is on, and
in Slice view turned by the view's turn (`turned`). So a move, a turn or a
flip asked for on screen is made in the world, about the image's middle as
shown, and taken back into the space (`world_matrix`).

The screen's axes are right, up and toward you, as they are drawn: measured
on napari's canvas (`tests/test_your_images.py`). In Slice view they are the
grid's (`rotation.grid_frame`), with up the other way round when the
picture is flipped. In 3D they are the camera's: napari's `up_direction`
is the canvas's up, flipped or not, and right is `view x up` upright and
the reverse upside down, where napari draws the scene mirrored and turned.
"""

from __future__ import annotations

import numpy as np

from ..core.placement import about, middle, shift
from .rotation import grid_frame, screen_matrix
from .view import mirror_matrix, upside_down

#: The screen's axes, as the View dock's Rotate around names them, by their
#: place in (spin, tilt, turn) (`rotation.screen_matrix`).
LINE_OF_SIGHT, HORIZONTAL, VERTICAL = 0, 1, 2


def world_matrix(session) -> np.ndarray:
    """The 4x4 map from the space's micrometers to napari's world as shown."""
    mirror = mirror_matrix(3, session.mirror_center) if session.mirrored else np.eye(4)
    turn = session.turned.shown_turn
    return mirror if turn is None else turn.affine() @ mirror


def screen_frame(viewer) -> np.ndarray:
    """The world directions of screen right, up and toward you, as columns."""
    flipped = upside_down(viewer)
    if viewer.dims.ndisplay == 3:
        camera = viewer.scene.camera
        view = np.asarray(camera.view_direction, float)
        up = np.asarray(camera.up_direction, float)
        right = np.cross(view, up) * (-1.0 if flipped else 1.0)
        return np.column_stack([right, up, -view])
    frame = grid_frame(viewer.dims.order).copy()
    if flipped:
        frame[:, 1] *= -1.0
    return frame


def space_point(session, world) -> np.ndarray:
    """The point of the space shown at `world`, a point of napari's world."""
    inverse = np.linalg.inv(world_matrix(session))
    return inverse[:3, :3] @ np.asarray(world, float)[-3:] + inverse[:3, 3]


def _on_screen(session, matrix, shape, linear) -> np.ndarray:
    """`matrix` with `linear`, a map of the world, made about the image's
    middle as it is shown."""
    world = world_matrix(session)
    center = world[:3, :3] @ middle(matrix, shape) + world[:3, 3]
    return np.linalg.inv(world) @ about(center, linear) @ world @ np.asarray(matrix, float)


def turned(session, matrix, shape, axis: int, degrees: float) -> np.ndarray:
    """`matrix` turned about a screen axis through the image's middle.

    `axis` is LINE_OF_SIGHT, HORIZONTAL or VERTICAL, and a positive angle
    turns the image as the View dock's Rotate around turns the brain:
    counterclockwise, top toward you, near side to your right.
    """
    angles = [0.0, 0.0, 0.0]
    angles[axis] = float(degrees)
    frame = screen_frame(session.viewer)
    linear = frame @ screen_matrix(angles) @ np.linalg.inv(frame)
    return _on_screen(session, matrix, shape, linear)


def flipped(session, matrix, shape, top_bottom: bool) -> np.ndarray:
    """`matrix` mirrored left to right on screen, or top to bottom, about the
    image's middle."""
    axis = screen_frame(session.viewer)[:, 1 if top_bottom else 0]
    return _on_screen(session, matrix, shape, np.eye(3) - 2.0 * np.outer(axis, axis))


def scaled(matrix, shape, factor: float) -> np.ndarray:
    """`matrix` made `factor` times larger about the image's middle."""
    return about(middle(matrix, shape), float(factor) * np.eye(3)) @ np.asarray(matrix, float)


def dragged(session, matrix, pixels) -> np.ndarray:
    """`matrix` moved by (right, down) canvas pixels, in the screen's plane."""
    camera = session.viewer.scene.camera
    frame = screen_frame(session.viewer)
    right, down = (float(p) for p in pixels)
    delta = (right * frame[:, 0] - down * frame[:, 1]) / float(camera.zoom)
    world = world_matrix(session)
    return shift(np.linalg.inv(world[:3, :3]) @ delta) @ np.asarray(matrix, float)


def centered(matrix, shape, point) -> np.ndarray:
    """`matrix` moved so the image's middle is at `point` of the space."""
    return shift(np.asarray(point, float) - middle(matrix, shape)) @ np.asarray(matrix, float)


__all__ = [
    "HORIZONTAL",
    "LINE_OF_SIGHT",
    "VERTICAL",
    "centered",
    "dragged",
    "flipped",
    "scaled",
    "screen_frame",
    "space_point",
    "turned",
    "world_matrix",
]
