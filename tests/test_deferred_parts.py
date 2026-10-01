"""What a space builds late behaves as it did when everything was built at open.

A space opens with its primary atlas built; its other atlases and its
neuropil sets are built the first time their tab opens, and in 3D a large
stain shows a coarser pyramid level until the finer one has been read.
Each test drives the real controls, and compares what is drawn with a scene
built whole by `build_scene`, the way every scene used to open.
"""

from __future__ import annotations

import time

import numpy as np
import pytest
from viewer_harness import (
    assert_renders_loops,
    assert_rows_match_drawing,
    checked,
    drawn,
    hover,
    launched,
    layer_names,
    pump,
    session,
    switch_to,
    switcher,
)

from lobemap.viewer.deferred import STANDIN_NAME

pytestmark = pytest.mark.requires_data
pytest.importorskip("napari")

#: Every part a shipped space defers.
DEFERRED = [
    ("FAFB14", "fafb_neuropil"),
    ("JRCFIB2018F", "schlegel2021_s11"),
    ("JRCFIB2018F", "schlegel2021_s12"),
    ("JRCFIB2018F", "neuprint_hemibrain_neuropil"),
    ("JRCFIB2022M", "neuprint_cns_neuropil"),
]
STAINED = ("FAFB14", "JRCFIB2018F", "JRCFIB2022M")


def _buttons(tab):
    from qtpy.QtWidgets import QPushButton

    return {b.text(): b for b in tab.findChildren(QPushButton)}


def _open_tab(panel, name):
    """Click the tab, as a user does."""
    index = next(i for i in range(panel.count()) if panel.tabText(i) == name[:20])
    panel.setCurrentIndex(index)
    pump()
    return panel.currentWidget()


@pytest.mark.parametrize(("space", "name"), DEFERRED)
@pytest.mark.parametrize("ndisplay", ["3", "2"])
def test_a_deferred_part_is_built_when_its_tab_opens(monkeypatch, space, name, ndisplay):
    with launched(monkeypatch, "view", space, "--ndisplay", ndisplay) as (code, viewer):
        assert code == 0
        sess = session(viewer)
        assert name in sess.pending and name not in sess.surfaces
        before = layer_names(viewer)

        tab = _open_tab(sess.panel, name)
        assert tab is sess.panel.tabs[name]
        assert name in sess.surfaces and name not in sess.pending
        # Its mesh and its contours, in place of its stand-in if it had
        # one, and nothing of them drawn: it opens unchecked.
        after = layer_names(viewer)
        assert set(after) - set(before) == {tab.surface.layer.name,
                                            sess.contours[name].layer.name}
        assert set(before) - set(after) <= {STANDIN_NAME.format(name=name)}
        n = tab.table.rowCount()
        assert checked(tab) == set()
        assert tab.count.text() == f"0 / {n} shown"
        assert drawn(tab.surface, sess.contours[name]) == set()
        assert not tab.surface.layer.visible
        assert not sess.contours[name].layer.visible

        _buttons(tab)["Show all"].click()
        pump(300)
        assert checked(tab) == set(range(n))
        assert_rows_match_drawing(sess)
        if ndisplay == "3":
            assert drawn(tab.surface) == set(range(n))
        else:
            assert drawn(tab.surface, sess.contours[name]), "no outline on the plane"

        # And across the other mode and back, as every part always has.
        other = 5 - int(ndisplay)
        for mode in (other, int(ndisplay)):
            viewer.dims.ndisplay = mode
            pump(300)
            assert_rows_match_drawing(sess)


@pytest.mark.parametrize("ndisplay", [2, 3])
@pytest.mark.parametrize("space", STAINED)
def test_a_space_opens_with_the_sliders_and_view_of_its_whole_scene(registry, space,
                                                                   ndisplay):
    """As when every part was built at open: the same slider grid, the same fit."""
    import napari

    from lobemap.viewer.app import build_scene, load_space
    from lobemap.viewer.view import fit_view, orient_anterior

    late = napari.Viewer(show=False, ndisplay=ndisplay)
    whole = napari.Viewer(show=False, ndisplay=ndisplay)
    try:
        sess = load_space(late, registry, space)
        assert sess.pending
        build_scene(whole, registry, space)
        whole.dims.order = late.dims.order
        orient_anterior(whole, registry.spaces[space])      # as the load does, in 3D
        fit_view(whole)
        pump()
        assert late.dims.range == whole.dims.range
        np.testing.assert_array_equal(late.layers.extent.world, whole.layers.extent.world)
        assert late.camera.zoom == pytest.approx(whole.camera.zoom, rel=1e-9)
        np.testing.assert_allclose(late.camera.center, whole.camera.center, atol=1e-9)
    finally:
        late.close()
        whole.close()


@pytest.mark.parametrize("mirror", [False, True])
@pytest.mark.parametrize(("space", "name"), DEFERRED)
def test_building_a_deferred_part_moves_neither_the_sliders_nor_the_plane(
        monkeypatch, space, name, mirror):
    with launched(monkeypatch, "view", space, "--ndisplay", "2") as (code, viewer):
        assert code == 0
        sess = session(viewer)
        if mirror:
            switcher(viewer).mirror.click()
            pump()
        axis = int(viewer.dims.order[0])
        viewer.dims.set_current_step(axis, viewer.dims.current_step[axis] + 3)
        pump()
        sliders, plane = viewer.dims.range, viewer.dims.point
        camera = (viewer.camera.zoom, viewer.camera.center)

        tab = _open_tab(sess.panel, name)
        _buttons(tab)["Show all"].click()
        pump(300)
        assert name in sess.surfaces
        assert viewer.dims.range == sliders
        assert viewer.dims.point == plane
        assert (viewer.camera.zoom, viewer.camera.center) == camera
        assert_rows_match_drawing(sess)


def test_switching_a_stand_in_on_builds_its_part_and_shows_it(monkeypatch):
    """Its eye in the layer list does what the part's own layer's eye did."""
    with launched(monkeypatch, "view", "FAFB14", "--ndisplay", "2") as (code, viewer):
        assert code == 0
        sess = session(viewer)
        stand_in = viewer.layers[STANDIN_NAME.format(name="fafb_neuropil")]
        assert not stand_in.visible
        stand_in.visible = True
        pump(300)
        tab = sess.panel.tabs["fafb_neuropil"]
        # It became the part's mesh layer: no stand-in is left.
        assert tab.surface.layer is stand_in
        assert not [layer for layer in viewer.layers if "(not opened)" in layer.name]
        assert checked(tab) == set(range(tab.table.rowCount()))
        assert drawn(tab.surface, sess.contours["fafb_neuropil"])
        assert_rows_match_drawing(sess)


@pytest.mark.parametrize(("space", "name"), [("FAFB14", "fafb_neuropil"),
                                             ("JRCFIB2022M", "neuprint_cns_neuropil")])
def test_a_stand_in_deleted_by_hand_leaves_its_tab_working(monkeypatch, space, name):
    """Its tab builds the part in a layer of its own, the first time it opens."""
    with launched(monkeypatch, "view", space, "--ndisplay", "2") as (code, viewer):
        assert code == 0
        sess = session(viewer)
        viewer.layers.remove(viewer.layers[STANDIN_NAME.format(name=name)])
        pump()

        tab = _open_tab(sess.panel, name)
        assert tab is sess.panel.tabs[name]
        assert name in sess.surfaces and name not in sess.pending
        assert tab.surface.layer in viewer.layers
        assert sess.contours[name].layer in viewer.layers
        _buttons(tab)["Show all"].click()
        pump(300)
        assert checked(tab) == set(range(tab.table.rowCount()))
        assert drawn(tab.surface, sess.contours[name]), "no outline on the plane"
        assert_renders_loops(sess.contours[name])
        assert_rows_match_drawing(sess)


@pytest.mark.parametrize(("space", "name"), DEFERRED)
def test_a_part_built_under_the_mirror_is_drawn_mirrored(monkeypatch, space, name):
    """Built after the mirror was turned on, it is reflected like the rest."""
    from lobemap.viewer.view import MIRROR_AXIS, mirror_matrix

    with launched(monkeypatch, "view", space, "--ndisplay", "2") as (code, viewer):
        assert code == 0
        sess = session(viewer)
        switcher(viewer).mirror.click()
        pump()
        assert sess.mirrored
        center = sess.mirror_center

        tab = _open_tab(sess.panel, name)
        surface, contour = tab.surface, sess.contours[name]
        for layer in (surface.layer, contour.layer):
            np.testing.assert_allclose(layer.affine.affine_matrix,
                                       mirror_matrix(3, center), atol=1e-9)
        # The whole mesh, reflected about the scene's mirror plane.
        x = surface.meshset.vertices[:, MIRROR_AXIS]
        lo, hi = surface.layer.extent.world[:, MIRROR_AXIS]
        assert lo == pytest.approx(2 * center - x.max(), abs=1e-4)
        assert hi == pytest.approx(2 * center - x.min(), abs=1e-4)

        # And its outlines are drawn where that reflection puts them.
        _buttons(tab)["Show all"].click()
        pump(300)
        assert drawn(surface, contour), "no outline on the plane"
        assert_renders_loops(contour)
        assert_rows_match_drawing(sess)


@pytest.mark.parametrize("space", STAINED)
def test_every_part_built_late_matches_a_scene_built_whole(registry, space):
    """Same layers, same stacking order, same colors, widths and shading."""
    import napari

    from lobemap.viewer.app import build_scene, load_space

    late = napari.Viewer(show=False)
    whole = napari.Viewer(show=False)
    try:
        sess = load_space(late, registry, space, fit=False)
        for name in list(sess.pending):
            assert sess.panel.tab(name) is not None, name
        surfaces, contours = build_scene(whole, registry, space)
        pump()
        assert [layer.name for layer in late.layers] == [
            layer.name for layer in whole.layers]
        for name, surface in surfaces.items():
            got = sess.surfaces[name]
            for attr in ("shading", "blending", "opacity"):
                assert getattr(got.layer, attr) == getattr(surface.layer, attr), (name, attr)
            np.testing.assert_array_equal(got.colors, surface.colors)
            assert got.display_names == surface.display_names
            assert got.layer.metadata["lobemap"] == surface.layer.metadata["lobemap"]
            overlay = sess.contours[name]
            assert (overlay.color, overlay.width) == (contours[name].color,
                                                      contours[name].width), name
        assert ([layer.visible for layer in sess.images]
                == [layer.visible for layer in whole.layers
                    if layer.metadata.get("lobemap", {}).get("kind") in ("image", "labels")])
    finally:
        late.close()
        whole.close()


@pytest.mark.parametrize("space", STAINED)
def test_the_mirror_plane_is_where_it_was(registry, space):
    """The mid-plane of every part, within half a slider step, built or not."""
    import napari

    from lobemap.viewer.app import build_scene, load_space
    from lobemap.viewer.view import MIRROR_AXIS, mirror_center

    late = napari.Viewer(show=False)
    whole = napari.Viewer(show=False)
    try:
        sess = load_space(late, registry, space, fit=False)
        surfaces, _ = build_scene(whole, registry, space)
        images = [layer for layer in whole.layers
                  if layer.metadata.get("lobemap", {}).get("kind") in ("image", "labels")]
        want = mirror_center([s.layer for s in surfaces.values()] + images)
        step = late.dims.range[MIRROR_AXIS].step
        assert abs(sess.mirror_center - want) <= step / 2 + 1e-9
    finally:
        late.close()
        whole.close()


def test_a_deferred_shell_is_picked_once_built(monkeypatch):
    with launched(monkeypatch, "view", "FAFB14") as (code, viewer):
        sess = session(viewer)
        _buttons(sess.panel.tabs["benton2025"])["Show none"].click()
        tab = _open_tab(sess.panel, "fafb_neuropil")
        names = tab.surface.meshset.names
        index = next(i for i, n in enumerate(names) if n.startswith("AL"))
        tab.select([index])
        pump(300)
        assert hover(viewer, tab.surface.meshset.centroid(index)).startswith(
            "fafb_neuropil:")


def test_a_deferred_part_that_cannot_be_read_says_so_in_its_tab(monkeypatch):
    from lobemap.core.registry import Registry

    real = Registry.mesh

    def mesh(self, asset_id):
        if asset_id == "fafb_neuropil":
            raise OSError("fafb_neuropil is unreadable")
        return real(self, asset_id)

    monkeypatch.setattr(Registry, "mesh", mesh)
    with launched(monkeypatch, "view", "FAFB14", "--ndisplay", "2") as (code, viewer):
        assert code == 0
        sess = session(viewer)
        before = layer_names(viewer)
        page = _open_tab(sess.panel, "fafb_neuropil")
        from qtpy.QtWidgets import QLabel

        assert any("could not be loaded" in label.text()
                   for label in page.findChildren(QLabel))
        assert layer_names(viewer) == before
        assert "fafb_neuropil" in sess.pending
        # The rest of the scene carries on, the mirror included.
        assert_rows_match_drawing(sess)
        sess.set_mirror(True)
        pump()
        assert_rows_match_drawing(sess)


# -- the 3D pyramid level ---------------------------------------------------


def _wait(predicate, seconds: float = 30.0) -> bool:
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        pump(20)
        if predicate():
            return True
    return False


def _rendered(layer) -> np.ndarray:
    """The voxels the layer hands to its visual."""
    return np.asarray(layer._slice.image.raw)


@pytest.mark.parametrize("space", STAINED)
def test_3d_renders_the_same_pyramid_level_once_it_is_read(monkeypatch, space):
    from lobemap.viewer.images import coarse_level_for_3d, level_for_3d

    with launched(monkeypatch, "view", space) as (code, viewer):
        assert code == 0
        image = session(viewer).images[0]
        levels = list(image.data)
        fine = level_for_3d(levels)
        coarse = coarse_level_for_3d(levels, fine)
        assert coarse > fine
        # At once: a coarser level of the same image, drawn.
        assert image.visible and image.data_level == coarse
        assert _rendered(image).shape == tuple(levels[coarse].shape)

        assert _wait(lambda: image.data_level == fine), "the fine level never came"
        assert image.locked_data_level == fine
        store = session(viewer).registry.volume(image.metadata["lobemap"]["asset"])
        got = _rendered(image)
        assert got.shape == tuple(levels[fine].shape)
        # The same voxels, spot-checked on a grid of planes.
        np.testing.assert_array_equal(got[::97], np.asarray(store.levels[fine][::97]))

        # 2D releases it; 3D pins it again at once, with no second read.
        viewer.dims.ndisplay = 2
        pump()
        assert image.locked_data_level is None
        viewer.dims.ndisplay = 3
        pump()
        assert image.data_level == fine
        assert _rendered(image).shape == tuple(levels[fine].shape)


def test_a_switch_before_the_fine_level_arrives_leaves_nothing(monkeypatch):
    from lobemap.viewer import images

    with launched(monkeypatch, "view", "FAFB14") as (code, viewer):
        old = session(viewer).images[0]
        fine = images._FINE[old]
        switch_to(viewer, "GRABE")
        assert session(viewer).space == "GRABE"
        # Long enough for the read to finish; its result is dropped.
        pump(3000)
        assert fine.array is None
        assert all(name.startswith(("grabe", "Grabe")) for name in layer_names(viewer))
        assert_rows_match_drawing(session(viewer))


def test_closing_the_viewer_before_the_fine_level_arrives_stops_its_read(monkeypatch):
    """Nothing is swapped into the closed viewer's layer, and the read ends."""
    import threading

    from lobemap.viewer import chunkcache, images

    real = chunkcache._ChunkFiles.read

    def slow(self, idx):
        time.sleep(0.004)                    # a cold disk: the read outlasts the open
        return real(self, idx)

    monkeypatch.setattr(chunkcache._ChunkFiles, "read", slow)
    with launched(monkeypatch, "view", "FAFB14") as (code, viewer):
        assert code == 0
        image = session(viewer).images[0]
        fine = images._FINE[image]
        coarse = image.data_level
        assert coarse == fine.coarse and fine.array is None
        assert any(t.name == "lobemap-3d-level" for t in threading.enumerate())
    # Closed: long enough for the whole read and the poll that would swap it in.
    pump(2500)
    assert fine.array is None
    assert image.data_level == coarse
    assert _rendered(image).shape == tuple(image.data[coarse].shape)
    assert not any(t.name == "lobemap-3d-level" for t in threading.enumerate())


# -- the meshes, read ahead -------------------------------------------------


def _count_loads(monkeypatch, slow: dict | None = None):
    """Each mesh file read, in order, with when it started; `slow` delays some by path stem."""
    from lobemap.core.meshfmt import MeshSet

    real = MeshSet.load.__func__
    loads = []

    def load(cls, path, *args, **kwargs):
        from pathlib import Path

        loads.append((Path(path).stem, time.perf_counter()))
        time.sleep((slow or {}).get(Path(path).stem, 0.0))
        return real(cls, path, *args, **kwargs)

    monkeypatch.setattr(MeshSet, "load", classmethod(load))
    return loads


def _read_ahead_done() -> bool:
    import threading

    return not any(t.name == "lobemap-meshes" for t in threading.enumerate())


@pytest.mark.parametrize("space", ["FAFB14", "JRCFIB2018F", "JRCFIB2022M"])
def test_a_tab_opened_after_the_read_ahead_reads_no_mesh(monkeypatch, space):
    """A neuropil set's mesh is read once, in the background, and no tab reads one.

    An atlas's mesh is read with the registry, for its compartment names.
    """
    loads = _count_loads(monkeypatch)
    with launched(monkeypatch, "view", space, "--ndisplay", "2") as (code, viewer):
        assert code == 0
        sess = session(viewer)
        shells = [sess.parts[n].asset.path.stem for n in sess.pending
                  if sess.parts[n].reference]
        assert shells
        pump(50)
        assert _wait(_read_ahead_done)
        read = list(loads)
        for name in list(sess.pending):
            tab = _open_tab(sess.panel, name)
            assert tab is sess.panel.tabs[name]
        assert loads == read, "a tab read its mesh"
        names = [stem for stem, _ in loads]
        assert all(names.count(stem) == 1 for stem in shells), names


def test_a_tab_opened_while_its_mesh_is_read_waits_for_that_read(monkeypatch):
    loads = _count_loads(monkeypatch, slow={"neuprint_hemibrain_neuropil": 0.5})
    with launched(monkeypatch, "view", "JRCFIB2018F", "--ndisplay", "2") as (code, viewer):
        assert code == 0
        sess = session(viewer)
        assert _wait(lambda: any(s == "neuprint_hemibrain_neuropil" for s, _ in loads))
        tab = _open_tab(sess.panel, "neuprint_hemibrain_neuropil")
        assert tab is sess.panel.tabs["neuprint_hemibrain_neuropil"]
        assert [s for s, _ in loads].count("neuprint_hemibrain_neuropil") == 1
        _buttons(tab)["Show all"].click()
        pump(300)
        assert_rows_match_drawing(sess)


def test_the_read_ahead_waits_while_the_slider_moves(monkeypatch):
    from lobemap.viewer import deferred

    # A pause it waits for that no machine load can fake between two steps.
    monkeypatch.setattr(deferred, "QUIET_S", 0.5)
    loads = _count_loads(monkeypatch)
    with launched(monkeypatch, "view", "JRCFIB2018F", "--ndisplay", "2") as (code, viewer):
        assert code == 0
        axis = int(viewer.dims.order[0])
        start = viewer.dims.current_step[axis]
        before = len(loads)
        # From before the event loop first turns, which is when it starts.
        for k in range(40):                 # about a second of steps
            viewer.dims.set_current_step(axis, start + 1 + k % 6)
            pump(20)
        stopped = time.perf_counter()
        assert all(at > stopped for _, at in loads[before:]), (
            "a mesh was read while the slider moved")
        assert _wait(_read_ahead_done)
        assert "neuprint_hemibrain_neuropil" in [s for s, _ in loads[before:]]


def test_closing_the_viewer_stops_the_read_ahead(monkeypatch):
    from lobemap.viewer import deferred

    # Kept waiting by one step until the viewer has closed.
    monkeypatch.setattr(deferred, "QUIET_S", 5.0)
    loads = _count_loads(monkeypatch)
    with launched(monkeypatch, "view", "JRCFIB2018F", "--ndisplay", "2") as (code, viewer):
        assert code == 0
        before = len(loads)
        axis = int(viewer.dims.order[0])
        viewer.dims.set_current_step(axis, viewer.dims.current_step[axis] + 1)
        pump(100)
        assert not _read_ahead_done(), "it should be waiting"
    assert _wait(_read_ahead_done, seconds=1.0)
    assert len(loads) == before
