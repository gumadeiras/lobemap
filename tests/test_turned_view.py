"""Turning the view, measured on what is drawn, in a synthetic scene.

No fetched data (`turned_harness`): three ellipsoid compartments over three
ramp images, whose value at a point names the specimen point shown there.
The real spaces are checked in `test_turned_spaces.py`.

- 2D spin: the image and the contours are one plane, the exact section of
  the meshes, turned counterclockwise about the view's center; no slider
  moves, Home frames the section as unturned, napari keeps its level.
- 3D: the camera turns from Home; no layer moves; surfaces stay lit from
  outside; both triads stay truthful; Home is Home turned.
- Mode trips keep the turn; rest gives back the view to the bit and leaves
  nothing installed; hover names what is under the cursor.
"""

from __future__ import annotations

import numpy as np
import pytest
import turned_harness as th
from viewer_harness import canvas_position, hover, pump

napari = pytest.importorskip("napari")


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
    if mirrored:
        session.set_mirror(True)
    th.through_middle(viewer, axis, session.contours["synthetic"])
    th.settle_canvas(viewer)
    return session


def _check_plane(viewer, session, tol_um=2e-4):
    """The drawn loops are trimesh's section of the meshes by the plane on
    screen, and the images under every loop point show that mesh point.

    The plane is taken into mesh coordinates through the contour layer's
    own transform, and its cutting frame when the view is turned across the
    grid (`th.plane_in_mesh`). Under a loop point, napari's nearest texel
    is within half a texel of it, on each texel axis (`th.texel_reach`).
    """
    contour = session.contours["synthetic"]
    origin, normal = th.plane_in_mesh(viewer, contour)
    loops = th.loops_in_mesh(contour, th.to_mesh(contour))
    assert loops, "nothing drawn"
    by_owner: dict[int, list] = {}
    for owner, loop in loops:
        by_owner.setdefault(owner, []).append(loop)
    for owner, drawn in by_owner.items():
        want = th.trimesh_loops(contour.meshset, owner, origin, normal)
        assert th.hausdorff(drawn, want) <= tol_um, owner
    reach = th.texel_reach(viewer, contour)
    top = np.asarray(th.SHAPE) - 2.01
    for _owner, loop in loops:
        for m in loop[:: max(1, len(loop) // 12)]:
            index = (m - th.TRANSLATE) / th.SCALE
            if np.any(index < 1.01) or np.any(index > top):
                continue                    # outside the image, or at its edge
            w = th.mesh_to_world(contour, m)
            for k, image in enumerate(session.images):
                got = th.image_index_at(image, w)
                assert got is not None
                want = (m[k] - th.TRANSLATE[k]) / th.SCALE[k]
                # float32 ramps: a millionth of a voxel of rounding.
                assert abs(got - want) <= reach[k] + 1e-4, (k, got, want)


_check_plane_oblique = _check_plane


def _screen_angle(viewer, a, b) -> float:
    """Direction on screen from world point a to b, counterclockwise from right."""
    pa, pb = np.asarray(canvas_position(viewer, a)), np.asarray(canvas_position(viewer, b))
    dx, dy = pb - pa
    return float(np.degrees(np.arctan2(-dy, dx)))


@pytest.mark.parametrize("axis", [2, 0])
@pytest.mark.parametrize("mirrored", [False, True])
def test_a_spun_slice_is_one_exact_plane_turned_counterclockwise(viewer, registry, axis,
                                                                  mirrored):
    session = _scene(viewer, registry, axis, mirrored)
    surface = session.surfaces["synthetic"]
    contour = session.contours["synthetic"]
    # Two specimen points, through the contour layer: the mirror included.
    a, b = (np.asarray(contour.layer.data_to_world(surface.meshset.centroid(i)), float)
            for i in (0, 1))
    before = _screen_angle(viewer, a, b)
    for spin in (37.0, 90.0, 180.0, -123.0):
        session.set_rotation(spin, 0, 0)
        th.settle_canvas(viewer)
        _check_plane(viewer, session)
        contour = session.contours["synthetic"]
        # The same two specimen points, through the contour layer.
        pa = contour.layer.data_to_world(surface.meshset.centroid(0))
        pb = contour.layer.data_to_world(surface.meshset.centroid(1))
        turned = _screen_angle(viewer, pa, pb) - before
        assert (turned - spin + 180.0) % 360.0 - 180.0 == pytest.approx(0.0, abs=1e-6)
    assert session.rotation == (-123.0, 0.0, 0.0)


def test_a_spin_moves_no_slider_and_rest_gives_back_the_view_to_the_bit(viewer, registry):
    session = _scene(viewer, registry, axis=1, mirrored=True, multiscale=True)
    before, pixels = th.state(viewer), th.render(viewer)
    ranges, points = before["range"], before["point"]
    # A spin box held down: 1..90 degrees, then rest.
    for spin in range(1, 91):
        session.set_rotation(float(spin), 0, 0)
        now = th.state(viewer)
        assert now["range"] == ranges and now["point"] == points
    th.settle_canvas(viewer)
    session.set_rotation(0, 0, 0)
    th.settle_canvas(viewer)
    assert th.state(viewer) == before
    assert np.array_equal(th.render(viewer), pixels)
    # And after other edits while turned: a step, the mirror, back again.
    session.set_rotation(30, 0, 0)
    axis = int(viewer.dims.order[0])
    viewer.dims.set_current_step(axis, viewer.dims.current_step[axis] + 3)
    session.set_mirror(False)
    session.set_mirror(True)
    session.set_rotation(0, 0, 0)
    th.settle_canvas(viewer)
    assert th.state(viewer) == before
    assert np.array_equal(th.render(viewer), pixels)


def test_home_in_2d_frames_a_spun_section_as_unturned(viewer, registry):
    session = _scene(viewer, registry)
    viewer.reset_view()
    zoom = viewer.scene.camera.zoom
    middle = np.asarray(viewer.dims.point, float)
    middle[list(viewer.dims.displayed)] = np.asarray(viewer.scene.camera.center)[-2:]
    want = [(middle[k] - th.TRANSLATE[k]) / th.SCALE[k] for k in range(3)]
    for spin in (45.0, 90.0, 130.0):
        session.set_rotation(spin, 0, 0)
        viewer.scene.camera.zoom = zoom / 3.0
        session.home()
        assert viewer.scene.camera.zoom == pytest.approx(zoom, rel=1e-9)
        # The scene's middle is at the center of the view.
        center = np.asarray(viewer.dims.point, float)
        center[list(viewer.dims.displayed)] = np.asarray(viewer.scene.camera.center)[-2:]
        got = [th.image_index_at(image, center) for image in session.images]
        assert np.allclose(got, want, atol=0.5 + 1e-6)


def test_a_spin_never_makes_napari_pick_a_coarser_level(viewer, registry):
    session = _scene(viewer, registry, multiscale=True)
    image = session.images[0]
    base = viewer.scene.camera.zoom
    for factor in np.linspace(0.6, 3.0, 13):
        session.set_rotation(0, 0, 0)
        viewer.scene.camera.zoom = base * factor
        th.settle_canvas(viewer)
        unturned = image.data_level
        for spin in (30.0, 45.0):
            session.set_rotation(spin, 0, 0)
            th.settle_canvas(viewer)
            assert image.data_level <= unturned, (factor, spin)


def test_3d_turns_the_camera_from_home_and_moves_no_layer(viewer, registry):
    from viewer_harness import node_determinant, shaded_normals

    from lobemap.core.model import anatomical_axes
    from lobemap.viewer.axes import _ANATOMY_ATTR, _vispy_axes_overlay
    from lobemap.viewer.rotation import screen_matrix, turned_view

    session = th.build(viewer, registry)
    viewer.dims.ndisplay = 3
    th.settle_canvas(viewer)
    surface = session.surfaces["synthetic"]
    surface.show_all()
    viewer.reset_view()
    th.settle_canvas(viewer)
    camera = viewer.scene.camera
    view0, up0 = np.asarray(camera.view_direction), np.asarray(camera.up_direction)
    right0 = np.cross(view0, up0)
    center = np.asarray(camera.center, float)
    c_px = np.asarray(canvas_position(viewer, center))
    zoom = camera.zoom
    det0 = node_determinant(viewer, surface)
    outward0 = shaded_normals(viewer, surface)[1]
    placed = [np.asarray(layer._transforms[1:].simplified.affine_matrix)
              for layer in viewer.layers]
    points = np.array([surface.meshset.centroid(i) for i in range(3)]
                      + [th.TRANSLATE, th.TRANSLATE + th.SCALE * np.array(th.SHAPE)])
    frame = anatomical_axes(registry.spaces["GRABE"])
    for angles in [(37, 0, 0), (0, 37, 0), (0, 0, 37), (15, -60, 120), (90, 45, -30),
                   (180, 0, 0), (0, 180, 0)]:
        session.set_rotation(*angles)
        th.settle_canvas(viewer)
        rel = points - center
        home = np.column_stack([rel @ right0, rel @ up0, rel @ -view0])
        turned = home @ screen_matrix(angles).T
        want = c_px + zoom * np.column_stack([turned[:, 0], -turned[:, 1]])
        got = np.array([canvas_position(viewer, p) for p in points])
        # vispy maps in float32: a thousandth of a pixel.
        assert np.abs(got - want).max() < 1e-3, angles
        assert all(np.array_equal(p, np.asarray(layer._transforms[1:].simplified.affine_matrix))
                   for p, layer in zip(placed, viewer.layers, strict=True))
        assert node_determinant(viewer, surface) == pytest.approx(det0)
        assert shaded_normals(viewer, surface)[1] == pytest.approx(outward0)
        # Each triad arrow points where its label says, on screen.
        overlay = _vispy_axes_overlay(viewer)
        for node, direction in ((getattr(overlay, _ANATOMY_ATTR), lambda s: frame[s]),
                                (overlay.node.axes, lambda s: np.eye(3)["xyz".index(s)])):
            for label, drawn in _label_directions(node).items():
                vec = np.asarray(direction(label), float)
                on_screen = (np.asarray(canvas_position(viewer, center + 10 * vec))
                             - np.asarray(canvas_position(viewer, center)))
                if np.linalg.norm(on_screen) > 1e-3 * 10 * zoom:
                    cos = drawn @ on_screen / np.linalg.norm(drawn) / np.linalg.norm(on_screen)
                    assert cos > np.cos(np.radians(1.0)), (angles, label)
        # Home, after a free move, is Home turned by the angles.
        camera.angles = (12.0, -33.0, 71.0)
        viewer.reset_view()
        want_v, want_u = turned_view(view0, up0, angles)
        assert np.allclose(camera.view_direction, want_v, atol=1e-6)
        assert np.allclose(camera.up_direction, want_u, atol=1e-6)
        # Setting the angles the scene already has puts the camera there too.
        camera.angles = (40.0, 10.0, -20.0)
        session.set_rotation(*angles)
        assert np.allclose(camera.view_direction, want_v, atol=1e-6)


def _label_directions(node) -> dict[str, np.ndarray]:
    """Canvas direction of each label of an Axes visual, from its origin."""
    text = node.text
    labels = [text.text] if isinstance(text.text, str) else list(text.text)
    to_canvas = text.get_transform("visual", "canvas")
    origin = np.asarray(node.get_transform("visual", "canvas").map([0, 0, 0, 1]), float)
    origin = origin[:2] / origin[3]
    out = {}
    for k, label in enumerate(labels):
        p = np.asarray(to_canvas.map(np.r_[np.asarray(text.pos, float)[k][:3], 1.0]), float)
        out[label] = p[:2] / p[3] - origin
    return out


def test_the_turn_survives_trips_between_2d_and_3d(viewer, registry):
    """3D faces Home turned and moves no layer; 2D comes back to the same
    turned plane, framed as napari frames it unturned after a trip: napari
    fits the view on every change of mode."""
    from lobemap.viewer.rotation import turned_view
    from lobemap.viewer.view import orient_anterior

    session = _scene(viewer, registry)
    # An unturned trip first: how large 2D comes back without a turn.
    viewer.dims.ndisplay = 3
    viewer.dims.ndisplay = 2
    th.settle_canvas(viewer)
    zoom_unturned = viewer.scene.camera.zoom
    for angles in ((37, 0, 0), (37, 20, -35)):
        session.set_rotation(*angles)
        th.settle_canvas(viewer)
        plane = viewer.dims.point[int(viewer.dims.order[0])]
        states = []
        for _ in range(3):
            viewer.dims.ndisplay = 3
            th.settle_canvas(viewer)
            camera = viewer.scene.camera
            saved = tuple(camera.angles)
            orient_anterior(viewer, registry.spaces["GRABE"], angles=(0, 0, 0))
            v0, u0 = np.asarray(camera.view_direction), np.asarray(camera.up_direction)
            camera.angles = saved
            want_v, want_u = turned_view(v0, u0, angles)
            assert np.allclose(camera.view_direction, want_v, atol=1e-6)
            assert np.allclose(camera.up_direction, want_u, atol=1e-6)
            for layer in session.affine_layers():
                assert np.allclose(layer.affine.affine_matrix, np.eye(4))
            for image in session.images:
                assert isinstance(image.data, np.ndarray)
            viewer.dims.ndisplay = 2
            th.settle_canvas(viewer)
            assert viewer.dims.point[int(viewer.dims.order[0])] == plane
            assert viewer.scene.camera.zoom == pytest.approx(zoom_unturned, rel=1e-9)
            _check_plane_oblique(viewer, session)
            states.append(th.state(viewer))
        assert states[0] == states[1] == states[2]
        assert session.rotation == tuple(float(a) for a in angles)


def test_hover_names_the_compartment_under_the_cursor_while_turned(viewer, registry):
    session = _scene(viewer, registry)
    contour = session.contours["synthetic"]
    contour.set_fills({0, 1, 2})
    names = contour.meshset.names
    for spin in (0.0, 45.0, 160.0):
        session.set_rotation(spin, 0, 0)
        th.settle_canvas(viewer)
        seen = set()
        for i, loop in enumerate(contour.paths):
            owner = contour._shape_index[i]
            inside = np.asarray(loop, float).mean(axis=0)
            got = hover(viewer, contour.layer.data_to_world(inside))
            assert got == f"synthetic: {names[owner]}", (spin, got)
            seen.add(owner)
        assert seen
    viewer.dims.ndisplay = 3
    surface = session.surfaces["synthetic"]
    for angles in ((0, 0, 0), (15, -60, 120), (90, 45, -30)):
        session.set_rotation(*angles)
        for i in range(3):
            surface.set_selection({i})
            th.settle_canvas(viewer)
            got = hover(viewer, surface.layer.data_to_world(surface.meshset.centroid(i)))
            assert got == f"synthetic: {names[i]}", (angles, got)


def test_rest_and_teardown_leave_nothing_of_the_turn_installed(viewer, registry):
    from napari.components.layerlist import LayerList
    from viewer_harness import handler_counts

    from lobemap.viewer import rotation

    session = _scene(viewer, registry)
    counts = handler_counts(viewer)
    callbacks = len(viewer.dims.events.ndisplay.callbacks)
    session.set_rotation(0, 0, 0)
    assert handler_counts(viewer) == counts
    for angles in [(30, 0, 0), (0, 20, 0)]:
        session.set_rotation(*angles)
        viewer.dims.ndisplay = 3
        viewer.dims.ndisplay = 2
        session.set_rotation(0, 0, 0)
        assert handler_counts(viewer) == counts
        assert len(viewer.dims.events.ndisplay.callbacks) == callbacks
        assert type(viewer.layers) is LayerList
        assert all("_update_draw" not in layer.__dict__ for layer in viewer.layers)
    session.set_rotation(30, 10, 0)
    assert rotation.owner(viewer) is session.turned
    session.teardown()
    assert type(viewer.layers) is LayerList
    assert rotation.owner(viewer) is None
    assert len(viewer.dims.events.ndisplay.callbacks) < callbacks
