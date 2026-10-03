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
