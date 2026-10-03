"""Drive the real viewer the way a user does, and read back what it draws.

`launched` runs `lobemap.cli.main` end to end with only the window hidden
and the event loop stubbed. The readers below report what is rendered --
which layer is visible, which compartments its colors or shapes draw --
rather than what a widget claims, so a test can compare the two.
"""

from __future__ import annotations

import contextlib
import os
import time
from pathlib import Path

import numpy as np

REGISTRY = Path(__file__).resolve().parents[1] / "registry"
SPACES = ("FAFB14", "JRCFIB2018F", "JRCFIB2022M", "GRABE")


def data_root() -> Path:
    """The data the registry reads by default, wherever it is."""
    from lobemap.core.registry import default_data_root

    return Path(default_data_root(REGISTRY))


def pump(ms: float = 0) -> None:
    """Let Qt run: queued signals, timers, and deferred widget deletion."""
    from qtpy.QtCore import QCoreApplication, QEvent
    from qtpy.QtWidgets import QApplication

    end = time.perf_counter() + ms / 1000
    while True:
        QApplication.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        if time.perf_counter() >= end:
            return
        time.sleep(0.01)


@contextlib.contextmanager
def launched(monkeypatch, *argv):
    """Run `lobemap <argv>`; yield (exit code, viewer or None).

    The window is created hidden and never maximized -- `maximize` would
    show it -- and `napari.run` returns at once, so the viewer is left as
    the user would first see it. It is closed afterwards.
    """
    import napari

    from lobemap import cli

    created = []
    real = napari.Viewer

    def hidden(*args, **kwargs):
        kwargs["show"] = False
        viewer = real(*args, **kwargs)
        created.append(viewer)
        return viewer

    monkeypatch.setattr(napari, "Viewer", hidden)
    monkeypatch.setattr(napari, "run", lambda *a, **k: None)
    monkeypatch.setattr("lobemap.viewer.app.maximize", lambda viewer: False)
    monkeypatch.setenv("LOBEMAP_CRASH_LOG", os.devnull)
    try:
        code = cli.main(["--registry", str(REGISTRY), *argv])
        yield code, (created[0] if created else None)
    finally:
        for viewer in created:
            viewer.close()
        pump()


def dead_network(monkeypatch) -> None:
    """Make every download fail as a refused connection, so nothing leaves the host.

    Patched at `urlopen` rather than through proxy variables: urllib builds
    its default opener once per process, from the environment at the first
    download, so a proxy set here had no effect after any earlier test had
    downloaded.
    """
    import urllib.error
    import urllib.request

    def refuse(url, *args, **kwargs):
        raise urllib.error.URLError(ConnectionRefusedError(61, "Connection refused"))

    monkeypatch.setattr(urllib.request, "urlopen", refuse)


def switcher(viewer):
    from lobemap.viewer.switcher import SpaceSwitcher

    found = viewer.window._qt_window.findChildren(SpaceSwitcher)
    assert len(found) == 1, found
    return found[0]


def session(viewer):
    return switcher(viewer).session


def switch_to(viewer, space: str) -> None:
    """Pick `space` in the space menu, as a user would."""
    combo = switcher(viewer).combo
    combo.setCurrentIndex(combo.findData(space))
    pump()


def docks(viewer, title: str) -> list:
    from qtpy.QtWidgets import QDockWidget

    pump()
    return [d for d in viewer.window._qt_window.findChildren(QDockWidget)
            if d.windowTitle() == title]


def handler_counts(viewer) -> dict[str, int]:
    """Every hook a scene can leave behind on objects that outlive it."""
    canvas = viewer.window._qt_viewer.canvas
    out = {
        f"dims.{name}": len(getattr(viewer.dims.events, name).callbacks)
        for name in ("ndisplay", "current_step", "order", "point")
    }
    out.update({
        f"canvas.{name}": len(getattr(canvas.events, name).callbacks)
        for name in ("draw", "resize", "mouse_press", "mouse_wheel", "key_press")
    })
    out["viewer.mouse_move_callbacks"] = len(viewer.mouse_move_callbacks)
    out["viewer.mouse_drag_callbacks"] = len(viewer.mouse_drag_callbacks)
    return out


def layer_names(viewer) -> list[str]:
    return sorted(layer.name for layer in viewer.layers)


def stand_in_name(sess, name: str) -> str:
    """What the stand-in of the part `name` is called in the layer list."""
    from lobemap.viewer.deferred import STANDIN_NAME
    from lobemap.viewer.parts import part_title

    return STANDIN_NAME.format(title=part_title(sess.registry, sess.parts[name]))


# -- what is drawn --------------------------------------------------------


def contour_loops(contour) -> list[tuple[int, np.ndarray]]:
    """(compartment, loop) for every loop a contour overlay has on screen.

    Nothing unless its layer is on and its mesh visual is drawing: the
    loops are the overlay's, and `assert_renders_loops` checks that the
    vispy visuals draw exactly them.
    """
    if not (contour.layer.visible and contour.visual.mesh.visible):
        return []
    names = contour.meshset.names
    return [(names.index(contour.name_at_shape(i)), np.asarray(loop, float))
            for i, loop in enumerate(contour.paths)]


def rendered_mesh(contour) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Vertices (vispy x, y), faces and vertex RGBA the contour's mesh visual holds."""
    mesh = contour.visual.mesh
    if not (contour.layer.visible and mesh.visible):
        return np.empty((0, 2)), np.empty((0, 3), int), np.empty((0, 4))
    data = mesh.mesh_data
    return (np.asarray(data.get_vertices(), float)[:, :2],
            np.asarray(data.get_faces(), int),
            np.asarray(data.get_vertex_colors(), float))


def rendered_labels(contour) -> list[tuple[str, np.ndarray, np.ndarray]]:
    """(text, vispy x-y position, RGBA) for every label the text visual draws."""
    text = contour.visual.text
    if not (contour.layer.visible and text.visible):
        return []
    strings = [text.text] if isinstance(text.text, str) else list(text.text)
    pos = np.asarray(text.pos, float)[:, :2]
    rgba = np.atleast_2d(np.asarray(text.color.rgba, float))
    rgba = np.broadcast_to(rgba, (len(strings), 4)) if len(rgba) == 1 else rgba
    return [(s, pos[i], rgba[i]) for i, s in enumerate(strings) if s]


def _edge_rgba(contour, owner: int) -> np.ndarray:
    from napari.utils.colormaps.standardize_color import transform_color

    spec = contour.colors[owner] if contour.colors is not None else contour.color
    return np.asarray(transform_color(spec), float)[0]


def _areas(points: np.ndarray, faces: np.ndarray) -> np.ndarray:
    a, b, c = (points[faces[:, i]] for i in range(3))
    return np.abs((b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1])
                  - (b[:, 1] - a[:, 1]) * (c[:, 0] - a[:, 0])) / 2.0


def ring_area(ring: np.ndarray) -> float:
    """The exact area inside a simple closed ring of float32 points, as drawn.

    The shoelace formula, about the ring's first point, so coordinates far
    from the origin cancel nothing away. A fill that covers the ring and no
    more has exactly this area, however it is triangulated.
    """
    r = np.asarray(ring, np.float32).astype(float)
    r = r - r[0]
    x, y = r[:, 0], r[:, 1]
    return abs(float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))) / 2.0


def assert_renders_loops(contour, tol: float = 1e-3) -> None:
    """The contour's vispy visuals draw exactly its loops, and nothing else.

    - Outlines: the rendered outline triangles are, vertex for vertex and
      triangle for triangle, the stroke napari's Shapes gives a closed path
      `contour.width` wide (bermuda's `triangulate_path_edge`, the call
      napari makes), in each loop's compartment color.
    - Fills: each filled compartment's fill triangles, drawn before every
      outline, cover exactly the area inside its loops, in the order napari
      displays them -- no less, and no more, as overlapping triangles would
      -- in its color at `FILL_ALPHA`; nothing else is filled.
    - Labels: each labeled compartment's name, once, at the mean of its
      longest loop's points, in its color.
    - Placement: vispy maps the rendered points to where the layer's
      data-to-world transform puts them, so the mirror moves them too.
    """
    import bermuda
    from scipy.spatial import cKDTree

    loops = contour_loops(contour)
    vertices, faces, colors = rendered_mesh(contour)
    xy = list(contour.viewer.dims.displayed)[::-1]
    alpha = colors[faces[:, 0], 3] if len(faces) else np.empty(0)
    is_fill = np.isclose(alpha, contour.FILL_ALPHA, atol=1e-6)
    if is_fill.any():
        assert is_fill[: is_fill.sum()].all(), "an outline drawn under a fill"
    stroke_faces, fill_faces = faces[~is_fill], faces[is_fill]

    want_v, want_c, want_tri = [], [], 0
    for owner, loop in loops:
        ring = np.ascontiguousarray(loop[:-1][:, xy], np.float32)
        centers, offsets, tris = bermuda.triangulate_path_edge(ring, closed=True)
        want_v.append(centers + contour.width * offsets)
        want_c.append(np.broadcast_to(_edge_rgba(contour, owner), (len(centers), 4)))
        want_tri += len(tris)
    assert len(stroke_faces) == want_tri, (len(stroke_faces), want_tri)
    if loops:
        # Matched on position and color together: the outlines of two
        # touching compartments can share a point.
        used = np.unique(stroke_faces)
        got = np.hstack((vertices[used], 1e3 * colors[used]))
        want = np.hstack((np.vstack(want_v), 1e3 * np.vstack(want_c)))
        distance, _ = cKDTree(got).query(want)
        assert distance.max() <= tol, f"an outline vertex {distance.max():.2e} off"
        back, _ = cKDTree(want).query(got)
        assert back.max() <= tol, f"a stray outline vertex {back.max():.2e} off"

    fill_area: dict[tuple, float] = {}
    for tri, area in zip(fill_faces, _areas(vertices, fill_faces)):
        key = tuple(np.round(colors[tri[0]], 4))
        fill_area[key] = fill_area.get(key, 0.0) + float(area)
    want_area: dict[tuple, float] = {}
    displayed = list(contour.viewer.dims.displayed)
    for owner, loop in loops:
        if owner in contour.filled:
            rgba = _edge_rgba(contour, owner).copy()
            rgba[3] = contour.FILL_ALPHA
            key = tuple(np.round(rgba, 4))
            want_area[key] = want_area.get(key, 0.0) + ring_area(loop[:-1][:, displayed])
    assert set(fill_area) == set(want_area), "filled colors differ"
    for key, area in want_area.items():
        # float64 arithmetic on float32 points: far below any visible change.
        assert abs(fill_area[key] - area) <= 1e-6 * area + 1e-9, (key, fill_area[key], area)

    # Where vispy puts the rendered points is where napari's own transform
    # puts those points of the plane: the layer's, the mirror included.
    if len(vertices):
        to_scene = contour.visual.mesh.get_transform("visual", "scene")
        for v in vertices[np.linspace(0, len(vertices) - 1, 8).astype(int)]:
            data = np.zeros(3)
            data[xy] = v
            data[contour.axis] = contour.slice_position()
            want = np.asarray(contour.layer.data_to_world(data))[displayed][::-1]
            got = np.asarray(to_scene.map(np.r_[v, 0.0, 1.0]), float)
            np.testing.assert_allclose(got[:2] / got[3], want, atol=tol)

    longest: dict[int, np.ndarray] = {}
    for owner, loop in loops:
        if owner in contour.labels and (owner not in longest
                                        or len(loop) > len(longest[owner])):
            longest[owner] = loop
    got = sorted(rendered_labels(contour), key=lambda t: t[0])
    want = sorted(((contour.display_names[o], loop[:, xy].mean(axis=0),
                    _edge_rgba(contour, o)) for o, loop in longest.items()),
                  key=lambda t: t[0])
    assert [g[0] for g in got] == [w[0] for w in want], "labels differ"
    for (_s, pos, rgba), (_t, wpos, wrgba) in zip(got, want):
        np.testing.assert_allclose(pos, wpos, atol=tol)
        np.testing.assert_allclose(rgba, wrgba, atol=1e-6)


def signed_volume(vertices, faces) -> float:
    """Positive when the winding puts the normals outward.

    Summed about the mesh's own mean vertex, not the world origin: a
    closed mesh gives the same volume about any point, and a small one far
    from the origin otherwise loses it to cancellation, a percent for a
    32 um3 neuropil set some hundred um out.
    """
    vertices = np.asarray(vertices, float)
    vertices = vertices - vertices.mean(axis=0)
    a, b, c = (vertices[faces[:, k]] for k in range(3))
    return float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6.0)


def shaded_normals(viewer, surface) -> tuple[float, float]:
    """(signed volume, share of outward normals) of a surface as vispy
    shades it, read in 3D off its vispy node.

    Not off the napari layer: napari reverses the winding on upload, so the
    faces a layer holds are not the faces shaded, and in 2D the node holds a
    flat slice whose volume is zero. The share is of the first compartment's
    vertex normals pointing away from its centroid; glomeruli are not
    convex, so about 77% is what outward looks like.
    """
    from lobemap.viewer.napari_private import layer_visual

    mesh = layer_visual(viewer, surface.layer).node.mesh_data
    v = np.asarray(mesh.get_vertices(), float)
    f = np.asarray(mesh.get_faces())
    n = np.asarray(mesh.get_vertex_normals(), float)
    values = np.asarray(surface.layer.data[2])
    assert len(values) == len(v), "the node is not in step with the layer"
    first = (values == values[0]) & (np.linalg.norm(n, axis=1) > 1e-12)
    center = v[first].mean(axis=0)
    outward = float(np.mean(np.einsum("ij,ij->i", n[first], v[first] - center) > 0))
    return signed_volume(v, f), outward


def node_determinant(viewer, surface) -> float:
    """Determinant of a surface node's visual-to-scene transform: negative
    when napari reflects it, which flips `gl_FrontFacing` and so inverts
    vispy's smooth shading (`AtlasSurface._present`)."""
    from lobemap.viewer.napari_private import layer_visual

    node = layer_visual(viewer, surface.layer).node
    transform = node.transforms.get_transform("visual", "scene")
    origin = np.asarray(transform.map(np.zeros((3, 3))))[:, :3]
    return float(np.linalg.det(np.asarray(transform.map(np.eye(3)))[:, :3] - origin))


def mode_layer(surface, contour=None):
    """The layer that draws this atlas in the current mode."""
    if contour is not None and surface.viewer.dims.ndisplay == 2:
        return contour.layer
    return surface.layer


def drawn(surface, contour=None) -> set[int]:
    """Compartment indices this atlas puts on screen right now.

    3D: the mesh layer is visible, the compartment's geometry is resident,
    and its color is opaque. 2D, with a contour overlay: the contour layer
    is visible and draws a loop of that compartment -- and the mesh, if it
    is on as well, draws everything it holds.
    """
    out: set[int] = set()
    if contour is not None and surface.viewer.dims.ndisplay == 2:
        out = {owner for owner, _loop in contour_loops(contour)}
        if not surface.layer.visible:
            return out
    if not surface.layer.visible:
        return set()
    resident = {round(float(v)) for v in np.unique(surface.layer.data[2])}
    alpha = np.asarray(surface.layer.colormap.colors)[:, 3]
    n = surface.meshset.n_compartments
    opaque = {i for i in range(n) if alpha[min(i, len(alpha) - 1)] > 0}
    return out | (resident & opaque)


def checked(tab) -> set[int]:
    from qtpy.QtCore import Qt

    from lobemap.viewer.panel import VISIBLE_COL

    return {tab._index_of(r) for r in range(tab.table.rowCount())
            if tab.table.item(r, VISIBLE_COL).checkState() == Qt.Checked}


def planes_cut(surface) -> set[int]:
    """Checked compartments the current 2D plane actually cuts.

    A fresh section of the atlas, sharing no cache with the viewer, at the
    plane on screen: the slider's world point taken into the MeshSet's frame
    through the contour layer's transform, which carries the mirror -- the
    surface reflects its own vertices instead (`AtlasSurface._present`). A
    compartment whose bounds hold the plane but whose surface does not reach
    it -- a tangent plane, a concave side -- is not cut.
    """
    from lobemap.viewer.sections import MeshSections

    viewer = surface.viewer
    axis = int(viewer.dims.order[0])
    frame = surface.twin.layer if surface.twin is not None else surface.layer
    position = float(frame.world_to_data(list(viewer.dims.point))[axis])
    cut = MeshSections(surface.meshset).at(axis, position)
    return {i for i in surface.selection if cut.get(i)}


def assert_rows_match_drawing(sess) -> None:
    """Every tab: checked rows, count text and rendered geometry agree.

    Call it once the scene has settled (`pump(300)`): a compartment checked
    after compaction reaches the mesh with the next compaction. In 2D only
    the checked compartments this plane crosses can have a contour, so
    those are what must be drawn.
    """
    two_d = sess.viewer.dims.ndisplay == 2
    for name, tab in sess.panel.tabs.items():
        contour = sess.contours.get(name)
        rows = checked(tab)
        got = drawn(tab.surface, contour)
        want = planes_cut(tab.surface) if two_d else rows
        n = tab.table.rowCount()
        assert rows == tab.surface.selection, (name, "rows != selection")
        assert got == want, (name, sorted(got ^ want)[:8])
        assert tab.count.text() == f"{len(rows)} of {n} shown", (name, tab.count.text())
        if not rows:
            assert not tab.surface.layer.visible, name
            if contour is not None:
                assert not contour.layer.visible, name
        elif two_d and contour is not None:
            assert not tab.surface.layer.visible, (name, "mesh drawn in 2D")


# -- the cursor -----------------------------------------------------------


def canvas_position(viewer, world) -> tuple[float, float]:
    """Canvas pixel at which `world` is drawn: `_map_canvas2world` inverted."""
    canvas = viewer.window._qt_viewer.canvas
    transform = canvas.view.transform * canvas.view.scene.transform
    point = np.asarray(world, float)[list(viewer.dims.displayed)][::-1]
    mapped = np.asarray(transform.map(np.r_[point, 0.0][:3] if len(point) == 2
                                      else point), float)
    return float(mapped[0] / mapped[3]), float(mapped[1] / mapped[3])


def hover(viewer, world) -> str:
    """Move the mouse over `world` through napari's own event path."""
    from vispy.app.canvas import MouseEvent

    canvas = viewer.window._qt_viewer.canvas
    viewer.status = ""
    event = MouseEvent(type="mouse_move", pos=canvas_position(viewer, world),
                       modifiers=(), buttons=[])
    canvas._on_mouse_move(event)
    pump()
    status = viewer.status
    return status if isinstance(status, str) else str(status)


def click(viewer, world, drag: float = 0.0) -> str:
    """Press and release the left button over `world`, through napari's own
    mouse path; `drag` moves the cursor that many pixels in between. What
    the status bar says after."""
    from vispy.app.canvas import MouseEvent

    canvas = viewer.window._qt_viewer.canvas
    x, y = canvas_position(viewer, world)
    viewer.status = ""
    press = MouseEvent(type="mouse_press", pos=(x, y), modifiers=(), button=1,
                       buttons=[1])
    canvas._on_mouse_press(press)
    if drag:
        for k in range(1, 4):
            move = MouseEvent(type="mouse_move", pos=(x + drag * k / 3, y),
                              modifiers=(), button=1, buttons=[1], press_event=press)
            canvas._on_mouse_move(move)
    end = (x + drag, y)
    release = MouseEvent(type="mouse_release", pos=end, modifiers=(), button=1,
                         buttons=[], press_event=press)
    canvas._on_mouse_release(release)
    pump()
    status = viewer.status
    return status if isinstance(status, str) else str(status)
