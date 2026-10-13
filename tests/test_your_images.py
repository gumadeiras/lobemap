"""Your images in a scene, measured on what is drawn, in a synthetic scene.

No fetched data (`turned_harness`). The image is three ramp channels, each
voxel's value its index along x, y or z, so the value napari shows at a
point says exactly which voxel of the image it shows there; trilinear
sampling of a ramp is exact, through one resampling or two.

- Slice view shows the image's section on the plane, wherever its placement
  turns it, mirrored and turned with the scene, oblique sections included.
- 3D draws its voxels where the placement puts them, mirrored with the scene.
- Each mode draws one layer of each channel, the other hidden.
- A turn, a flip and a drag move it as seen on screen.
"""

from __future__ import annotations

import numpy as np
import pytest
import turned_harness as th
from scipy.spatial.transform import Rotation
from viewer_harness import canvas_position, click, pump

from lobemap.core.placement import apply, middle
from lobemap.viewer import placing
from lobemap.viewer.placed import PlacedImage, PlacedVolume

napari = pytest.importorskip("napari")

#: The image: its shape, and where it is placed among the synthetic bodies.
SHAPE = (40, 36, 30)


def _matrix(turn=(25.0, -35.0, 70.0)) -> np.ndarray:
    out = np.eye(4)
    out[:3, :3] = Rotation.from_euler("xyz", turn, degrees=True).as_matrix() @ np.diag(
        [0.8, 0.9, 1.1])
    out[:3, 3] = np.asarray(th.BODIES[0][1]) - out[:3, :3] @ ((np.array(SHAPE) - 1) / 2)
    return out


def _ramps() -> list[np.ndarray]:
    return [th.ramp(axis, SHAPE) for axis in range(3)]


@pytest.fixture
def viewer():
    v = napari.Viewer(show=False, ndisplay=2)
    yield v
    v.close()
    pump()


def _scene(viewer, registry, matrix=None):
    session = th.build(viewer, registry)
    image = PlacedImage(viewer, "ramps", _ramps(), _matrix() if matrix is None else matrix,
                        [(0.0, float(max(SHAPE)))] * 3)
    session.add_placed(image)
    image.set_visible(True)
    th.settle_canvas(viewer)
    th.through_middle(viewer, 2, session.contours["synthetic"])
    th.settle_canvas(viewer)
    return session, image


def _voxel_shown(session, image, layer, world) -> np.ndarray:
    """The image voxel the slice layer's data voxel nearest `world` is."""
    data = np.round(np.asarray(layer.world_to_data(world), float))
    at = np.asarray(layer.data_to_world(data), float)
    space = placing.space_point(session, at)
    return apply(np.linalg.inv(image.matrix), space)[0], at


def _check_slice(viewer, session, image) -> int:
    """Each channel shows, at points of the plane, the voxel placed there.

    Round the image's middle as shown, on the plane: the mirror reflects
    the scene about the brain's mid-plane, and the image with it.
    """
    right, up, _focus = th.screen_frame(viewer)
    axis = int(viewer.dims.order[0])
    focus = _shown(session, image.matrix, (np.array(SHAPE) - 1) / 2)
    focus[axis] = float(viewer.dims.point[axis])
    checked = 0
    for a in np.linspace(-12, 12, 5):
        for b in np.linspace(-12, 12, 5):
            world = focus + a * right + b * up
            for k, layer in enumerate(image.slices):
                want, at = _voxel_shown(session, image, layer, world)
                if np.any(want < 1) or np.any(want > np.array(SHAPE) - 2):
                    continue
                got = th.image_index_at(layer, at)
                assert got == pytest.approx(want[k], abs=2e-3), (k, world)
                checked += 1
    assert checked > 30
    return checked


@pytest.mark.parametrize("mirrored", [False, True])
@pytest.mark.parametrize("angles", [(0, 0, 0), (37, 0, 0), (20, 15, 0), (-30, 10, 25)])
def test_slice_view_shows_the_image_s_own_section(viewer, registry, mirrored, angles):
    session, image = _scene(viewer, registry)
    if mirrored:
        session.set_mirror(True)
    session.set_rotation(*angles)
    th.settle_canvas(viewer)
    _check_slice(viewer, session, image)


def test_a_new_placement_is_shown_on_a_turned_slice(viewer, registry):
    session, image = _scene(viewer, registry)
    session.set_mirror(True)
    session.set_rotation(20, 15, 0)
    th.settle_canvas(viewer)
    session.place(image, _matrix((-10.0, 20.0, 5.0)))
    th.settle_canvas(viewer)
    assert session.rotation == (20.0, 15.0, 0.0)
    _check_slice(viewer, session, image)


@pytest.mark.parametrize("mirrored", [False, True])
def test_3d_draws_the_voxels_where_they_are_placed(viewer, registry, mirrored):
    session, image = _scene(viewer, registry)
    if mirrored:
        session.set_mirror(True)
    viewer.dims.ndisplay = 3
    pump()
    corners = np.array([[0, 0, 0], [39, 0, 0], [0, 35, 29], [39, 35, 29]], float)
    world = placing.world_matrix(session)
    for volume in image.volumes:
        got = np.array([volume.data_to_world(c) for c in corners])
        assert np.allclose(got, apply(world @ image.matrix, corners), atol=1e-6)


def test_each_mode_draws_one_layer_of_each_channel(viewer, registry):
    session, image = _scene(viewer, registry)
    for ndisplay in (3, 2, 3):
        viewer.dims.ndisplay = ndisplay
        pump()
        drawn = image.volumes if ndisplay == 3 else image.slices
        assert [layer.visible for layer in image.layers] == [
            layer in drawn for layer in image.layers]
    image.set_visible(False)
    assert not any(layer.visible for layer in image.layers)
    # napari's eye on the layer the mode draws shows the image again.
    image.volumes[0].visible = True
    assert image.visible and all(layer.visible for layer in image.volumes)


def test_the_slice_layers_sit_over_the_brain_maps_and_under_the_meshes(viewer, registry):
    session, image = _scene(viewer, registry)
    names = [layer.name for layer in viewer.layers]
    brain = [names.index(layer.name) for layer in session.images if layer not in image.slices]
    yours = [names.index(layer.name) for layer in image.layers]
    meshes = [names.index(session.surfaces["synthetic"].layer.name),
              names.index(session.contours["synthetic"].layer.name)]
    assert max(brain) < min(yours) and max(yours) < min(meshes)


def test_a_placed_volume_reads_a_plane_without_reading_the_rest():
    data = _ramps()[0]
    grid = PlacedVolume(data, _matrix(), 0.8)
    plane = grid[:, :, grid.shape[2] // 2]
    assert isinstance(grid[:, :, :], PlacedVolume)
    assert plane.shape == grid.shape[:2]
    # The middle of the grid shows the middle of the image.
    center = np.array(grid.shape) // 2
    space = grid.translate + grid.step * center
    want = apply(np.linalg.inv(_matrix()), space)[0][0]
    assert float(grid[tuple(center)]) == pytest.approx(want, abs=1e-3)


def _screen_angle(viewer, a, b) -> float:
    pa, pb = np.asarray(canvas_position(viewer, a)), np.asarray(canvas_position(viewer, b))
    dx, dy = pb - pa
    return float(np.degrees(np.arctan2(-dy, dx)))


def _shown(session, matrix, index) -> np.ndarray:
    """Where napari's world shows voxel `index` of an image placed by `matrix`."""
    return apply(placing.world_matrix(session) @ matrix, index)[0]


@pytest.mark.parametrize("mirrored", [False, True])
@pytest.mark.parametrize("flipped", [False, True])
def test_a_turn_about_the_line_of_sight_turns_the_image_counterclockwise(
        viewer, registry, mirrored, flipped):
    session, image = _scene(viewer, registry)
    session.set_mirror(mirrored)
    session.set_flip(flipped)
    th.settle_canvas(viewer)
    right, up, _focus = th.screen_frame(viewer)
    # Two voxels of the image on the plane: its middle and one to its right.
    mid = middle(image.matrix, image.shape) if hasattr(image, "shape") else None
    center = _shown(session, image.matrix, (np.array(SHAPE) - 1) / 2)
    side = center + 5.0 * right
    inverse = np.linalg.inv(placing.world_matrix(session) @ image.matrix)
    a, b = apply(inverse, center)[0], apply(inverse, side)[0]
    before = _screen_angle(viewer, center, side)
    turned = placing.turned(session, image.matrix, SHAPE, placing.LINE_OF_SIGHT, 30.0)
    after = _screen_angle(viewer, _shown(session, turned, a), _shown(session, turned, b))
    assert (after - before - 30.0 + 180.0) % 360.0 - 180.0 == pytest.approx(0.0, abs=1e-6)
    assert np.allclose(_shown(session, turned, a), center)
    assert mid is None or np.allclose(middle(turned, SHAPE), middle(image.matrix, SHAPE))


@pytest.mark.parametrize("flipped", [False, True])
def test_3d_turns_move_the_image_as_the_view_dock_turns_the_brain(viewer, registry, flipped):
    session, image = _scene(viewer, registry)
    viewer.dims.ndisplay = 3
    viewer.scene.camera.angles = (10.0, 25.0, 40.0)
    session.set_flip(flipped)
    th.settle_canvas(viewer)
    right, up, toward = th.screen_axes(viewer)
    center = _shown(session, image.matrix, (np.array(SHAPE) - 1) / 2)
    inverse = np.linalg.inv(placing.world_matrix(session) @ image.matrix)
    near, top = (apply(inverse, center + 5.0 * d)[0] for d in (toward, up))
    # Vertical axis: the near side moves to your right.
    turned = placing.turned(session, image.matrix, SHAPE, placing.VERTICAL, 20.0)
    assert np.dot(_shown(session, turned, near) - center, right) > 1.0
    # Horizontal axis: the top comes toward you.
    turned = placing.turned(session, image.matrix, SHAPE, placing.HORIZONTAL, 20.0)
    assert np.dot(_shown(session, turned, top) - center, toward) > 1.0


@pytest.mark.parametrize("mirrored", [False, True])
def test_a_flip_mirrors_the_image_as_seen(viewer, registry, mirrored):
    session, image = _scene(viewer, registry)
    session.set_mirror(mirrored)
    right, up, _focus = th.screen_frame(viewer)
    center = _shown(session, image.matrix, (np.array(SHAPE) - 1) / 2)
    inverse = np.linalg.inv(placing.world_matrix(session) @ image.matrix)
    voxel = apply(inverse, center + 4.0 * right + 3.0 * up)[0]
    flipped = placing.flipped(session, image.matrix, SHAPE, top_bottom=False)
    assert np.allclose(_shown(session, flipped, voxel), center - 4.0 * right + 3.0 * up)
    flipped = placing.flipped(session, image.matrix, SHAPE, top_bottom=True)
    assert np.allclose(_shown(session, flipped, voxel), center + 4.0 * right - 3.0 * up)


@pytest.mark.parametrize("ndisplay", [2, 3])
def test_a_drag_moves_the_image_under_the_cursor(viewer, registry, ndisplay):
    session, image = _scene(viewer, registry)
    viewer.dims.ndisplay = ndisplay
    th.settle_canvas(viewer)
    center = _shown(session, image.matrix, (np.array(SHAPE) - 1) / 2)
    before = np.asarray(canvas_position(viewer, center))
    moved = placing.dragged(session, image.matrix, (30.0, -20.0))
    after = np.asarray(canvas_position(viewer, _shown(session, moved,
                                                      (np.array(SHAPE) - 1) / 2)))
    assert after - before == pytest.approx((30.0, -20.0), abs=0.05)


def test_dragging_with_the_mouse_moves_the_image_and_not_the_view(viewer, registry):
    """Through napari's own mouse path, as the tab's Drag to move does."""
    from lobemap.viewer.image_rows import PlaceRows

    session, image = _scene(viewer, registry)
    applied = []

    class Box:                                   # what PlaceRows asks of its tab
        def __init__(self):
            self.viewer, self.session = viewer, session

        def current(self):
            return image if not applied else type("I", (), {"matrix": applied[-1]})()

        def apply(self, matrix, record=True):
            applied.append(matrix)
            session.place(image, matrix)

        def undo(self):
            pass

    rows = PlaceRows(Box())
    camera = tuple(viewer.scene.camera.center)
    center = _shown(session, image.matrix, (np.array(SHAPE) - 1) / 2)
    before = np.asarray(canvas_position(viewer, center))
    rows.drag.setChecked(True)
    click(viewer, center, drag=24.0)
    rows.drag.setChecked(False)
    assert tuple(viewer.scene.camera.center) == camera and viewer.scene.camera.mouse_pan
    after = np.asarray(canvas_position(viewer, _shown(session, image.matrix,
                                                      (np.array(SHAPE) - 1) / 2)))
    assert after - before == pytest.approx((24.0, 0.0), abs=0.05)


def test_taking_an_image_out_leaves_the_scene_as_it_was(viewer, registry):
    session, image = _scene(viewer, registry)
    session.set_rotation(20, 15, 0)
    th.settle_canvas(viewer)
    session.drop_placed(image)
    assert not session.placed and all(layer not in viewer.layers for layer in image.layers)
    assert all(layer not in session.images for layer in image.layers)
    session.set_rotation(0, 0, 0)
    th.assert_on_the_plane(viewer, session)


@pytest.mark.parametrize("ndisplay", [2, 3])
def test_your_image_never_moves_the_sliders_the_fit_or_the_mirror_plane(viewer, registry,
                                                                         ndisplay):
    """They span the brain: a change of the sliders made napari slice every
    layer again, 0.6 s in 3D for a move of one image."""
    session = th.build(viewer, registry)
    viewer.dims.ndisplay = ndisplay
    th.settle_canvas(viewer)
    ranges, center = list(viewer.dims.range), session.mirror_center
    fit = viewer.layers._extent_world_augmented.copy()
    far = _matrix()
    far[:3, :3] *= 0.2                          # finer voxels than the brain's
    far[:3, 3] += 400.0                         # and far outside it
    image = PlacedImage(viewer, "far", _ramps(), far, [(0.0, 40.0)] * 3)
    session.add_placed(image)
    image.set_visible(True)
    session.place(image, placing.centered(far, SHAPE, (900.0, 900.0, 900.0)))
    pump()
    assert list(viewer.dims.range) == ranges
    assert session.mirror_center == center
    assert np.allclose(viewer.layers._extent_world_augmented, fit)
