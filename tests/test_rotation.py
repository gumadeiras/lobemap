"""The rotation arithmetic: one right-handed convention, the same on every axis.

Spin turns the picture counterclockwise, tilt brings the top toward the
viewer, turn brings the front toward the viewer's right -- whichever array
axis 2D slices along, and in 3D. These are checked on the matrices here and
on what is drawn in `test_turned_view.py`.
"""

from __future__ import annotations

import itertools

import numpy as np
import pytest

from lobemap.viewer.rotation import (
    Turn,
    aligned_frame,
    grid_frame,
    screen_matrix,
    turn_matrix,
    turned_view,
)
from lobemap.viewer.slicing import order_for

RIGHT, UP, TOWARD = np.eye(3)


def test_each_angle_turns_the_way_its_name_says():
    assert np.allclose(screen_matrix((90, 0, 0)) @ RIGHT, UP)          # counterclockwise
    assert np.allclose(screen_matrix((0, 90, 0)) @ UP, TOWARD)         # top toward the viewer
    assert np.allclose(screen_matrix((0, 0, 90)) @ TOWARD, RIGHT)      # front to the right
    for angles in [(37, 0, 0), (0, -60, 0), (15, -60, 120), (-170, 89, 5)]:
        m = screen_matrix(angles)
        assert np.allclose(m.T @ m, np.eye(3)) and np.linalg.det(m) == pytest.approx(1.0)


def test_spin_is_applied_last_so_it_only_turns_the_picture():
    for tilt, turn in [(30, 0), (0, 45), (-20, 70)]:
        base = screen_matrix((0, tilt, turn))
        spun = screen_matrix((40, tilt, turn))
        assert np.allclose(spun, screen_matrix((40, 0, 0)) @ base)


@pytest.mark.parametrize("axis", [0, 1, 2])
def test_the_2d_grid_frame_is_the_screen_napari_draws(axis):
    """Columns right, rows down: up is minus the row axis, and the frame is proper."""
    order = order_for(axis)
    frame = grid_frame(order)
    assert np.linalg.det(frame) == pytest.approx(1.0)
    assert frame[order[2], 0] == 1.0 and frame[order[1], 1] == -1.0
    assert abs(frame[axis, 2]) == 1.0


@pytest.mark.parametrize("axis", [0, 1, 2])
def test_the_2d_turn_has_the_same_sense_on_every_slice_axis(axis):
    order = order_for(axis)
    frame = grid_frame(order)
    right, up, toward = frame.T
    assert np.allclose(turn_matrix((90, 0, 0), order) @ right, up)
    assert np.allclose(turn_matrix((0, 90, 0), order) @ up, toward)
    assert np.allclose(turn_matrix((0, 0, 90), order) @ toward, right)


@pytest.mark.parametrize("axis", [0, 1, 2])
def test_zero_is_the_identity_and_spin_keeps_the_sliced_axis_exactly(axis):
    order = order_for(axis)
    assert np.array_equal(turn_matrix((0, 0, 0), order), np.eye(3))
    for spin in (15.0, 37.0, 90.0, 180.0, -123.4):
        q = turn_matrix((spin, 0, 0), order)
        assert np.array_equal(q[axis], np.eye(3)[axis])
        assert np.array_equal(q[:, axis], np.eye(3)[axis])


def test_a_turn_round_trips_its_pivot_to_the_bit():
    rng = np.random.default_rng(3)
    for _ in range(20):
        q = turn_matrix(rng.uniform(-180, 180, 3), order_for(2))
        focus = rng.uniform(-500, 500, 3)
        before = Turn.about(turn_matrix(rng.uniform(-180, 180, 3), order_for(2)),
                            rng.uniform(-500, 500, 3))
        turn = Turn.about(q, focus, before)
        assert np.array_equal(turn(turn.pivot), turn.focus)
        assert np.array_equal(turn.inverse(turn.focus), turn.pivot)
        points = rng.uniform(-500, 500, (50, 3))
        assert np.allclose(turn.inverse(turn(points)), points, atol=1e-9)
        homogeneous = np.c_[points, np.ones(50)] @ turn.affine().T
        assert np.allclose(homogeneous[:, :3], turn(points), atol=1e-9)
        # Keeping the specimen point shown at `focus` where it is.
        assert np.allclose(turn(before.inverse(focus)), focus, atol=1e-9)


def test_3d_turns_the_camera_by_the_inverse_of_the_scene():
    view, up = np.array([0.0, 0.0, -1.0]), np.array([0.0, 1.0, 0.0])
    for angles in [(37, 0, 0), (0, 37, 0), (0, 0, 37), (15, -60, 120)]:
        v, u = turned_view(view, up, angles)
        basis = np.column_stack([np.cross(view, up), up, -view])
        world = basis @ screen_matrix(angles) @ basis.T
        # A scene point turned with the scene is seen where the camera,
        # turned back, sees the unturned point.
        p = np.array([0.3, -1.2, 2.0])
        screen_turned = np.array([np.cross(view, up) @ (world @ p), up @ (world @ p)])
        right2 = np.cross(v, u)
        screen_camera = np.array([right2 @ p, u @ p])
        assert np.allclose(screen_turned, screen_camera, atol=1e-12)


def test_the_aligned_frame_is_the_proper_anatomy_nearest_the_grid():
    rng = np.random.default_rng(5)
    grid = grid_frame(order_for(2))
    for _ in range(20):
        small = turn_matrix(rng.uniform(-25, 25, 3), order_for(2))
        anatomy = small @ np.eye(3)[:, list(rng.permutation(3))]
        anatomy = anatomy * rng.choice([-1.0, 1.0], 3)
        frame = aligned_frame(grid, anatomy)
        assert np.linalg.det(frame) == pytest.approx(1.0)
        # Each column is the anatomical direction nearest the grid's.
        for k in range(3):
            assert np.argmax(np.abs(anatomy.T @ grid[:, k])) == np.argmax(
                np.abs(anatomy.T @ frame[:, k]))
            assert grid[:, k] @ frame[:, k] > np.cos(np.radians(45))
    for signs in itertools.product((1, -1), repeat=3):
        anatomy = np.eye(3) * np.asarray(signs)
        assert np.allclose(aligned_frame(grid, anatomy), grid)
