"""The picture upside down, measured on what is drawn, in a synthetic scene.

No fetched data (`turned_harness`): three ellipsoid compartments, colored
red, green and blue, over three ramp images. The real spaces are checked
in `test_flip_spaces.py`.

The flip is a flip of the screen, top to bottom about the middle of the
view, after the turn and the mirror, made by the camera
(`view.show_upside_down`). So in every case -- 2D unturned, spun and cut
across the grid, 3D unturned and turned, with and without the mirror:

- the picture drawn is the upright one upside down, and nothing else
  moves: no slider, plane, camera center, zoom or angle, and no layer;
- the contours, fills and labels lie on the plane, and the labels read
  upright;
- the surfaces are lit from outside, through napari's GL resets;
- hover names what is drawn under the cursor;
- both corner triads point where their labels say;
- Fit to window and trips between 2D and 3D keep it;
- off, the view is exactly what it was;
- with the mirror, a front view is turned 180 degrees.
"""

from __future__ import annotations

import numpy as np
import pytest
import turned_harness as th
from viewer_harness import assert_renders_loops, canvas_position, hover, pump

napari = pytest.importorskip("napari")

#: (spin, tilt, turn): at rest, spun in the plane, and across the grid.
ANGLES_2D = ((0.0, 0.0, 0.0), (37.0, 0.0, 0.0), (20.0, 37.0, 15.0))
#: At Home, turned, and near the elevation route C's prototype lost.
ANGLES_3D = ((0.0, 0.0, 0.0), (25.0, 35.0, -50.0), (10.0, 84.0, 0.0))
#: Screen right, up and toward the viewer, flipped.
FLIP = np.array([[1.0], [-1.0], [1.0]])
SPACE = "GRABE"


@pytest.fixture
def viewer():
    v = napari.Viewer(show=False, ndisplay=2)
    yield v
    v.close()
    pump()


def _scene(viewer, registry, mirrored=False, ndisplay=2):
    """The synthetic scene, sliced through its largest body, or in 3D at
    Home with every compartment shown and the images hidden."""
    session = th.build(viewer, registry, SPACE)
    th.settle_canvas(viewer)
    if mirrored:
        session.set_mirror(True)
    if ndisplay == 3:
        viewer.dims.ndisplay = 3
        session.surfaces["synthetic"].show_all()
        for image in session.images:
            image.visible = False
        viewer.reset_view()
    else:
        th.through_middle(viewer, 2, session.contours["synthetic"])
    th.settle_canvas(viewer)
    return session


# -- 2D ------------------------------------------------------------------------


@pytest.mark.parametrize("mirrored", [False, True])
def test_a_slice_upside_down_is_the_same_slice_and_off_gives_it_back(viewer, registry,
                                                                      mirrored):
    session = _scene(viewer, registry, mirrored)
    contour = session.contours["synthetic"]
    contour.set_fills({0, 1, 2})
    for angles in ANGLES_2D:
        session.set_rotation(*angles)
        th.settle_canvas(viewer)
        before, upright = th.state(viewer), th.picture(viewer)
        session.set_flip(True)
        th.settle_canvas(viewer)
        assert session.flipped
        # Nothing moves but the picture: dims, camera, every layer's place.
        assert th.state(viewer) == before, angles
        th.assert_upside_down(th.picture(viewer), upright)
        th.assert_on_the_plane(viewer, session)
        assert_renders_loops(contour)
        session.set_flip(False)
        th.settle_canvas(viewer)
        assert th.state(viewer) == before
        assert np.array_equal(th.picture(viewer), upright), angles


@pytest.mark.parametrize("mirrored", [False, True])
def test_names_on_a_slice_upside_down_read_upright(viewer, registry, mirrored):
    """Each name is drawn upside down where its loop is, in letters that are
    not: its pixels match the upright name's, and not their mirror image.
    Unturned, spun and cut across the grid."""
    session = _scene(viewer, registry, mirrored)
    contour = session.contours["synthetic"]
    for image in session.images:
        image.visible = False
    contour.set_labels({0, 1, 2})
    text = contour.visual.text

    def crops() -> dict[str, np.ndarray]:
        th.settle_canvas(viewer)
        contour.visual.mesh.visible = False             # the names alone
        pixels = th.picture(viewer).sum(axis=-1).astype(float)
        scale = pixels.shape[1] / viewer.window._qt_viewer.canvas._scene_canvas.size[0]
        h, w = round(9 * scale), round(24 * scale)
        to_canvas = text.get_transform("visual", "canvas")
        out = {}
        for name, pos in zip(np.atleast_1d(text.text), np.asarray(text.pos, float),
                             strict=True):
            x, y = np.asarray(to_canvas.map(np.r_[pos[:2], 0.0, 1.0]))[:2] * scale
            row, col = round(y), round(x)
            if h <= row < pixels.shape[0] - h and w <= col < pixels.shape[1] - w:
                out[str(name)] = pixels[row - h:row + h + 1, col - w:col + w + 1]
        return out

    def corr(a, b) -> float:
        a, b = a - a.mean(), b - b.mean()
        return float((a * b).sum() / np.sqrt((a * a).sum() * (b * b).sum()))

    for angles in ANGLES_2D:
        session.set_rotation(*angles)
        upright = crops()
        assert upright, angles
        session.set_flip(True)
        flipped = crops()
        assert flipped.keys() == upright.keys(), angles
        for name, got in flipped.items():
            assert upright[name].std() > 0, name
            same, mirror_image = corr(got, upright[name]), corr(got, upright[name][::-1])
            assert same > 0.8 and mirror_image < same - 0.3, (angles, name, same,
                                                                 mirror_image)
        session.set_flip(False)


@pytest.mark.parametrize("mirrored", [False, True])
def test_hover_names_what_is_drawn_under_the_cursor_upside_down(viewer, registry, mirrored):
    session = _scene(viewer, registry, mirrored)
    contour = session.contours["synthetic"]
    contour.set_fills({0, 1, 2})
    for image in session.images:
        image.visible = False
    session.set_flip(True)
    names = contour.meshset.names
    for angles in ANGLES_2D:
        session.set_rotation(*angles)
        th.settle_canvas(viewer)
        pixels = th.picture(viewer)
        seen = set()
        for i, loop in enumerate(contour.paths):
            owner = contour._shape_index[i]
            inside = contour.layer.data_to_world(np.asarray(loop, float).mean(axis=0))
            x, y = canvas_position(viewer, inside)
            width, height = viewer.window._qt_viewer.canvas._scene_canvas.size
            if not (0 <= x < width and 0 <= y < height):
                continue                        # off the canvas
            # Drawn there, filled, upside down; and named there.
            assert th.pixel_at(viewer, pixels, x, y).sum() > 30, (angles, names[owner])
            assert hover(viewer, inside) == f"{names[owner]} — synthetic", angles
            seen.add(owner)
        assert seen, angles


@pytest.mark.parametrize("mirrored", [False, True])
def test_the_slice_triad_points_where_it_says_upside_down(viewer, registry, mirrored):
    session = _scene(viewer, registry, mirrored)
    session.set_flip(True)
    for angles in ANGLES_2D:
        session.set_rotation(*angles)
        th.settle_canvas(viewer)
        checked = th.assert_triads_point_where_they_say(viewer, registry.spaces[SPACE])
        # The poles' arrows on the section; napari's x/y arrows step aside.
        assert checked >= 2, angles


def test_fit_to_window_keeps_a_slice_upside_down(viewer, registry):
    session = _scene(viewer, registry)
    for angles in ANGLES_2D:
        session.set_rotation(*angles)
        session.home()
        th.settle_canvas(viewer)
        home, upright = th.state(viewer), th.picture(viewer)
        session.set_flip(True)
        viewer.scene.camera.zoom *= 2.5
        viewer.scene.camera.center = tuple(np.asarray(viewer.scene.camera.center) + 7.0)
        session.home()
        th.settle_canvas(viewer)
        assert session.flipped
        assert th.state(viewer) == home, angles
        th.assert_upside_down(th.picture(viewer), upright)
        session.set_flip(False)


# -- 3D ------------------------------------------------------------------------


@pytest.mark.parametrize("mirrored", [False, True])
def test_3d_upside_down_keeps_the_camera_and_lights_from_outside(viewer, registry,
                                                                   mirrored):
    from lobemap.viewer.napari_private import front_face

    session = _scene(viewer, registry, mirrored, ndisplay=3)
    surface = session.surfaces["synthetic"]
    for angles in ANGLES_3D:
        session.set_rotation(*angles)
        th.settle_canvas(viewer)
        axes, before, upright = th.screen_axes(viewer), th.state(viewer), th.picture(viewer)
        placed = th.placed(viewer)
        session.set_flip(True)
        th.settle_canvas(viewer)
        # The camera looks where it looked, with the screen's up turned over.
        assert np.allclose(th.screen_axes(viewer), FLIP * axes, atol=1e-6), angles
        assert th.placed(viewer) == placed, angles
        flipped = th.picture(viewer)
        # The upright picture upside down, its light too: lit from outside,
        # as upright, also after napari sets every layer's GL state anew. A
        # few pixels differ where the translucent surface overlaps itself.
        th.assert_upside_down(flipped, upright, at_most=0.02)
        assert th.brightness(flipped) == pytest.approx(th.brightness(upright), rel=0.05), angles
        surface.layer.blending = "opaque"
        surface.layer.blending = "translucent"
        order = list(viewer.layers)
        viewer.layers.move(viewer.layers.index(surface.layer), 0)
        assert th.brightness(th.picture(viewer)) == pytest.approx(th.brightness(flipped), rel=0.02)
        viewer.layers.move(0, order.index(surface.layer) + 1)
        assert list(viewer.layers) == order
        # The control: front faces as napari leaves them are lit from inside.
        front_face(viewer, surface.layer, False)
        assert th.brightness(th.picture(viewer)) < 0.8 * th.brightness(upright), angles
        front_face(viewer, surface.layer, True)
        session.set_flip(False)
        th.settle_canvas(viewer)
        assert th.state(viewer) == before
        assert np.array_equal(th.picture(viewer), upright), angles


@pytest.mark.parametrize("mirrored", [False, True])
def test_3d_hover_and_triads_upside_down(viewer, registry, mirrored):
    """Hover at the pixel where each compartment is drawn, in its own color,
    names it; both triads point where their labels say."""
    session = _scene(viewer, registry, mirrored, ndisplay=3)
    surface = session.surfaces["synthetic"]
    names = surface.meshset.names
    session.set_flip(True)
    for angles in ANGLES_3D:
        session.set_rotation(*angles)
        th.settle_canvas(viewer)
        assert th.assert_triads_point_where_they_say(viewer, registry.spaces[SPACE]) >= 4
        for i in range(3):
            surface.set_selection({i})
            th.settle_canvas(viewer)
            point = _surface_world(session, surface.meshset.centroid(i))
            color = th.pixel_at(viewer, th.picture(viewer), *canvas_position(viewer, point))
            assert int(np.argmax(color)) == i and color.max() > 30, (angles, i, color)
            assert hover(viewer, point) == f"{names[i]} — synthetic", (angles, i)
        surface.show_all()


@pytest.mark.parametrize("mirrored", [False, True])
def test_fit_to_window_faces_home_upside_down(viewer, registry, mirrored):
    session = _scene(viewer, registry, mirrored, ndisplay=3)
    camera = viewer.scene.camera
    for angles in ANGLES_3D:
        session.set_rotation(*angles)
        session.home()
        axes = th.screen_axes(viewer)
        session.set_flip(True)
        camera.angles = (12.0, -33.0, 71.0)
        session.home()
        assert session.flipped
        assert np.allclose(th.screen_axes(viewer), FLIP * axes, atol=1e-6), angles
        session.set_flip(False)


@pytest.mark.parametrize("mirrored", [False, True])
def test_trips_between_2d_and_3d_keep_the_picture_upside_down(viewer, registry, mirrored):
    """The view each mode comes back to is the upright one's, upside down,
    trip after trip: the regression route C's prototype had in 3D."""
    session = _scene(viewer, registry, mirrored)
    for angles in ((0.0, 0.0, 0.0), (20.0, 37.0, 15.0)):
        session.set_rotation(*angles)
        # Upright, after trips: what each mode comes back to. Two, since the
        # first can still move a slider of an axis 2D shows, not the plane.
        for _ in range(2):
            viewer.dims.ndisplay = 3
            th.settle_canvas(viewer)
            axes = th.screen_axes(viewer)
            viewer.dims.ndisplay = 2
            th.settle_canvas(viewer)
        state, upright = th.state(viewer), th.picture(viewer)
        session.set_flip(True)
        for _ in range(3):
            viewer.dims.ndisplay = 3
            th.settle_canvas(viewer)
            assert np.allclose(th.screen_axes(viewer), FLIP * axes, atol=1e-6), angles
            viewer.dims.ndisplay = 2
            th.settle_canvas(viewer)
            assert th.state(viewer) == state, angles
            th.assert_upside_down(th.picture(viewer), upright)
        session.set_flip(False)
        th.settle_canvas(viewer)
        assert np.array_equal(th.picture(viewer), upright)


# -- with the mirror -----------------------------------------------------------


@pytest.mark.parametrize("ndisplay", [2, 3])
def test_mirror_and_flip_turn_a_front_view_half_around(viewer, registry, ndisplay):
    """Each specimen point, drawn mirrored and upside down, is where the plain
    view draws it turned 180 degrees about one point of the screen."""
    session = _scene(viewer, registry, ndisplay=ndisplay)
    contour, surface = session.contours["synthetic"], session.surfaces["synthetic"]
    layer = surface.layer if ndisplay == 3 else contour.layer
    mesh = np.asarray(surface.meshset.vertices, float)[::25]
    if ndisplay == 2:
        # Points of the plane on screen.
        axis = int(viewer.dims.order[0])
        mesh = mesh.copy()
        mesh[:, axis] = contour.layer.world_to_data(viewer.dims.point)[axis]

    def drawn() -> np.ndarray:
        return np.array([canvas_position(viewer, layer.data_to_world(m)
                                         if ndisplay == 2 else _surface_world(session, m))
                         for m in mesh])

    plain = drawn()
    session.set_mirror(True)
    session.set_flip(True)
    if ndisplay == 3:
        session.home()
    th.settle_canvas(viewer)
    turned = drawn()
    pivot = (turned + plain).mean(axis=0) / 2.0
    assert np.abs(turned - (2.0 * pivot - plain)).max() < 1e-3
    assert np.ptp(plain, axis=0).min() > 50, "too few pixels to tell"


def _surface_world(session, point) -> np.ndarray:
    """Where the surfaces draw a mesh point: reflected with the scene."""
    from lobemap.viewer.view import MIRROR_AXIS

    out = np.array(point, float)
    if session.mirrored:
        out[MIRROR_AXIS] = 2.0 * session.mirror_center - out[MIRROR_AXIS]
    return out


def test_a_surface_keeps_its_front_face_through_napari_gl_resets(viewer):
    """`napari_private.front_face` sets vispy's GL front face on a surface's
    node and keeps it when napari sets the node's whole GL state anew, as it
    does on a change of blending or of the layer order."""
    from lobemap.viewer.napari_private import front_face, layer_visual

    viewer.dims.ndisplay = 3
    layer = viewer.add_surface((np.eye(3), np.array([[0, 1, 2]]), np.arange(3.0)))
    other = viewer.add_image(np.zeros((4, 4, 4), np.uint8))
    front_face(viewer, layer, True)
    assert layer_visual(viewer, layer).node._vshare.gl_state["front_face"] == "cw"
    layer.blending = "opaque"
    viewer.layers.move(viewer.layers.index(other), 0)
    assert layer_visual(viewer, layer).node._vshare.gl_state["front_face"] == "cw"
    front_face(viewer, layer, False)
    assert layer_visual(viewer, layer).node._vshare.gl_state["front_face"] == "ccw"
