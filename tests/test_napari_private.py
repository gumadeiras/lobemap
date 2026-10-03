"""Every private internal of another package that lobemap reaches, by name and shape.

napari has no public way to draw a visual under a layer, to keep a slice
step from recomputing every layer's extent, to recolor its axis indicator
or add a second one, to reach its Qt window, or to arrange its own buttons
and docks; bermuda, vispy, zarr and
navis are reached below their documented surface in places too. Most of
these are reached through `getattr` defaults or `contextlib.suppress`, so
when one moves the viewer misdraws, slows down or drops a control without
a word. pyproject pins napari to the minor version its internals were
written against; the others are not pinned.

After any upgrade, a failure here names what moved and which module uses
it. `need` writes that message, and `reaching` routes a missing import or
attribute through it too, rather than letting it fail as a bare
ImportError or AttributeError. What a scene reaches is checked on the
objects `viewer.app.load_space` builds, and again on a bare viewer set up
by the same calls, so a checkout without data still checks it.

`CHECKED` names the test that checks each private name, and
`test_every_private_name_src_reaches_is_checked` scans `src/` so that a new
one cannot go unchecked. Any string in `src/` that reads as a private name
or a private module path counts as reaching it, however it is used:
`operator.attrgetter`, `vars()`, `__dict__`, `importlib`, `sys.modules`. An
attribute name the scan cannot read from the source must be listed in
`DYNAMIC`, so it cannot hide one either.
"""

from __future__ import annotations

import ast
import contextlib
import inspect
import re
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

napari = pytest.importorskip("napari")

SRC = Path(__file__).resolve().parents[1] / "src" / "lobemap"

#: Every private name or private module `src/` reaches in another package,
#: and the test below that checks it.
CHECKED = {
    "_qt_viewer": "test_a_layer_has_a_vispy_node_to_draw_under",
    "_qt_window": "test_the_window_and_canvas_lobemap_reaches",
    "_viewer_overlay_to_visual": "test_the_axis_indicator_is_recolored_and_gets_a_second_triad",
    "_font_info": "test_the_axis_indicator_is_recolored_and_gets_a_second_triad",
    "_default_color": "test_the_axis_indicator_is_recolored_and_gets_a_second_triad",
    "_on_data_change": "test_the_axis_indicator_is_recolored_and_gets_a_second_triad",
    "napari._vispy.visuals.axes": "test_the_axis_indicator_is_recolored_and_gets_a_second_triad",
    "napari._vispy.visuals.text": "test_napari_text_visual_takes_labels",
    "napari._vispy.utils.gl": "test_every_blending_has_a_gl_state",
    "napari.layers.shapes._shapes_utils": "test_napari_triangulation_without_bermuda",
    "napari.layers.shapes._accelerated_triangulate_dispatch":
        "test_napari_triangulation_without_bermuda",
    "_slice_dims": "test_a_slice_step_goes_through_slice_dims_and_clears_the_extent",
    "_clear_extent": "test_a_slice_step_goes_through_slice_dims_and_clears_the_extent",
    "_layer_slicer": "test_a_step_can_be_seen_before_any_layer_is_sliced",
    "_transforms": "test_the_prefetch_finds_the_planes_a_step_lands_on",
    "_cmtkbin": "test_navis_says_whether_cmtk_is_installed",
    "_update_scenegraph": "test_a_mesh_is_hidden_and_shown_without_napari_redoing_it",
    "_block_refresh": "test_a_mesh_is_hidden_and_shown_without_napari_redoing_it",
    "_layer_node": "test_a_volume_takes_its_voxels_at_its_next_draw",
    "_volume_node": "test_a_volume_takes_its_voxels_at_its_next_draw",
    "_prepare_draw": "test_a_volume_takes_its_voxels_at_its_next_draw",
    "napari._qt.widgets.qt_viewer_dock_widget": "test_the_napari_chrome_lobemap_tidies",
    "_extent_world_augmented": "test_a_turned_view_rewrites_the_extent_napari_reads",
    "_clean_cache": "test_a_turned_view_rewrites_the_extent_napari_reads",
    "_on_layers_change": "test_a_turned_view_rewrites_the_extent_napari_reads",
    "_extent_augmented": "test_a_turned_view_rewrites_the_extent_napari_reads",
    "_update_draw": "test_a_turned_image_picks_its_level_as_napari_draws",
    "_viewbox_corners_in_world": "test_a_turned_image_picks_its_level_as_napari_draws",
    "_current_viewbox_size": "test_a_turned_image_picks_its_level_as_napari_draws",
    "_data_level": "test_a_turned_image_picks_its_level_as_napari_draws",
    "_slicing_state": "test_a_turned_image_picks_its_level_as_napari_draws",
}

#: lobemap's own private names, reached from another of its modules.
OWN = {"_load_spaces", "_load_assets", "_load_atlases", "_read", "_box", "_obj"}

#: Attribute names `src/` computes at run time, by module and expression.
#: Each names data -- a flybrains template, a bermuda function, a layer
#: setting -- and never a private internal. A new one fails the scan until
#: it is read and listed here.
DYNAMIC = {
    ("cli.py", "reg.spaces[args.space].flybrains_template"),
    ("core/resolve.py", "template"),
    ("core/spaces.py", "name"),
    ("ingest/synapse_buckets.py", "template_name"),
    ("viewer/triangulate.py", "name"),
    ("viewer/layers.py", "key"),
}

_ATTR_CALLS = ("getattr", "hasattr", "setattr", "delattr")

#: A string that reads as a name or a dotted module path.
_NAMEISH = re.compile(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*")


def need(ok, what: str, used_by: str) -> None:
    assert ok, f"{what} is missing or has changed shape; {used_by} relies on it"


@contextlib.contextmanager
def reaching(what: str, used_by: str):
    """Fail through `need` when reaching `what` raises: an import, an attribute."""
    try:
        yield
    except AssertionError:
        raise
    except Exception as exc:                # whatever moved, name it
        need(False, f"{what} ({type(exc).__name__}: {exc})", used_by)


def _private(name: str) -> bool:
    return name.startswith("_") and not name.startswith(("__", "_lobemap"))


def _strings(node) -> list[str] | None:
    """The strings a literal str constant, tuple or list holds, else None."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, (ast.Tuple, ast.List)) and all(
            isinstance(e, ast.Constant) and isinstance(e.value, str) for e in node.elts):
        return [e.value for e in node.elts]
    return None


def _scan(source: str) -> tuple[list[tuple[str, int]], list[str]]:
    """The private names one module reaches outside `self`, with their lines,
    and the attribute names it computes at run time.

    A name given to `getattr` and the like is read from a literal, from a
    module-level string constant, or from the target of a loop over literal
    strings; any other is returned as computed. Any string that reads as a
    private name, or as a module path with a private part, counts wherever
    it is.
    """
    tree = ast.parse(source)
    known = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and _strings(node.value) is not None:
            for target in node.targets:
                if isinstance(target, ast.Name):
                    known[target.id] = _strings(node.value)
    looped = {}
    for node in ast.walk(tree):
        if (isinstance(node, ast.For) and isinstance(node.target, ast.Name)
                and _strings(node.iter) is not None):
            for inner in ast.walk(node):
                if isinstance(inner, ast.Name) and inner.id == node.target.id:
                    looped[id(inner)] = _strings(node.iter)

    def own(value) -> bool:
        return isinstance(value, ast.Name) and value.id in ("self", "cls")

    # A name `getattr` and the like look up on `self` is lobemap's own.
    owned = {id(node.args[1]) for node in ast.walk(tree)
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
             and node.func.id in _ATTR_CALLS and len(node.args) >= 2
             and own(node.args[0])}

    found, computed = set(), []
    for node in ast.walk(tree):
        names = []
        if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and id(node) not in owned and _NAMEISH.fullmatch(node.value)
                and any(_private(part) and part != "_"
                        for part in node.value.split("."))):
            names.append(node.value)
        elif isinstance(node, ast.Attribute) and _private(node.attr):
            if not own(node.value):
                names.append(node.attr)
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
              and node.func.id in _ATTR_CALLS and len(node.args) >= 2
              and not own(node.args[0])):
            arg = node.args[1]
            values = (_strings(arg) if not isinstance(arg, ast.Name)
                      else looped.get(id(arg), known.get(arg.id)))
            if values is None:
                computed.append(ast.unparse(arg))
            else:
                names += [value for value in values if _private(value)]
        elif isinstance(node, ast.Import):
            names += [alias.name for alias in node.names
                      if any(part.startswith("_") for part in alias.name.split("."))]
        elif (isinstance(node, ast.ImportFrom) and node.module
              and node.module != "__future__"):
            if any(part.startswith("_") for part in node.module.split(".")):
                names.append(node.module)
            names += [alias.name for alias in node.names if _private(alias.name)]
        found |= {(name, node.lineno) for name in names}
    return sorted(found), computed


def _private_names() -> tuple[dict[str, list[str]], set[tuple[str, str]]]:
    """Every private name `src/` reaches outside `self`, and where; and every
    attribute name it computes, by module."""
    found: dict[str, list[str]] = {}
    computed: set[tuple[str, str]] = set()
    for path in sorted(SRC.rglob("*.py")):
        names, dynamic = _scan(path.read_text())
        for name, line in names:
            found.setdefault(name, []).append(f"{path.relative_to(SRC.parent)}:{line}")
        computed |= {(path.relative_to(SRC).as_posix(), expr) for expr in dynamic}
    return found, computed


def test_the_scan_sees_every_way_of_reaching_a_name():
    source = """
import napari._vispy.visuals
import numpy, napari._qt.qt_main_window as w
from napari._vispy import utils
from napari.layers import _shapes_utils
ATTR = "_from_a_constant"
other._attribute
getattr(other, "_got")
hasattr(other, "_has")
setattr(other, "_set", 1)
delattr(other, "_deleted")
getattr(other, ATTR)
for name in ("_looped", "public"):
    getattr(other, name)
getattr(other, computed_at_run_time)
operator.attrgetter("_attrgot")(other)
vars(other)["_in_vars"]
other.__dict__["_in_dict"]
importlib.import_module("napari._imported")
__import__("napari._dunder_imported")
sys.modules["napari._in_sys_modules"]
self._own
getattr(self, "_own_too")
"_ a sentence, not a name"
"__main__"
"a_b".split("_")
"""
    found, computed = _scan(source)
    assert sorted({name for name, _ in found}) == sorted([
        "napari._vispy.visuals", "napari._qt.qt_main_window", "napari._vispy",
        "_shapes_utils", "_attribute", "_got", "_has", "_set", "_deleted",
        "_from_a_constant", "_looped", "_attrgot", "_in_vars", "_in_dict",
        "napari._imported", "napari._dunder_imported", "napari._in_sys_modules"])
    assert computed == ["computed_at_run_time"]


def test_every_private_name_src_reaches_is_checked():
    found, computed = _private_names()
    unread = sorted(computed - DYNAMIC)
    assert not unread, f"attribute names src/ computes, not read here: {unread}"
    gone = sorted(DYNAMIC - computed)
    assert not gone, f"DYNAMIC lists names src/ no longer computes: {gone}"
    unchecked = {name: where for name, where in found.items()
                 if name not in CHECKED and name not in OWN}
    assert not unchecked, f"private names no test here checks: {unchecked}"
    stale = sorted(set(CHECKED) - set(found))
    assert not stale, f"CHECKED lists names src/ no longer reaches: {stale}"
    missing = sorted({test for test in CHECKED.values() if test not in globals()})
    assert not missing, f"CHECKED names tests that do not exist: {missing}"


@pytest.fixture
def viewer():
    v = napari.Viewer(show=False, ndisplay=2)
    yield v
    v.close()


@pytest.fixture(params=["bare viewer", "loaded scene"])
def opened(request, registry):
    """A 2D viewer as lobemap leaves it: a GRABE scene, or a bare one set up alike.

    The bare one has an image and an empty Shapes layer, as a scene's image
    and contour layers are, and the axis indicator set up by the call a
    scene makes, `viewer.axes.apply_axis_mode`.
    """
    from qtpy.QtWidgets import QApplication

    from lobemap.viewer.axes import apply_axis_mode

    scene = request.param == "loaded scene"
    if scene:
        request.getfixturevalue("core_data")
    space = registry.spaces["GRABE"]
    v = napari.Viewer(show=False, ndisplay=2)
    try:
        if scene:
            from lobemap.viewer.app import load_space

            with reaching("a GRABE scene opened by load_space", "the viewer"):
                session = load_space(v, registry, "GRABE", fit=False)
            contour = session.contours[registry.primary_atlas("GRABE").id].layer
            image = next(layer for layer in v.layers
                         if layer.metadata.get("lobemap", {}).get("kind") == "image")
        else:
            image = v.add_image(np.zeros((8, 8, 8), np.uint8))
            contour = v.add_shapes(data=[], ndim=3)
            apply_axis_mode(v, space)
        QApplication.processEvents()
        yield SimpleNamespace(viewer=v, space=space, image=image, contour=contour)
    finally:
        v.close()


def test_napari_is_the_pinned_minor_version():
    major, minor = (int(p) for p in napari.__version__.split(".")[:2])
    need((major, minor) == (0, 9), f"napari {napari.__version__} (0.9 is pinned)",
         "every check below")


def test_a_layer_has_a_vispy_node_to_draw_under(opened):
    from vispy.scene.node import Node

    from lobemap.viewer.napari_private import layer_visual

    where = "viewer.window._qt_viewer.canvas.layer_to_visual[layer]"
    used = "viewer.contours.SliceVisual"
    with reaching(where, used):
        visual = layer_visual(opened.viewer, opened.contour)
        node, font = visual.node, visual.font_info
    need(isinstance(node, Node), f"{where}.node", used)
    need(hasattr(font, "font_manager") and hasattr(font, "face"), f"{where}.font_info",
         f"{used} labels")


def test_napari_text_visual_takes_labels(opened):
    from lobemap.viewer.napari_private import layer_visual, text_visual

    used = "viewer.contours.SliceVisual labels"
    with reaching("napari._vispy.visuals.text.Text(parent=, font_info=)", used):
        visual = layer_visual(opened.viewer, opened.contour)
        text = text_visual(visual.node, visual.font_info)
    with reaching("Text.font_size, .anchors, .text, .pos and .color", used):
        text.font_size = 10.5
        text.anchors = ("center", "center")
        text.text = ["DA1", "DM1"]
        text.pos = np.zeros((2, 2), np.float32)
        text.color = np.ones((2, 4), np.float32)
        shape = text.color.rgba.shape
    need(text.parent is visual.node, "Text(parent=, font_info=)", used)
    need(list(text.text) == ["DA1", "DM1"] and shape == (2, 4),
         "Text.text / Text.color per label", used)


def test_every_blending_has_a_gl_state():
    """A key vispy's `set_gl_state` takes: a GL flag, or a `set_<key>` setter."""
    from lobemap.viewer.napari_private import gl_state

    used = "viewer.contours.SliceVisual blending"
    with reaching("napari.layers.base._base_constants.Blending and vispy's "
                  "BaseGlooFunctions", used):
        from napari.layers.base._base_constants import Blending
        from vispy.gloo.wrappers import BaseGlooFunctions

        blendings = [str(blending) for blending in Blending]
    for blending in blendings:
        with reaching(f"napari._vispy.utils.gl.BLENDING_MODES[{blending}]", used):
            state = gl_state(blending)
        need(state and all(isinstance(value, bool) or hasattr(BaseGlooFunctions, f"set_{key}")
                           for key, value in state.items()),
             f"napari._vispy.utils.gl.BLENDING_MODES[{blending}]", used)


def test_a_slice_step_goes_through_slice_dims_and_clears_the_extent(viewer):
    """What `keep_extent_while_slicing` wraps, and what it relies on napari doing."""
    layer = viewer.add_image(np.zeros((6, 4, 4), np.uint8))
    used = "viewer.napari_private.keep_extent_while_slicing"
    need(callable(getattr(layer, "_slice_dims", None)), "Layer._slice_dims", used)
    need(callable(getattr(layer, "_clear_extent", None)), "Layer._clear_extent", used)
    need("extent" in inspect.signature(layer.refresh).parameters,
         "Layer.refresh(extent=)", used)
    calls = []
    slice_dims, clear = layer._slice_dims, layer._clear_extent
    layer._slice_dims = lambda *a, **k: (calls.append("slice"), slice_dims(*a, **k))[1]
    layer._clear_extent = lambda: (calls.append("clear"), clear())[1]
    before = viewer.layers.extent
    viewer.dims.set_current_step(0, 3)
    need(calls[:1] == ["slice"] and "clear" in calls,
         "the layer slicer calling layer._slice_dims, which calls _clear_extent", used)
    need(viewer.layers.extent is not before,
         "viewer.layers recomputing its extent when a layer clears one", used)


def test_a_mesh_is_hidden_and_shown_without_napari_redoing_it(viewer):
    """What `no_scene_update` and `shown_unsliced` reach, and what they rely on napari doing."""
    from lobemap.viewer.napari_private import layer_visual, no_scene_update, shown_unsliced

    used = "viewer.layers.AtlasSurface, which keeps its 3D build through 2D"
    viewer.dims.ndisplay = 3
    vertices = np.array([[0, 0, 0], [0, 1, 0], [1, 0, 0], [0, 0, 1]], float)
    layer = viewer.add_surface((vertices, np.array([[0, 1, 2], [0, 1, 3]])))
    canvas = viewer.window._qt_viewer.canvas
    need(callable(getattr(canvas, "_update_scenegraph", None)),
         "VispyCanvas._update_scenegraph", used)
    need(callable(getattr(layer, "_block_refresh", None)), "Layer._block_refresh", used)
    node = layer_visual(viewer, layer).node
    built, drawn = [], []
    layer.events.set_data.connect(lambda: built.append(1))
    on_draw = canvas.on_draw
    canvas.on_draw = lambda *a, **k: (drawn.append(1), on_draw(*a, **k))[1]
    with (reaching("layer.events.visible.blocker(canvas._update_scenegraph)", used),
          no_scene_update(viewer, layer)):
        layer.visible = False
    need(not drawn and not node.visible,
         "a visibility change reaching the vispy node but not the scene graph", used)
    layer.visible = True
    need(drawn and built, "a layer shown updating the scene graph and rebuilding its visual",
         used)
    layer.visible = False
    del built[:]
    with reaching("Layer._block_refresh()", used), shown_unsliced(layer):
        layer.visible = True
    need(not built and node.visible, "a layer shown under _block_refresh keeping its visual",
         used)


def test_a_volume_takes_its_voxels_at_its_next_draw(viewer, monkeypatch):
    """What `keep_volume_texture` reaches, and what it relies on napari and vispy doing."""
    from vispy.visuals.volume import VolumeVisual

    from lobemap.viewer.napari_private import keep_volume_texture, layer_visual

    used = "viewer.images, which uploads a 3D level only when it changes"
    uploads = []
    upload = VolumeVisual.set_data

    def counted(self, vol, *args, **kwargs):
        uploads.append(vol.shape)
        return upload(self, vol, *args, **kwargs)

    monkeypatch.setattr(VolumeVisual, "set_data", counted)
    layer = viewer.add_image(np.arange(6 * 5 * 4, dtype=np.uint8).reshape(6, 5, 4))
    with reaching("layer_visual(...)._layer_node._volume_node", used):
        node = layer_visual(viewer, layer)._layer_node._volume_node
    need(isinstance(node, VolumeVisual) and callable(getattr(node, "_prepare_draw", None)),
         "ImageLayerNode._volume_node, a vispy Volume with _prepare_draw", used)
    with reaching("keep_volume_texture", used):
        keep_volume_texture(viewer, layer)
    render = viewer.window._qt_viewer.canvas._scene_canvas.render
    del uploads[:]
    viewer.dims.ndisplay = 3
    need(uploads == [(6, 5, 4)],
         "napari handing the volume node its voxels through set_data, the first at once", used)
    for ndisplay in (2, 3):
        viewer.dims.ndisplay = ndisplay
        render()
    need(uploads == [(6, 5, 4)], "napari slicing the same buffer on the way back into 3D", used)
    layer.data = np.zeros((3, 5, 4), np.uint8)
    need(uploads == [(6, 5, 4)], "napari handing new voxels of the same dtype to set_data", used)
    render()
    need(uploads[-1] == (3, 5, 4), "vispy calling Volume._prepare_draw as it draws", used)


def test_napari_triangulation_without_bermuda():
    from lobemap.viewer.napari_private import triangulate_edge, triangulate_face

    square = np.array([[0, 0], [0, 1], [1, 1], [1, 0]], np.float32)
    used = "viewer.triangulate without bermuda"
    where = "napari.layers.shapes._shapes_utils.triangulate_edge"
    with reaching(where, used):
        centers, offsets, triangles = triangulate_edge(square)
    need(centers.shape == offsets.shape and centers.shape[1] == 2 and triangles.shape[1] == 3,
         where, used)
    where = ("napari.layers.shapes._accelerated_triangulate_dispatch."
             "normalize_vertices_and_edges + _shapes_utils.triangulate_face_vispy")
    with reaching(where, used):
        points, faces = triangulate_face(square)
    need(np.asarray(points).shape[1] == 2 and np.asarray(faces).shape[1] == 3, where, used)


def test_bermuda_strokes_and_fills():
    bermuda = pytest.importorskip("bermuda")
    ring = np.array([[0, 0], [0, 2], [1, 3], [2, 2], [2, 0]], np.float32)
    used = "viewer.triangulate outlines and fills"
    where = "bermuda.triangulate_path_edge(ring, closed=, limit=)"
    with reaching(where, used):
        centers, offsets, triangles = bermuda.triangulate_path_edge(ring, closed=True,
                                                                    limit=3.0)
    need(centers.shape == offsets.shape and triangles.shape[1] == 3, where, used)
    where = "bermuda.triangulate_polygons_face -> (triangles, points)"
    with reaching(where, used):
        triangles, points = bermuda.triangulate_polygons_face([ring])
    need(triangles.shape[1] == 3 and points.shape[1] == 2, where, used)


def test_vispy_mesh_takes_and_gives_back_its_buffers(viewer):
    from vispy.scene.visuals import Mesh

    used = "viewer.contours.SliceVisual and the tests' rendered-buffer readers"
    vertices = np.array([[0, 0], [1, 0], [0, 1]], np.float32)
    with reaching("vispy MeshVisual.set_data / mesh_data", used):
        mesh = Mesh()
        mesh.set_data(vertices=vertices, faces=np.array([[0, 1, 2]], np.uint32),
                      vertex_colors=np.ones((3, 4), np.float32))
        got = np.asarray(mesh.mesh_data.get_vertices())[:, :2]
        colors = np.asarray(mesh.mesh_data.get_vertex_colors())
    need(np.array_equal(got, vertices) and colors.shape == (3, 4),
         "vispy MeshVisual.set_data / mesh_data", used)
    need(callable(getattr(mesh, "get_transform", None)), "vispy Node.get_transform", used)


def test_zarr_v2_metadata_the_chunk_reader_reads(tmp_path):
    used = "viewer.chunkcache._ChunkFiles"
    with reaching("zarr.create_array / open_array (format 2) and zarr.storage.LocalStore",
                  used):
        import zarr
        from numcodecs import Zstd
        from zarr.storage import LocalStore

        zarr.create_array(store=str(tmp_path / "a.zarr"), shape=(4, 4), chunks=(2, 2),
                          dtype="u1", zarr_format=2, compressors=Zstd())
        arr = zarr.open_array(str(tmp_path / "a.zarr"), mode="r")
        meta = arr.metadata
    for name in ("zarr_format", "filters", "order", "compressor", "fill_value",
                 "encode_chunk_key"):
        need(hasattr(meta, name), f"zarr ArrayV2Metadata.{name}", used)
    need(isinstance(arr.store, LocalStore) and hasattr(arr.store, "root")
         and arr.path == "", "zarr LocalStore.root and Array.path", used)
    with reaching("ArrayV2Metadata.encode_chunk_key", used):
        key = meta.encode_chunk_key((1, 0))
    need(key == "1.0", "ArrayV2Metadata.encode_chunk_key", used)


def test_what_the_slice_benchmark_reaches_into(viewer):
    used = "benchmarks/slice_step.py"
    with reaching("napari._qt.qt_viewer.QtViewer._on_slice_ready", used):
        from napari._qt.qt_viewer import QtViewer

        ready = QtViewer._on_slice_ready
    need(callable(getattr(ready, "__wrapped__", None)),
         "QtViewer._on_slice_ready.__wrapped__", used)
    with reaching("viewer._layer_slicer", used):
        slicer = viewer._layer_slicer
    need(hasattr(slicer, "_force_sync"), "viewer._layer_slicer._force_sync", used)
    with reaching("viewer.window._qt_viewer.canvas", used):
        canvas = viewer.window._qt_viewer.canvas
    need(callable(getattr(canvas, "on_draw", None)), "QtViewer.canvas.on_draw", used)
    layer = viewer.add_image([np.zeros((8, 8, 8)), np.zeros((4, 4, 4))], multiscale=True)
    need(hasattr(layer, "_data_level") and np.asarray(layer.corner_pixels).shape == (2, 3),
         "Image._data_level and Image.corner_pixels", used)


def test_the_axis_indicator_is_recolored_and_gets_a_second_triad(opened):
    """What `viewer.axes` reaches in napari's canvas axes overlay, by what it draws.

    napari's triad is drawn in lobemap's colors only if `Axes._default_color`
    is still the table `Axes.set_data` reads and `_on_data_change` still
    redraws from it; the anatomical triad is there only if a second `Axes`,
    built with the overlay's `_font_info`, still draws in its ViewBox.
    """
    from lobemap.core.model import anatomical_triad
    from lobemap.viewer import axes

    viewer = opened.viewer
    viewer.dims.ndisplay = 3
    axes.apply_axis_mode(viewer, opened.space)
    used = "viewer.axes.apply_axis_mode"
    where = "viewer.window._qt_viewer.canvas._viewer_overlay_to_visual[axes overlay]"
    with reaching(where, used):
        from napari._vispy.utils.qt_font import FontInfo
        from napari._vispy.visuals.axes import Axes
        from vispy.scene.node import Node

        canvas = viewer.window._qt_viewer.canvas
        vispys = list(canvas._viewer_overlay_to_visual[viewer.canvas.overlays["axes"]])
    need(len(vispys) == 1 and isinstance(getattr(vispys[0].node, "axes", None), Axes),
         f"{where}.node.axes, a napari._vispy.visuals.axes.Axes", used)
    overlay = vispys[0]
    need(isinstance(getattr(overlay, "_font_info", None), FontInfo),
         "VispyCanvasAxesOverlay._font_info", "viewer.axes._anatomy_triad")
    need(isinstance(getattr(overlay.node, "scene", None), Node),
         "VispyCanvasAxesOverlay.node.scene", "viewer.axes._anatomy_triad")
    need(callable(getattr(overlay, "_on_data_change", None)),
         "VispyCanvasAxesOverlay._on_data_change", used)
    need(len(getattr(overlay.node.axes, "_default_color", ())) == 6,
         "Axes._default_color, six RGBA", used)
    need({"axes", "reversed_axes", "colored", "bg_color", "dashed", "arrows", "text_offset"}
         <= set(inspect.signature(Axes.set_data).parameters),
         "Axes.set_data(axes=, reversed_axes=, colored=, bg_color=, dashed=, arrows=, "
         "text_offset=)", used)

    def drawn_colors(node) -> set:
        with reaching("Axes.line.color", used):
            return {tuple(np.round(c, 6)) for c in np.asarray(node.line.color, float)}

    def table(rows) -> set:
        return {tuple(np.round(c, 6)) for c in np.asarray(rows, float)[:3]}

    need(drawn_colors(overlay.node.axes) == table(axes.VOXEL_COLORS),
         "Axes._default_color read by Axes.set_data, redrawn by "
         "VispyCanvasAxesOverlay._on_data_change", used)
    second = getattr(overlay, axes._ANATOMY_ATTR, None)
    need(isinstance(second, Axes) and second.parent is overlay.node.scene and second.visible,
         "Axes(font_info=) parented into VispyCanvasAxesOverlay.node.scene",
         "viewer.axes._anatomy_triad")
    with reaching("Axes.text.text", used):
        labels = list(second.text.text)
    need(labels == list(anatomical_triad(opened.space)[1])[::-1]
         and drawn_colors(second) == table(axes.ANATOMY_COLORS),
         "Axes.set_data and Axes.text on a second Axes", used)


def test_the_window_and_canvas_lobemap_reaches(opened):
    from qtpy.QtWidgets import QMainWindow

    used = "viewer.chrome docking and viewer.view.maximize"
    with reaching("napari Window._qt_window", used):
        window = opened.viewer.window._qt_window
    need(isinstance(window, QMainWindow)
         and all(callable(getattr(window, name, None))
                 for name in ("addDockWidget", "splitDockWidget", "tabifyDockWidget",
                              "setTabPosition", "resizeDocks", "showNormal",
                              "showMaximized")),
         "Window._qt_window, a QMainWindow", used)
    used = "viewer.view.install_initial_fit"
    with reaching("viewer.window._qt_viewer.canvas.events", used):
        events = opened.viewer.window._qt_viewer.canvas.events
    need(all(hasattr(events, name) for name in
             ("resize", "draw", "mouse_press", "mouse_wheel", "key_press")),
         "QtViewer.canvas.events resize, draw, mouse_press, mouse_wheel and key_press", used)


def test_the_napari_chrome_lobemap_tidies(viewer):
    """What `viewer.chrome` reaches in napari's window: its dock class, which
    takes `close_btn` and keeps it when the dock floats; its buttons, which
    `tidy` hides; and its two layer docks, which `tidy` renames."""
    from qtpy.QtCore import Qt
    from qtpy.QtWidgets import QDockWidget, QLabel, QMenu, QWidget

    from lobemap.viewer import chrome

    used = "viewer.chrome.add_dock"
    where = "napari._qt.widgets.qt_viewer_dock_widget.QtViewerDockWidget(close_btn=False)"
    with reaching(where, used):
        dock = chrome.add_dock(viewer, QWidget(), "Lobemap dock", "left")
    need(isinstance(dock, QDockWidget) and not hasattr(dock.title, "close_button"),
         where, used)
    need(isinstance(viewer.window.window_menu, QMenu)
         and dock.toggleViewAction() in viewer.window.window_menu.actions(),
         "Window.window_menu, a QMenu", used)
    with reaching("QtViewerDockWidget rebuilding its title bar as it floats", used):
        dock.setFloating(True)
        dock.setFloating(False)
        title = dock.title
    need(not hasattr(title, "close_button") and title.title.text() == "Lobemap dock",
         "QtViewerDockWidget._update_title_bar, from its name and close_btn", used)

    used = "viewer.chrome.tidy"
    qt_viewer = viewer.window._qt_viewer
    buttons = {
        "viewerButtons": ("consoleButton", "ndisplayButton", "rollDimsButton",
                          "transposeDimsButton", "gridViewButton", "resetViewButton"),
        "layerButtons": ("newPointsButton", "newShapesButton", "newLabelsButton",
                         "deleteButton"),
    }
    for row, names in buttons.items():
        with reaching(f"QtViewer.{row}", used):
            frame = getattr(qt_viewer, row)
        # Hidden whole, so a button napari adds to the row is hidden too;
        # this says which ones that hides.
        held = frame.findChildren(QWidget, options=Qt.FindChildOption.FindDirectChildrenOnly)
        need({id(widget) for widget in held}
             == {id(getattr(frame, name, None)) for name in names},
             f"QtViewer.{row} holding {', '.join(names)} and no other widget", used)
    for name in ("dockLayerControls", "dockLayerList"):
        with reaching(f"QtViewer.{name}.name and .title.title", used):
            layer_dock = getattr(qt_viewer, name)
            label = layer_dock.title.title
        need(isinstance(layer_dock, QDockWidget) and isinstance(label, QLabel)
             and isinstance(layer_dock.name, str),
             f"QtViewer.{name}, a dock with a name and a title label", used)


def test_the_prefetch_finds_the_planes_a_step_lands_on(viewer):
    """`Dims.set_current_step` puts the point at start + k * step, and the copied
    transform maps it as `Layer.world_to_data` does, to the last bit: the keys
    the prefetch cuts planes under are the ones a step looks up."""
    from lobemap.viewer.napari_private import data_from_world
    from lobemap.viewer.view import mirror_matrix

    used = "viewer.prefetch.Plan.positions"
    layer = viewer.add_shapes(data=[], ndim=3)
    viewer.add_image(np.zeros((40, 30, 20), np.uint8), scale=(0.3, 0.25, 0.7))
    layer.affine = mirror_matrix(3, 7.3, 0)
    with reaching("Layer._transforms[1:].simplified.inverse", used):
        to_data = data_from_world(layer)
    for axis in range(3):
        start, _stop, step = viewer.dims.range[axis]
        for k in (0, 3, 17, int(viewer.dims.nsteps[axis]) - 1):
            viewer.dims.set_current_step(axis, k)
            point = viewer.dims.point
            need(point[axis] == start + k * step, "Dims.point after set_current_step", used)
            with reaching("Layer._transforms[1:].simplified.inverse", used):
                got = to_data(list(np.asarray(point)))
            need(np.array_equal(got, layer.world_to_data(point)),
                 "Layer._transforms[1:].simplified.inverse", used)


def test_a_step_can_be_seen_before_any_layer_is_sliced(opened):
    """`before_slicing` wraps `viewer._layer_slicer.submit`: the prefetch is told
    to give way before napari slices any layer for the step."""
    from lobemap.viewer.napari_private import before_slicing

    used = "viewer.contours (the prefetch's poke)"
    viewer, layer = opened.viewer, opened.image
    seen = []
    with reaching("viewer._layer_slicer.submit", used):
        before_slicing(viewer, lambda: seen.append("before"))
        before_slicing(viewer, lambda: None)       # one wrapper, however many hooks
    slice_dims = layer._slice_dims
    layer._slice_dims = lambda *a, **k: (seen.append("slice"), slice_dims(*a, **k))[1]
    axis = int(viewer.dims.order[0])
    viewer.dims.set_current_step(axis, (viewer.dims.current_step[axis] + 1)
                                 % int(viewer.dims.nsteps[axis]))
    need(seen[:2] == ["before", "slice"], "viewer._layer_slicer.submit slicing every layer",
         used)


def test_navis_says_whether_cmtk_is_installed():
    cmtk = pytest.importorskip("navis.transforms.cmtk")
    need(hasattr(cmtk, "_cmtkbin"), "navis.transforms.cmtk._cmtkbin",
         "core.spaces.cmtk_available")


def test_a_turned_view_rewrites_the_extent_napari_reads(viewer):
    """`hook_extent` swaps the layer list's class for one whose two cached
    extents go through lobemap; napari must read its slider ranges from
    `extent` and fit from `_extent_world_augmented`."""
    from functools import cached_property

    from napari.components.layerlist import LayerList

    from lobemap.viewer.napari_private import augmented_extent, hook_extent

    used = "viewer.turned.TurnedView, through napari_private.hook_extent"
    for name in ("extent", "_extent_world_augmented"):
        need(isinstance(LayerList.__dict__.get(name), cached_property),
             f"LayerList.{name}, a functools.cached_property", used)
    need(callable(getattr(viewer.layers, "_clean_cache", None)), "LayerList._clean_cache",
         used)
    need(callable(getattr(viewer, "_on_layers_change", None)),
         "ViewerModel._on_layers_change", used)
    layer = viewer.add_image(np.zeros((10, 20, 30), np.uint8), scale=(2.0, 1.0, 0.5))
    with reaching("Layer._extent_augmented", used):
        extent = augmented_extent(layer)
    need(np.allclose(extent.world, [[-1.0, -0.5, -0.25], [19.0, 19.5, 14.75]]),
         "Layer._extent_augmented, the world extent with the pixels' size", used)
    shifted = np.array([[100.0, 0.0, 0.0], [140.0, 50.0, 60.0]])
    hook_extent(viewer, ranges=lambda world, step: (shifted, step * 0 + 0.25),
                fit=lambda world: shifted)
    need([tuple(r) for r in viewer.dims.range]
         == [(100.0, 140.0, 0.25), (0.0, 50.0, 0.25), (0.0, 60.0, 0.25)],
         "viewer._on_layers_change setting dims.range from layers.extent", used)
    viewer.reset_view()
    need(np.allclose(viewer.scene.camera.center[-2:], [25.0, 30.0]),
         "ViewerModel.fit_to_view reading layers._extent_world_augmented", used)
    hook_extent(viewer)
    need(type(viewer.layers) is LayerList
         and tuple(viewer.dims.range[0]) == (0.0, 18.0, 2.0),
         "LayerList restored with its own extent", used)


def test_a_turned_image_picks_its_level_as_napari_draws(viewer):
    """`update_draw` asks a layer for its level and region with the arguments
    napari's canvas draw gives it, and `level_as_unturned` wraps that call."""
    from lobemap.viewer.napari_private import level_as_unturned, update_draw

    used = "viewer.turned.TurnedView, through napari_private.update_draw"
    canvas = viewer.window._qt_viewer.canvas
    with reaching("VispyCanvas._viewbox_corners_in_world / _current_viewbox_size", used):
        corners = np.asarray(canvas._viewbox_corners_in_world)
        size = tuple(canvas._current_viewbox_size)
    need(corners.shape[0] == 2 and len(size) == 2,
         "VispyCanvas._viewbox_corners_in_world (2, ndim) and _current_viewbox_size", used)
    need({"scale_factor", "corner_pixels_displayed", "shape_threshold"}
         <= set(inspect.signature(napari.layers.Image._update_draw).parameters),
         "Layer._update_draw(scale_factor=, corner_pixels_displayed=, shape_threshold=)",
         used)
    levels = [np.zeros((4, n, n), np.uint8) for n in (4096, 2048, 1024, 512, 256, 128)]
    layer = viewer.add_image(levels, multiscale=True)
    viewer.reset_view()
    with reaching("Layer._update_draw", used):
        update_draw(viewer, layer)
    plain = layer.data_level
    need(plain < len(levels) - 1 and np.any(layer.corner_pixels),
         "Layer._update_draw setting data_level and corner_pixels", used)
    from lobemap.viewer.napari_private import level_of, put_level, slice_now

    kept = level_of(layer)
    layer.data_level = len(levels) - 1
    with reaching("Image._data_level", used):
        put_level(layer, kept)
        slice_now(viewer, layer)
    need(callable(getattr(getattr(layer, "_slicing_state", None),
                          "set_slice_input_from_dims", None)),
         "Layer._slicing_state.set_slice_input_from_dims(dims, force)", used)
    need(layer.data_level == plain and np.array_equal(layer.corner_pixels, kept[1])
         and np.asarray(layer._slice.image.raw).shape[-1]
         == kept[1][1, 2] - kept[1][0, 2] + 1,
         "Image._data_level and corner_pixels read by the next slice", used)
    calls = []
    original = type(layer)._update_draw

    def spy(self, *args, **kwargs):
        calls.append(1)
        return original(self, *args, **kwargs)

    type(layer)._update_draw = spy
    try:
        level_as_unturned(layer, [[0.0, -1.0], [1.0, 0.0]])
        update_draw(viewer, layer)
    finally:
        type(layer)._update_draw = original
        level_as_unturned(layer, None)
    need(len(calls) == 1 and "_update_draw" not in layer.__dict__,
         "an instance _update_draw found before the class's", used)
