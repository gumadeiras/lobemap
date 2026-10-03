"""A scene built from synthetic data, and readers for what a turned view draws.

No fetched data: three closed meshes, and image layers whose value at every
voxel is that voxel's index along one axis -- a ramp. Trilinear
interpolation of a ramp is exact, and the nearest voxel is within half a
voxel of it, so the value an image shows at a point says exactly which
specimen point it is showing there. The scene is assembled from the same
parts `viewer.app.load_space` assembles a space from -- `SceneSession`,
`AtlasSurface`, `ContourOverlay`, the display mode, picking and Home -- and
uses a registered space's anatomy, which is metadata and needs no data.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np

#: Where the synthetic image sits: voxel size and origin, um, per array axis.
SCALE = np.array([0.8, 0.7, 1.2])
TRANSLATE = np.array([100.0, 150.0, 30.0])
SHAPE = (60, 56, 40)

#: The synthetic compartments: name, center (um), semi-axes (um).
BODIES = (
    ("alpha", (114.0, 162.0, 52.0), (9.0, 6.0, 12.0)),
    ("beta", (135.0, 180.0, 48.0), (7.0, 9.0, 8.0)),
    ("gamma", (128.0, 163.0, 61.0), (5.0, 4.0, 6.0)),
)


def meshset():
    """Three ellipsoids, as closed meshes of different sizes and places."""
    import trimesh

    from lobemap.core.meshfmt import MeshSet

    parts = []
    for name, center, axes in BODIES:
        sphere = trimesh.creation.icosphere(subdivisions=3, radius=1.0)
        v = np.asarray(sphere.vertices) * np.asarray(axes) + np.asarray(center)
        parts.append((name, v.astype(np.float32), np.asarray(sphere.faces)))
    return MeshSet.from_parts(parts)


def ramp(axis: int, shape=SHAPE) -> np.ndarray:
    """A volume whose value is each voxel's index along `axis`."""
    index = np.arange(shape[axis], dtype=np.float32)
    view = [1, 1, 1]
    view[axis] = shape[axis]
    return np.ascontiguousarray(np.broadcast_to(index.reshape(view), shape))


class _Registry:
    """What a scene reads of the registry: the spaces, and one atlas."""

    def __init__(self, registry) -> None:
        self.spaces = registry.spaces
        self.atlases = {"synthetic": None}

    @staticmethod
    def primary_atlas(_space):
        return SimpleNamespace(id="synthetic")


def build(viewer, registry, space: str = "GRABE", multiscale: bool = False):
    """A synthetic scene in `viewer`, wired as `load_space` wires a space.

    Returns the session; its images are the x, y and z ramps, in that order.
    `multiscale` makes the ramps two-level pyramids, as the stains are.
    """
    from lobemap.viewer.app import install_display_mode, install_picking
    from lobemap.viewer.contours import install as install_contours
    from lobemap.viewer.layers import AtlasSurface
    from lobemap.viewer.parts import make_contour
    from lobemap.viewer.scene import SceneSession
    from lobemap.viewer.view import install_home_orientation

    session = SceneSession(viewer, _Registry(registry), space)
    for axis in range(3):
        data = ramp(axis)
        if multiscale:
            data = [data, np.ascontiguousarray(data[::2, ::2, ::2])]
        layer = viewer.add_image(data, multiscale=multiscale, scale=SCALE,
                                 translate=TRANSLATE, name=f"ramp {'xyz'[axis]}",
                                 colormap="gray", contrast_limits=(0, max(SHAPE)),
                                 interpolation2d="nearest")
        layer.metadata["lobemap"] = {"kind": "image", "asset": layer.name}
        session.images.append(layer)
    mesh = meshset()
    colors = np.array([[1.0, 0.0, 0.0, 1.0], [0.0, 1.0, 0.0, 1.0], [0.0, 0.0, 1.0, 1.0]])
    surface = AtlasSurface(viewer, mesh, "synthetic", colors=colors, visible=False,
                           compact_delay_ms=0)
    contour = make_contour(viewer, surface, ("#ff0000", 0.15), False)
    session.surfaces = {"synthetic": surface}
    session.contours = {"synthetic": contour}
    handlers = install_contours(viewer, session.contours)
    contour.handlers = session.contour_handlers = handlers
    session.callbacks += install_picking(viewer, session.surfaces, session.contours)
    session.handlers += install_display_mode(viewer, session.surfaces, session.contours,
                                             session.images, session=session)
    install_home_orientation(viewer, registry.spaces[space],
                             reflect_axis=session.reflect_axis)
    return session


def through_middle(viewer, axis: int = 2, contour=None) -> None:
    """Fit, then slice along `axis` through the largest body's center and
    center the view on it: the pivot a turn keeps where it is. Through
    `contour`'s layer, if given, which carries the mirror."""
    from lobemap.viewer.view import fit_view

    fit_view(viewer)
    # The largest body's center: every plane through it cuts it.
    pivot = np.asarray(BODIES[0][1], float)
    if contour is not None:
        pivot = np.asarray(contour.layer.data_to_world(pivot), float)
    viewer.dims.set_point(axis, float(pivot[axis]))
    center = list(viewer.scene.camera.center)
    center[-2:] = pivot[list(viewer.dims.displayed)]
    viewer.scene.camera.center = tuple(center)


def image_index_at(image, world) -> float | None:
    """The value -- the ramp's index -- an image shows at a world point."""
    value = image.get_value(world, world=True)
    if isinstance(value, tuple):            # a pyramid: (level, value)
        value = value[1]
    return None if value is None else float(value)


def loops_in_mesh(contour, to_mesh=None) -> list[tuple[int, np.ndarray]]:
    """(compartment, loop in mesh coordinates) for every loop drawn.

    `to_mesh` takes the contour layer's data coordinates to the meshes'
    (None: they are the same, as for an axis-aligned or spun cut).
    """
    from viewer_harness import contour_loops

    out = []
    for owner, loop in contour_loops(contour):
        pts = np.asarray(loop, float)
        out.append((owner, pts if to_mesh is None else to_mesh(pts)))
    return out


def trimesh_loops(meshset, index: int, origin, normal) -> list[np.ndarray]:
    """trimesh's section of one compartment by a plane, as closed loops."""
    import trimesh

    v, f = meshset.compartment(index)
    section = trimesh.Trimesh(vertices=v, faces=f, process=False).section(
        plane_origin=np.asarray(origin, float), plane_normal=np.asarray(normal, float))
    if section is None:
        return []
    return [np.asarray(p, float) for p in section.discrete if len(p) > 2]


def hausdorff(a, b) -> float:
    from scipy.spatial import cKDTree

    a, b = np.vstack(a), np.vstack(b)
    return float(max(cKDTree(b).query(a)[0].max(), cKDTree(a).query(b)[0].max()))


def screen_frame(viewer) -> tuple[np.ndarray, np.ndarray]:
    """2D: world directions of screen right and screen up, and the focus.

    From napari's own canvas mapping: right is the canvas x axis, up is
    minus the canvas y axis.
    """
    from viewer_harness import canvas_position

    dims = viewer.dims
    point = np.array(dims.point, float)
    shown = list(dims.displayed)
    point[shown] = np.asarray(viewer.scene.camera.center, float)[-2:]
    out = []
    for k in shown:
        step = np.zeros(3)
        step[k] = 1.0
        a = np.asarray(canvas_position(viewer, point))
        b = np.asarray(canvas_position(viewer, point + step))
        out.append(b - a)
    # out[i] is the canvas motion for +1 along displayed axis i.
    canvas = np.array(out)                     # rows: displayed axes; cols: canvas x, y
    right = np.zeros(3)
    up = np.zeros(3)
    inverse = np.linalg.inv(canvas.T)          # canvas (x, y) -> displayed axes
    right[shown] = inverse @ np.array([1.0, 0.0])
    up[shown] = inverse @ np.array([0.0, -1.0])
    return right / np.linalg.norm(right), up / np.linalg.norm(up), point


def assert_on_the_plane(viewer, session, tol_um=2e-4) -> None:
    """The drawn loops are trimesh's section of the meshes by the plane on
    screen, and the images under every loop point show that mesh point.

    The plane is taken into mesh coordinates through the contour layer's
    own transform, and its cutting frame when the view is turned across the
    grid (`plane_in_mesh`). Under a loop point, napari's nearest texel
    is within half a texel of it, on each texel axis (`texel_reach`).
    """
    contour = session.contours["synthetic"]
    origin, normal = plane_in_mesh(viewer, contour)
    loops = loops_in_mesh(contour, to_mesh(contour))
    assert loops, "nothing drawn"
    by_owner: dict[int, list] = {}
    for owner, loop in loops:
        by_owner.setdefault(owner, []).append(loop)
    for owner, drawn in by_owner.items():
        want = trimesh_loops(contour.meshset, owner, origin, normal)
        assert hausdorff(drawn, want) <= tol_um, owner
    reach = texel_reach(viewer, contour)
    top = np.asarray(SHAPE) - 2.01
    for _owner, loop in loops:
        for m in loop[:: max(1, len(loop) // 12)]:
            index = (m - TRANSLATE) / SCALE
            if np.any(index < 1.01) or np.any(index > top):
                continue                    # outside the image, or at its edge
            w = mesh_to_world(contour, m)
            for k, image in enumerate(session.images):
                got = image_index_at(image, w)
                assert got is not None
                want = (m[k] - TRANSLATE[k]) / SCALE[k]
                # float32 ramps: a millionth of a voxel of rounding.
                assert abs(got - want) <= reach[k] + 1e-4, (k, got, want)


def open_space(registry, space, ndisplay):
    """A viewer showing `space` as `lobemap view` opens it, and its session."""
    import napari

    from lobemap.viewer.app import load_space

    viewer = napari.Viewer(show=False, ndisplay=ndisplay)
    sess = load_space(viewer, registry, space, fit=False)
    settle_canvas(viewer)
    return viewer, sess


def center_on_the_atlas(viewer, sess) -> None:
    """Center the 2D view on the primary atlas, on a slider plane through it:
    the pivot a turn keeps, so the turned plane cuts the atlas."""
    name = sess.registry.primary_atlas(sess.space).id
    surface, contour = sess.surfaces[name], sess.contours[name]
    # The largest compartment's center: every plane through it cuts it.
    largest = int(np.argmax(np.diff(surface.meshset.vertex_offsets)))
    # Through the contour layer, which carries the mirror. At rest.
    middle = np.asarray(contour.layer.data_to_world(surface.meshset.centroid(largest)),
                        float)
    axis = int(viewer.dims.order[0])
    start, _stop, step = viewer.dims.range[axis]
    viewer.dims.set_current_step(axis, round((middle[axis] - start) / step))
    center = list(viewer.scene.camera.center)
    center[-2:] = middle[list(viewer.dims.displayed)]
    viewer.scene.camera.center = tuple(center)
    settle_canvas(viewer)


def contour_vs_trimesh(viewer, sess, to_mesh=None, tol_um=2e-4) -> int:
    """Every loop of the primary atlas against trimesh; the count compared."""
    name = sess.registry.primary_atlas(sess.space).id
    contour = sess.contours[name]
    axis = int(viewer.dims.order[0])
    shown = list(viewer.dims.displayed)
    world = np.zeros((3, 3))
    world[:, axis] = float(viewer.dims.point[axis])
    world[1, shown[0]] += 10.0
    world[2, shown[1]] += 10.0
    plane = np.array([contour.layer.world_to_data(w) for w in world], float)
    if to_mesh is not None:
        plane = to_mesh(plane)
    normal = np.cross(plane[1] - plane[0], plane[2] - plane[0])
    by_owner: dict[int, list] = {}
    for owner, loop in loops_in_mesh(contour, to_mesh):
        by_owner.setdefault(owner, []).append(loop)
    for owner, drawn in by_owner.items():
        want = trimesh_loops(contour.meshset, owner, plane[0], normal)
        assert want and hausdorff(drawn, want) <= tol_um, (sess.space, owner)
    return len(by_owner)


def screen_axes(viewer) -> np.ndarray:
    """3D: the world directions of screen right, screen up and toward the
    viewer, as rows, measured through vispy's own transform to the canvas.

    Right and up are the canvas x axis and minus its y axis; toward the
    viewer is minus the depth axis, which GL's depth test draws nearest.
    """
    canvas = viewer.window._qt_viewer.canvas
    transform = canvas.view.transform * canvas.view.scene.transform
    center = np.asarray(viewer.scene.camera.center, float)

    def canvas_of(world) -> np.ndarray:
        p = np.asarray(transform.map(np.r_[np.asarray(world, float)[::-1], 1.0]), float)
        return p[:3] / p[3]

    base = canvas_of(center)
    # Rows: canvas x, y and depth per unit along each world axis.
    rows = np.column_stack([canvas_of(center + e) - base for e in np.eye(3)])
    rows = rows / np.linalg.norm(rows, axis=1, keepdims=True)
    return np.array([rows[0], -rows[1], -rows[2]])


def label_directions(node) -> dict[str, np.ndarray]:
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


def assert_triads_point_where_they_say(viewer, space) -> int:
    """Each shown arrow of both corner triads points, on the canvas, where
    what it names is drawn, within a degree; how many were checked.

    napari's names the image's axes x, y and z, drawn as the scene's layers
    place them -- turned in the plane, mirrored -- which a layer's own
    transform says; the second, in 3D, the anatomical poles, reflected with
    the scene (`core.model.anatomical_triad`).
    """
    from viewer_harness import canvas_position

    from lobemap.core.model import anatomical_axes
    from lobemap.viewer.axes import _ANATOMY_ATTR, _vispy_axes_overlay
    from lobemap.viewer.rotation import owner
    from lobemap.viewer.view import MIRROR_AXIS

    overlay = _vispy_axes_overlay(viewer)
    session = owner(viewer).session
    frame = {k: np.asarray(v, float) for k, v in anatomical_axes(space).items()}
    if session.mirrored:
        for v in frame.values():
            v[MIRROR_AXIS] *= -1.0
    point = np.asarray(viewer.dims.point, float)
    point[list(viewer.dims.displayed)] = np.asarray(
        viewer.scene.camera.center, float)[-len(viewer.dims.displayed):]
    layer = session.affine_layers()[0]
    data = np.asarray(layer.world_to_data(point), float)

    def image_axis(label) -> np.ndarray:
        step = np.eye(3)["xyz".index(label)]
        return (np.asarray(layer.data_to_world(data + step), float)
                - np.asarray(layer.data_to_world(data), float))

    nodes = [(overlay.node.axes, image_axis)]
    anatomy = getattr(overlay, _ANATOMY_ATTR, None)
    if anatomy is not None:
        nodes.append((anatomy, frame.__getitem__))
    checked = 0
    for node, direction in nodes:
        if not node.visible:
            continue
        for label, drawn in label_directions(node).items():
            vec = np.asarray(direction(label), float)
            on_screen = (np.asarray(canvas_position(viewer, point + 10 * vec))
                         - np.asarray(canvas_position(viewer, point)))
            if np.linalg.norm(on_screen) < 1e-3 * 10 * viewer.scene.camera.zoom:
                continue                        # along the line of sight
            cos = drawn @ on_screen / np.linalg.norm(drawn) / np.linalg.norm(on_screen)
            assert cos > np.cos(np.radians(1.0)), (label, np.degrees(np.arccos(cos)))
            checked += 1
    return checked


def settle_canvas(viewer) -> None:
    """Put a hidden canvas's view box in step with the canvas, and draw once.

    A hidden window never resizes its canvas's central widget: napari's view
    box stays 600x800 inside an 800x600 canvas until one resize event, and
    napari picks pyramid levels only as it draws.
    """
    from viewer_harness import pump

    canvas = viewer.window._qt_viewer.canvas
    scene = canvas._scene_canvas
    scene.events.resize(size=scene.size)
    pump()
    canvas.on_draw(None)
    pump()


def render(viewer) -> np.ndarray:
    """RGB of the canvas, rendered offscreen once napari has drawn."""
    from viewer_harness import pump

    pump()
    canvas = viewer.window._qt_viewer.canvas
    canvas.on_draw(None)
    return np.asarray(canvas._scene_canvas.render())[..., :3]


def picture(viewer) -> np.ndarray:
    """`render`, without the corner triads and their box, which stay in their
    corner rather than flip, and are checked on their own
    (`assert_triads_point_where_they_say`)."""
    overlay = viewer.canvas.overlays["axes"]
    overlay.visible = False
    try:
        return render(viewer)
    finally:
        overlay.visible = True


def pixel_at(viewer, pixels, x, y) -> np.ndarray:
    """The rendered pixel at canvas point (x, y): the framebuffer can have
    more pixels than the canvas has points."""
    scale = pixels.shape[1] / viewer.window._qt_viewer.canvas._scene_canvas.size[0]
    return pixels[int(y * scale), int(x * scale)]


def assert_upside_down(got, upright, at_most=0.002) -> None:
    """`got` is the `upright` picture upside down, to the pixel but for
    `at_most` of them, on the edges of what is drawn, where GL's rule for a
    pixel centered on an edge breaks the tie the other way."""
    assert upright.std() > 0, "nothing drawn"
    off = np.any(np.abs(got.astype(int) - upright[::-1].astype(int)) > 2, axis=-1)
    assert off.mean() <= at_most, off.mean()


def brightness(pixels) -> float:
    """Mean brightness of what is drawn on the black canvas."""
    drawn = pixels.sum(axis=-1) > 30
    assert drawn.mean() > 0.001, "nothing drawn"
    return float(pixels[drawn].mean())


def placed(viewer) -> dict:
    """`state` but for each layer's corner pixels, which in 3D are the box
    napari spans between two corners of the screen, and so follow a flip."""
    out = state(viewer)
    out["layers"] = [layer[:4] for layer in out["layers"]]
    return out


def state(viewer) -> dict:
    """What a view is, as numbers: dims, camera, and every layer's placement."""
    camera = viewer.scene.camera
    dims = viewer.dims
    return {
        "order": tuple(dims.order),
        "point": tuple(float(p) for p in dims.point),
        "range": tuple(tuple(float(x) for x in r) for r in dims.range),
        "labels": tuple(dims.axis_labels),
        "center": tuple(float(c) for c in camera.center),
        "zoom": float(camera.zoom),
        "angles": tuple(float(a) for a in camera.angles),
        "layers": [(layer.name, bool(layer.visible),
                    np.asarray(layer._transforms[1:].simplified.affine_matrix).tolist(),
                    getattr(layer, "_data_level", None),
                    np.asarray(getattr(layer, "corner_pixels", [])).tolist())
                   for layer in viewer.layers],
    }


def to_mesh(contour):
    """Contour-layer data to mesh coordinates: through its cutting frame, if any."""
    frame = contour.frame
    return None if frame is None else frame.inverse


def mesh_to_world(contour, m) -> np.ndarray:
    """World point at which a mesh point is drawn in 2D, through the contours."""
    frame = contour.frame
    q = np.asarray(m, float) if frame is None else frame.apply(np.asarray(m, float))
    return np.asarray(contour.layer.data_to_world(q), float)


def plane_in_mesh(viewer, contour) -> tuple[np.ndarray, np.ndarray]:
    """(origin, normal) of the plane on screen, in mesh coordinates.

    Three world points of the slider's plane, taken to the contour layer's
    data by its own transform and to the meshes by its frame.
    """
    axis = int(viewer.dims.order[0])
    shown = list(viewer.dims.displayed)
    world = np.zeros((3, 3))
    world[:, axis] = float(viewer.dims.point[axis])
    world[1, shown[0]] += 10.0
    world[2, shown[1]] += 10.0
    plane = np.array([contour.layer.world_to_data(w) for w in world], float)
    back = to_mesh(contour)
    if back is not None:
        plane = back(plane)
    return plane[0], np.cross(plane[1] - plane[0], plane[2] - plane[0])


def texel_reach(viewer, contour) -> np.ndarray:
    """How far, in image index along each array axis, napari's nearest texel
    can be from a point of the plane: half a texel along each texel axis.

    Texels lie along the displayed axes of the turned world, one image voxel
    apart; along the slider they are on its positions. Unturned or spun,
    the slider's step need not be the image's, and the nearest plane is up
    to half a voxel off, as at rest.
    """
    shown = list(viewer.dims.displayed)
    frame = contour.frame
    if frame is None:
        return np.full(3, 0.5)
    rotation = frame.matrix[:3, :3]
    # Mesh displacement per turned-world unit along each displayed axis.
    reach = 0.5 * np.abs(rotation.T[:, shown]) @ SCALE[shown]
    return reach / SCALE


def texels(viewer, image, contour, axis_of_ramp: int):
    """(value, expected) for every texel of an image's current 2D slice.

    Each texel's world position through napari's own transforms -- the
    tile it was read in and the layer's data-to-world -- taken to the
    specimen point through the contour layer (`plane_in_mesh`), whose ramp
    index is the value the texel must hold. Texels whose specimen point is
    outside the image are left out.
    """
    raw = np.asarray(image._slice.image.raw, float)
    tile = image._transforms["tile2data"]
    dims = viewer.dims
    axis = int(dims.order[0])
    shown = list(dims.displayed)
    index = np.asarray(image.world_to_data(dims.point), float)
    plane = np.round(index[axis])
    rows, cols = np.indices(raw.shape)
    full = np.zeros((raw.size, 3))
    full[:, shown[0]] = rows.ravel()
    full[:, shown[1]] = cols.ravel()
    data = np.asarray(tile(full), float)
    data[:, axis] = plane
    world = np.array([image.data_to_world(d) for d in data], float)
    q = np.array([contour.layer.world_to_data(w) for w in world], float)
    back = to_mesh(contour)
    m = q if back is None else back(q)
    want = (m - TRANSLATE) / SCALE
    # Not within a voxel of the edge, where a coarser level ends sooner and a
    # sample a hair outside is zero.
    inside = np.all((want >= 1.01) & (want <= np.asarray(SHAPE) - 2.01), axis=1)
    return raw.ravel()[inside], want[inside, axis_of_ramp]
