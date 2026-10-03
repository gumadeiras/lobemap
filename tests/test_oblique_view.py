"""2D turned across the image grid: the oblique section, measured on what is drawn.

Synthetic data (`turned_harness`): ramp images, whose every texel names the
specimen point it shows, and ellipsoid compartments.

- The image and the contours lie on one plane, the exact section of the
  meshes; every texel napari draws holds the trilinear sample of its own
  specimen point, at whatever level napari picks.
- The image layer stays the user's: no layer is added, its controls govern,
  and shown while turned it shows the turned plane.
- The slider steps along the turned line of sight, over the scene's extent
  along it, and is not labeled as an image axis.
- Rest, in any order of modes, gives back the view; the slice axis and the
  order stay in step; mirror and turn reach every picture.
"""

from __future__ import annotations

import numpy as np
import pytest
import turned_harness as th
from viewer_harness import hover, pump

napari = pytest.importorskip("napari")

ANGLES = [(0, 37, 0), (20, 37, 15), (0, 0, 90), (0, 180, 0), (90, 0, 180),
          (-30, 60, -120)]


@pytest.fixture
def viewer():
    v = napari.Viewer(show=False, ndisplay=2)
    yield v
    v.close()
    pump()


def _scene(viewer, registry, axis=2, mirrored=False, multiscale=False):
    session = th.build(viewer, registry, multiscale=multiscale)
    th.settle_canvas(viewer)
    if axis != 2:
        session.set_slice_axis(axis)
    th.through_middle(viewer, axis)
    if mirrored:
        session.set_mirror(True)
    th.settle_canvas(viewer)
    return session


def _check(viewer, session, tol_um=2e-4):
    """One plane: contours against trimesh, images under them, every texel."""
    from test_turned_view import _check_plane

    _check_plane(viewer, session, tol_um)
    contour = session.contours["synthetic"]
    for k, image in enumerate(session.images):
        got, want = th.texels(viewer, image, contour, k)
        assert len(got) > 100
        # Trilinear on a ramp is exact; float32 data.
        assert np.abs(got - want).max() < 2e-3, (k, np.abs(got - want).max())


@pytest.mark.parametrize("axis", [2, 0])
@pytest.mark.parametrize("mirrored", [False, True])
def test_an_oblique_section_is_one_exact_plane(viewer, registry, axis, mirrored):
    session = _scene(viewer, registry, axis, mirrored)
    names = [layer.name for layer in viewer.layers]
    for angles in ANGLES:
        session.set_rotation(*angles)
        th.settle_canvas(viewer)
        _check(viewer, session)
        # The slider steps no image axis, and napari's image triad is put away.
        assert viewer.dims.axis_labels[axis] == "depth"
        from lobemap.viewer.axes import _vispy_axes_overlay

        assert not _vispy_axes_overlay(viewer).node.axes.visible
        assert [layer.name for layer in viewer.layers] == names


def test_every_level_napari_picks_is_sampled_where_it_is_drawn(viewer, registry):
    """A pyramid: napari picks its level and region; never coarser than
    unturned at the same zoom; and the region covers the canvas."""
    session = _scene(viewer, registry, multiscale=True)
    image = session.images[0]
    contour = session.contours["synthetic"]
    base = viewer.scene.camera.zoom
    canvas = viewer.window._qt_viewer.canvas
    seen = set()
    for factor in (0.02, 0.04, 0.07, 0.12, 0.5, 2.0):
        session.set_rotation(0, 0, 0)
        viewer.scene.camera.zoom = base * factor
        th.settle_canvas(viewer)
        unturned = image.data_level
        session.set_rotation(10, 33, -25)
        viewer.scene.camera.zoom = base * factor
        th.settle_canvas(viewer)
        level = image.data_level
        seen.add(level)
        shapes = np.array(image.level_shapes, float)
        shown = list(viewer.dims.displayed)
        # Coarser by no more than the unturned level's own factor.
        assert np.all(shapes[0, shown] / shapes[level, shown]
                      <= 2.0 ** unturned * (1 + 1e-9)), (factor, level, unturned)
        for k, layer in enumerate(session.images):
            got, want = th.texels(viewer, layer, contour, k)
            if len(got):
                assert np.abs(got - want).max() < 2e-3, (factor, k)
        # The region read covers what the canvas shows, inside the data.
        corners = np.asarray(canvas._viewbox_corners_in_world)[:, shown]
        data = np.array([image.world_to_data(_at(viewer, c)) for c in
                         [corners[0], corners[1], [corners[0][0], corners[1][1]],
                          [corners[1][0], corners[0][1]]]])[:, shown]
        held = np.asarray(image.corner_pixels)[:, shown] * (shapes[0, shown]
                                                            / shapes[level, shown])
        top = shapes[0, shown] - 1
        assert np.all(held[0] <= np.clip(data.min(axis=0), 0, top) + 1)
        assert np.all(held[1] + shapes[0, shown] / shapes[level, shown]
                      >= np.clip(data.max(axis=0), 0, top) - 1)
    assert len(seen) > 1


def _at(viewer, displayed_xy) -> np.ndarray:
    """A world point with the displayed axes set, on the slider's plane."""
    point = np.array(viewer.dims.point, float)
    point[list(viewer.dims.displayed)] = displayed_xy
    return point


def test_the_image_layer_stays_the_users_while_turned(viewer, registry):
    """No layer is added; its own controls govern; hidden and shown again
    while turned it shows the turned plane."""
    session = _scene(viewer, registry)
    image, contour = session.images[1], session.contours["synthetic"]
    names = [layer.name for layer in viewer.layers]
    image.visible = False
    session.set_rotation(15, -40, 25)
    th.settle_canvas(viewer)
    assert [layer.name for layer in viewer.layers] == names
    image.visible = True
    th.settle_canvas(viewer)
    got, want = th.texels(viewer, image, contour, 1)
    assert len(got) > 100 and np.abs(got - want).max() < 2e-3
    from lobemap.viewer.napari_private import layer_visual

    node = layer_visual(viewer, image).node
    for setting, value in (("contrast_limits", (3.0, 11.0)), ("gamma", 0.4),
                           ("opacity", 0.3), ("colormap", "magma"), ("blending", "additive")):
        setattr(image, setting, value)
        th.settle_canvas(viewer)
    assert np.allclose(node.clim, (3.0, 11.0)) and node.gamma == pytest.approx(0.4)
    assert node.opacity == pytest.approx(0.3) and image.colormap.name == "magma"
    viewer.layers.selection.active = image
    assert viewer.layers.selection.active is image
    session.set_rotation(0, 0, 0)
    assert image.contrast_limits == [3.0, 11.0] and image.colormap.name == "magma"
    assert isinstance(image.data, np.ndarray)


def test_the_slider_steps_along_the_turned_line_of_sight(viewer, registry):
    session = _scene(viewer, registry, mirrored=True)
    contour = session.contours["synthetic"]
    session.set_rotation(20, 37, 15)
    th.settle_canvas(viewer)
    axis = int(viewer.dims.order[0])
    start, stop, step = viewer.dims.range[axis]
    # The scene's extent along the turned normal: every mesh vertex and the
    # images' boxes, through the contours' own placement.
    origin, normal = th.plane_in_mesh(viewer, contour)
    normal = normal / np.linalg.norm(normal)
    world_per_mesh = th.mesh_to_world(contour, origin + normal)[axis] - th.mesh_to_world(
        contour, origin)[axis]
    heights = [th.mesh_to_world(contour, v)[axis] for v in contour.meshset.vertices[::7]]
    box = np.array([np.where(bits, th.TRANSLATE + th.SCALE * (np.array(th.SHAPE) - 1),
                             th.TRANSLATE) for bits in np.ndindex(2, 2, 2)])
    heights += [th.mesh_to_world(contour, c)[axis] for c in box]
    low, high = min(heights), max(heights)
    assert abs(abs(world_per_mesh) - 1.0) < 1e-9
    assert start <= low + 1e-6 and stop >= high - 1e-6
    assert start > low - step - 1e-6 and stop < high + step + 1e-6
    # One step moves the cut one step along the normal, in the meshes too.
    before, _n = th.plane_in_mesh(viewer, contour)
    k = viewer.dims.current_step[axis]
    viewer.dims.set_current_step(axis, k + 1)
    after, _n = th.plane_in_mesh(viewer, contour)
    assert abs(abs(np.dot(after - before, normal)) - step) < 1e-6
    _check(viewer, session)


#: Sequences of mode changes, the turn ("turn") and rest ("zero").
ORDERS = {
    "turn in 2D, rest in 3D": ["turn", 3, "zero", 2],
    "turn in 3D, rest in 2D": [3, "turn", 2, "zero"],
    "turn in 3D, rest in 2D, trip": [3, "turn", 2, "zero", 3, 2],
    "turn in 2D, trips, rest in 2D": ["turn", 3, 2, 3, 2, "zero"],
}


@pytest.mark.parametrize("name", list(ORDERS))
def test_rest_gives_back_the_view_in_any_order_of_modes(viewer, registry, name):
    """Rest leaves the view as the same trips taken unturned leave it."""
    session = _scene(viewer, registry, axis=1)
    results = []
    for turned in (False, True):
        session.set_rotation(0, 0, 0)
        viewer.dims.ndisplay = 2
        th.settle_canvas(viewer)
        for step in ORDERS[name]:
            if step == "turn":
                if turned:
                    session.set_rotation(20, 37, 15)
            elif step == "zero":
                session.set_rotation(0, 0, 0)
            else:
                viewer.dims.ndisplay = step
            th.settle_canvas(viewer)
        results.append((th.state(viewer), th.render(viewer)))
    assert results[1][0] == results[0][0]
    assert np.array_equal(results[1][1], results[0][1])


def test_turn_then_another_slice_axis_then_zero_keeps_the_order(viewer, registry):
    """The slice axis and dims.order stay in step; a spin after is in plane."""
    from lobemap.viewer.slicing import order_for

    session = _scene(viewer, registry)
    session.set_rotation(0, 37, 0)
    session.set_slice_axis(0)
    th.settle_canvas(viewer)
    _check(viewer, session)
    session.set_rotation(0, 0, 0)
    assert tuple(viewer.dims.order) == order_for(session.slice_axis) == order_for(0)
    session.set_rotation(30, 0, 0)
    th.settle_canvas(viewer)
    assert session.contours["synthetic"].frame is None
    from test_turned_view import _check_plane

    _check_plane(viewer, session)


def test_mirror_and_a_half_turn_reach_all_eight_sagittal_pictures(viewer, registry):
    """Slicing along the mirror axis, the mirror flips no picture; spins reach
    four, and a half turn about the vertical reaches the other four."""
    from viewer_harness import canvas_position

    session = _scene(viewer, registry, axis=0, mirrored=True)
    contour = session.contours["synthetic"]
    surface = session.surfaces["synthetic"]
    a, b, c = (surface.meshset.centroid(i) for i in range(3))
    pictures = set()
    for turn in (0.0, 180.0):
        for spin in (0.0, 90.0, 180.0, 270.0):
            session.set_rotation(spin, 0.0, turn)
            th.settle_canvas(viewer)
            # The screen map of the plane's two in-plane mesh directions.
            p = [np.asarray(canvas_position(viewer, th.mesh_to_world(contour, x)))
                 for x in (a, b, c)]
            m = np.column_stack([p[1] - p[0], p[2] - p[0]])
            pictures.add(tuple(np.sign(np.round(m.ravel(), 6))) + (np.sign(np.linalg.det(m)),))
    assert len(pictures) == 8


def test_hover_names_the_compartment_on_an_oblique_section(viewer, registry):
    session = _scene(viewer, registry)
    contour = session.contours["synthetic"]
    contour.set_fills({0, 1, 2})
    names = contour.meshset.names
    for angles in ((0, 37, 0), (40, -20, 70)):
        session.set_rotation(*angles)
        th.settle_canvas(viewer)
        assert contour.paths
        for i, loop in enumerate(contour.paths):
            owner = contour._shape_index[i]
            inside = np.asarray(loop, float).mean(axis=0)
            got = hover(viewer, contour.layer.data_to_world(inside))
            assert got == f"synthetic: {names[owner]}", (angles, got)


def test_nothing_of_the_oblique_path_stays_at_rest(viewer, registry):
    from napari.components.layerlist import LayerList
    from viewer_harness import handler_counts

    from lobemap.viewer import images, rotation

    session = _scene(viewer, registry, multiscale=True)
    counts = handler_counts(viewer)
    hooks = list(getattr(viewer._layer_slicer, "_lobemap_before", []))
    session.set_rotation(0, 37, 0)
    viewer.dims.ndisplay = 3
    viewer.dims.ndisplay = 2
    session.set_rotation(0, 0, 0)
    assert handler_counts(viewer) == counts
    assert list(getattr(viewer._layer_slicer, "_lobemap_before", [])) == hooks
    assert type(viewer.layers) is LayerList
    assert all(not hasattr(layer.data[0], "_image") for layer in session.images)
    assert all(layer not in images._HELD for layer in session.images)
    assert session.contours["synthetic"].frame is None
    assert rotation.owner(viewer) is session.turned
