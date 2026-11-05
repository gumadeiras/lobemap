"""Spatial culling preserves exact hits and keeps large meshes cheap to query."""

from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pytest
import trimesh

from lobemap.core.meshfmt import MeshSet
from lobemap.viewer.picking import MeshPicker


@pytest.fixture
def meshset():
    sphere = trimesh.creation.icosphere(subdivisions=5)
    return MeshSet.from_parts([
        ("front", sphere.vertices, sphere.faces),
        ("back", sphere.vertices + (3, 0, 0), sphere.faces),
    ])


def _rays():
    rng = np.random.default_rng(3)
    for y, z in rng.uniform(-1.2, 1.2, (32, 2)):
        yield np.array([-10., y, z]), np.array([1., 0., 0.])
    yield np.array([-10., 0., 0.]), np.array([1., 0., 0.])
    yield np.array([-10., 0.1, 0.2]), np.array([1., 0.01, 0.02]) / np.linalg.norm([1, .01, .02])
    for vector in ((1., 1., 1.), (-.8, .6, .4), (.3, .2, .93)):
        direction = np.asarray(vector) / np.linalg.norm(vector)
        for point in rng.uniform(-.8, .8, (8, 3)):
            yield point - 10 * direction, direction


def _wait_for_index(surface):
    from viewer_harness import pump

    assert surface._pick_job is not None, "showing the surface did not start indexing"
    for _ in range(100):
        pump(30)
        if not surface._pick_job.running:
            break
    assert not surface._pick_job.running
    assert set(surface._picker._trees) == set(surface._picker.large)


@pytest.mark.parametrize("selection,first", [({0, 1}, None), ({1}, None),
                                              ({0, 1}, 11.1), (set(), None)])
def test_indexed_hits_match_full_scans(meshset, selection, first, monkeypatch):
    from napari.utils import geometry

    picker = MeshPicker(meshset)
    rays = list(_rays())
    expected = [picker.pick(p, d, selection, first) for p, d in rays]
    picker.install(picker.prepare())
    tested = []
    original = geometry.line_in_triangles_3d

    def count(start, direction, triangles):
        tested.append(len(triangles))
        return original(start, direction, triangles)

    monkeypatch.setattr(geometry, "line_in_triangles_3d", count)
    assert [picker.pick(p, d, selection, first) for p, d in rays] == expected
    assert not tested or max(tested) < len(meshset.faces) // 10
    with ThreadPoolExecutor(max_workers=4) as pool:
        actual = list(pool.map(lambda ray: picker.pick(*ray, selection, first), rays * 4))
    assert actual == expected * 4


def test_surface_picking_uses_cached_bounds_and_keeps_mirror_and_eye_semantics(meshset,
                                                                            monkeypatch):
    import napari
    from napari.layers import Surface

    from lobemap.viewer.layers import AtlasSurface

    viewer = napari.Viewer(show=False, ndisplay=3)
    surface = AtlasSurface(viewer, meshset, "neurons")
    try:
        # Prepare through the production background job, not on the first pick.
        _wait_for_index(surface)
        rays = list(_rays())
        expected = []
        for p, d in rays:
            hit = surface.layer.get_value(p, view_direction=d, dims_displayed=[0, 1, 2],
                                          world=True)
            hit = hit[0] if isinstance(hit, tuple) else hit
            expected.append(None if hit is None else round(float(hit)))
        assert [surface.pick(p, d, [0, 1, 2]) for p, d in rays] == expected

        def refuse(layer):
            raise AssertionError("picking scanned the uploaded vertices for bounds")

        with monkeypatch.context() as patch:
            patch.setattr(Surface, "_extent_data", property(refuse))
            assert [surface.pick(p, d, [0, 1, 2]) for p, d in rays] == expected

        # The eye is between the two spheres: the front one is behind it.
        p, d = np.array([1.5, 0., 0.]), np.array([1., 0., 0.])
        assert surface.pick(p, d, [0, 1, 2]) == 0
        assert surface.pick(p, d, [0, 1, 2], from_position=True) == 1
        surface.set_mirror(0, 5)
        p[0], d[0] = 10 - p[0], -d[0]
        assert surface.pick(p, d, [0, 1, 2], from_position=True) == 1
        surface.set_selection({0})
        assert surface.pick(p, d, [0, 1, 2], from_position=True) is None
        surface.compact()
        assert surface.pick(p, d, [0, 1, 2]) == 0
    finally:
        surface.stop()
        viewer.close()


def test_an_empty_compartment_cannot_answer_a_ray():
    mesh = MeshSet.from_parts([("empty", np.empty((0, 3)), np.empty((0, 3), np.int64))])
    picker = MeshPicker(mesh)
    assert picker.pick(np.zeros(3), np.array([1., 0., 0.]), {0}) is None


@pytest.mark.parametrize("show", ["layer eye", "selection", "display mode"])
def test_every_3d_show_path_prepares_the_index_once(meshset, show):
    import napari
    from viewer_harness import pump

    from lobemap.viewer.app import install_display_mode
    from lobemap.viewer.contours import ContourOverlay
    from lobemap.viewer.layers import AtlasSurface

    viewer = napari.Viewer(show=False, ndisplay=2)
    viewer.add_image(np.zeros((8, 8, 8), np.uint8))
    selection = [0, 1] if show == "display mode" else []
    surface = AtlasSurface(viewer, meshset, "neurons", selection=selection, visible=False)
    contour = ContourOverlay(viewer, meshset, "neurons", "red", selection=set(selection))
    handlers = install_display_mode(viewer, {"neurons": surface}, {"neurons": contour})
    try:
        assert surface._pick_job is None
        viewer.dims.ndisplay = 3
        if show == "layer eye":
            surface.layer.visible = True
        elif show == "selection":
            surface.set_selection({0, 1})
        _wait_for_index(surface)
        pump(surface.compact_delay_ms + 30)
        assert surface.pick(np.zeros(3), np.array([1., 0., 0.]), [0, 1, 2]) == 0
        job = surface._pick_job
        surface.layer.visible = False
        surface.layer.visible = True
        viewer.dims.ndisplay = 2
        viewer.dims.ndisplay = 3
        assert surface._pick_job is job, "showing the same mesh rebuilt its index"
    finally:
        for event, handler in handlers:
            event.disconnect(handler)
        surface.stop()
        contour.stop()
        viewer.close()


@pytest.mark.parametrize("cancel_during", [0, 1])
def test_removal_stops_later_builds_and_discards_the_current_result(meshset, monkeypatch,
                                                                  cancel_during):
    import threading

    import napari
    from viewer_harness import pump

    from lobemap.viewer.layers import AtlasSurface

    entered, release, finished = (threading.Event() for _ in range(3))
    builds, results = [], []
    bounds_tree, prepare = trimesh.triangles.bounds_tree, MeshPicker.prepare

    def build(triangles):
        builds.append(len(triangles))
        if len(builds) == cancel_during + 1:
            entered.set()
            assert release.wait(5)
        return bounds_tree(triangles)

    def observed(picker):
        try:
            result = prepare(picker)
            results.append(result)
            return result
        finally:
            finished.set()

    monkeypatch.setattr(trimesh.triangles, "bounds_tree", build)
    monkeypatch.setattr(MeshPicker, "prepare", observed)
    viewer = napari.Viewer(show=False, ndisplay=3)
    surface = AtlasSurface(viewer, meshset, "neurons")
    try:
        assert entered.wait(5)
        surface.stop()
        release.set()
        assert finished.wait(5)
        pump(100)
        assert len(builds) == cancel_during + 1, "removal did not stop later compartment builds"
        assert results == [{}], "the cancelled job retained unused indices"
        assert not surface._picker._trees
    finally:
        release.set()
        surface.stop()
        viewer.close()


def test_first_eye_show_prepares_an_already_selected_mesh(meshset):
    import napari

    from lobemap.viewer.layers import AtlasSurface

    viewer = napari.Viewer(show=False, ndisplay=3)
    surface = AtlasSurface(viewer, meshset, "neurons", visible=False)
    try:
        assert surface.selection == {0, 1} and surface._pick_job is None
        surface.layer.visible = True
        _wait_for_index(surface)
    finally:
        surface.stop()
        viewer.close()


def test_a_cancelled_picker_does_not_start_preparation(meshset, monkeypatch):
    def refuse(triangles):
        raise AssertionError("a cancelled picker started an index build")

    picker = MeshPicker(meshset)
    picker.cancel()
    monkeypatch.setattr(trimesh.triangles, "bounds_tree", refuse)
    assert picker.prepare() == {}
