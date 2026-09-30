"""Every private internal the viewer relies on, by name and shape.

napari offers no public way to draw a visual under a layer or to keep a
slice step from recomputing every layer's extent, and bermuda, vispy and
zarr are reached below their documented surface in places too. pyproject
pins napari to the minor version all of this was written against. After
any upgrade, a failure here names what moved and which module uses it,
instead of the viewer misdrawing or slowing down without a word.
"""

from __future__ import annotations

import inspect

import numpy as np
import pytest

napari = pytest.importorskip("napari")


def need(ok, what: str, used_by: str) -> None:
    assert ok, f"{what} is missing or has changed shape; {used_by} relies on it"


@pytest.fixture
def viewer():
    v = napari.Viewer(show=False, ndisplay=2)
    yield v
    v.close()


def test_napari_is_the_pinned_minor_version():
    major, minor = (int(p) for p in napari.__version__.split(".")[:2])
    need((major, minor) == (0, 9), f"napari {napari.__version__} (0.9 is pinned)",
         "every check below")


def test_a_layer_has_a_vispy_node_to_draw_under(viewer):
    from vispy.scene.node import Node

    from lobemap.viewer.napari_private import layer_visual

    layer = viewer.add_shapes(data=[], ndim=3)
    visual = layer_visual(viewer, layer)
    where = "viewer.window._qt_viewer.canvas.layer_to_visual[layer]"
    need(isinstance(visual.node, Node), f"{where}.node", "viewer.contours.SliceVisual")
    font = visual.font_info
    need(hasattr(font, "font_manager") and hasattr(font, "face"), f"{where}.font_info",
         "viewer.contours.SliceVisual labels")


def test_napari_text_visual_takes_labels(viewer):
    from lobemap.viewer.napari_private import layer_visual, text_visual

    layer = viewer.add_shapes(data=[], ndim=3)
    visual = layer_visual(viewer, layer)
    text = text_visual(visual.node, visual.font_info)
    used = "viewer.contours.SliceVisual labels (napari._vispy.visuals.text.Text)"
    text.font_size = 10.5
    text.anchors = ("center", "center")
    text.text = ["DA1", "DM1"]
    text.pos = np.zeros((2, 2), np.float32)
    text.color = np.ones((2, 4), np.float32)
    need(text.parent is visual.node, "Text(parent=, font_info=)", used)
    need(list(text.text) == ["DA1", "DM1"] and text.color.rgba.shape == (2, 4),
         "Text.text / Text.color per label", used)


def test_every_blending_has_a_gl_state():
    """A key vispy's `set_gl_state` takes: a GL flag, or a `set_<key>` setter."""
    from napari.layers.base._base_constants import Blending
    from vispy.gloo.wrappers import BaseGlooFunctions

    from lobemap.viewer.napari_private import gl_state

    for blending in Blending:
        state = gl_state(str(blending))
        need(state and all(isinstance(value, bool) or hasattr(BaseGlooFunctions, f"set_{key}")
                           for key, value in state.items()),
             f"napari._vispy.utils.gl.BLENDING_MODES[{blending!s}]",
             "viewer.contours.SliceVisual blending")


def test_a_slice_step_goes_through_slice_dims_and_clears_the_extent(viewer):
    """What `keep_extent_while_slicing` wraps, and what it relies on napari doing."""
    layer = viewer.add_image(np.zeros((6, 4, 4), np.uint8))
    used = "viewer.napari_private.keep_extent_while_slicing"
    need(callable(getattr(layer, "_slice_dims", None)), "Layer._slice_dims", used)
    need(callable(getattr(layer, "_clear_extent", None)), "Layer._clear_extent", used)
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


def test_napari_triangulation_without_bermuda():
    from lobemap.viewer.napari_private import triangulate_edge, triangulate_face

    square = np.array([[0, 0], [0, 1], [1, 1], [1, 0]], np.float32)
    centers, offsets, triangles = triangulate_edge(square)
    used = "viewer.contours outlines and fills without bermuda"
    need(centers.shape == offsets.shape and centers.shape[1] == 2 and triangles.shape[1] == 3,
         "napari.layers.shapes._shapes_utils.triangulate_edge", used)
    points, faces = triangulate_face(square)
    need(np.asarray(points).shape[1] == 2 and np.asarray(faces).shape[1] == 3,
         "napari's normalize_vertices_and_edges + triangulate_face_vispy", used)


def test_bermuda_strokes_and_fills():
    bermuda = pytest.importorskip("bermuda")
    ring = np.array([[0, 0], [0, 2], [1, 3], [2, 2], [2, 0]], np.float32)
    used = "viewer.contours outlines and fills"
    centers, offsets, triangles = bermuda.triangulate_path_edge(ring, closed=True, limit=3.0)
    need(centers.shape == offsets.shape and triangles.shape[1] == 3,
         "bermuda.triangulate_path_edge(ring, closed=, limit=)", used)
    triangles, points = bermuda.triangulate_polygons_face([ring])
    need(triangles.shape[1] == 3 and points.shape[1] == 2,
         "bermuda.triangulate_polygons_face -> (triangles, points)", used)


def test_vispy_mesh_takes_and_gives_back_its_buffers(viewer):
    from vispy.scene.visuals import Mesh

    mesh = Mesh()
    vertices = np.array([[0, 0], [1, 0], [0, 1]], np.float32)
    mesh.set_data(vertices=vertices, faces=np.array([[0, 1, 2]], np.uint32),
                  vertex_colors=np.ones((3, 4), np.float32))
    data = mesh.mesh_data
    used = "viewer.contours.SliceVisual and the tests' rendered-buffer readers"
    need(np.array_equal(np.asarray(data.get_vertices())[:, :2], vertices)
         and np.asarray(data.get_vertex_colors()).shape == (3, 4),
         "vispy MeshVisual.set_data / mesh_data", used)
    need(callable(getattr(mesh, "get_transform", None)), "vispy Node.get_transform", used)


def test_zarr_v2_metadata_the_chunk_reader_reads(tmp_path):
    import zarr
    from numcodecs import Zstd
    from zarr.storage import LocalStore

    arr = zarr.create_array(store=str(tmp_path / "a.zarr"), shape=(4, 4), chunks=(2, 2),
                            dtype="u1", zarr_format=2, compressors=Zstd())
    arr = zarr.open_array(str(tmp_path / "a.zarr"), mode="r")
    meta = arr.metadata
    used = "viewer.chunkcache._ChunkFiles"
    for name in ("zarr_format", "filters", "order", "compressor", "fill_value",
                 "encode_chunk_key"):
        need(hasattr(meta, name), f"zarr ArrayV2Metadata.{name}", used)
    need(isinstance(arr.store, LocalStore) and hasattr(arr.store, "root")
         and arr.path == "", "zarr LocalStore.root and Array.path", used)
    need(meta.encode_chunk_key((1, 0)) == "1.0", "ArrayV2Metadata.encode_chunk_key", used)


def test_what_the_slice_benchmark_reaches_into(viewer):
    from napari._qt.qt_viewer import QtViewer

    used = "benchmarks/slice_step.py"
    need(callable(getattr(QtViewer._on_slice_ready, "__wrapped__", None)),
         "QtViewer._on_slice_ready.__wrapped__", used)
    need(hasattr(viewer._layer_slicer, "_force_sync"), "viewer._layer_slicer._force_sync", used)
    need(callable(getattr(viewer.window._qt_viewer.canvas, "on_draw", None)),
         "QtViewer.canvas.on_draw", used)
    layer = viewer.add_image([np.zeros((8, 8, 8)), np.zeros((4, 4, 4))], multiscale=True)
    need(hasattr(layer, "_data_level") and np.asarray(layer.corner_pixels).shape == (2, 3),
         "Image._data_level and Image.corner_pixels", used)


def test_what_the_axes_and_camera_code_reaches_into(viewer):
    from napari._vispy.visuals.axes import Axes

    need(inspect.isclass(Axes), "napari._vispy.visuals.axes.Axes", "viewer.axes")
    need(hasattr(viewer.window._qt_viewer, "canvas"), "viewer.window._qt_viewer.canvas",
         "viewer.axes and viewer.view")
