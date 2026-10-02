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
    node_determinant,
    pump,
    session,
    shaded_normals,
    signed_volume,
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
        assert late.scene.camera.zoom == pytest.approx(whole.scene.camera.zoom, rel=1e-9)
        np.testing.assert_allclose(late.scene.camera.center, whole.scene.camera.center, atol=1e-9)
    finally:
        late.close()
        whole.close()


#: The plane eaa535f, the last revision that built every part at open, landed
#: on along x, y and z when that slice axis was chosen right after a space
#: opened in 2D, or opened in 3D and then went to 2D. Measured on an export
#: of it with this data.
EAA535F_PLANES = {
    ("FAFB14", "2"): (490.0419, 252.5266, 46.8532),
    ("FAFB14", "3"): (490.1573, 252.5266, 46.8532),
    ("JRCFIB2018F", "2"): (137.25, 270.5, 210.0),
    ("JRCFIB2018F", "3"): (137.5, 270.5, 210.0),
    ("JRCFIB2022M", "2"): (435.35, 233.8, 109.8),
    ("JRCFIB2022M", "3"): (435.35, 233.8, 109.8),
    ("GRABE", "2"): (130.56, 87.04, 56.64),
    ("GRABE", "3"): (130.56, 87.04, 56.64),
}


@pytest.mark.parametrize("axis", [0, 1, 2])
@pytest.mark.parametrize(("space", "ndisplay"), list(EAA535F_PLANES))
def test_a_slice_axis_chosen_right_after_the_open_lands_where_it_did(monkeypatch, space,
                                                                     ndisplay, axis):
    """Where napari put the sliders when the first neuropil set was built first."""
    with launched(monkeypatch, "view", space, "--ndisplay", ndisplay) as (code, viewer):
        assert code == 0
        control = switcher(viewer).slice
        control.setCurrentIndex(control.findData(axis))
        pump()
        if ndisplay == "3":
            viewer.dims.ndisplay = 2
            pump()
        assert int(viewer.dims.order[0]) == axis
        assert viewer.dims.point[axis] == pytest.approx(
            EAA535F_PLANES[(space, ndisplay)][axis], abs=1e-3)
        assert_rows_match_drawing(session(viewer))


@pytest.mark.parametrize("axis", [0, 1, 2])
@pytest.mark.parametrize(("space", "ndisplay"),
                         [key for key in EAA535F_PLANES if key[0] != "FAFB14"])
def test_a_slice_axis_chosen_right_after_a_switch_lands_where_it_did(monkeypatch, space,
                                                                     ndisplay, axis):
    """Where it lands when the space opens: eaa535f tore the old scene down first,
    so napari put the sliders as for a space opened alone. Switched from FAFB14
    opened in the same mode."""
    with launched(monkeypatch, "view", "FAFB14", "--ndisplay", ndisplay) as (code, viewer):
        assert code == 0
        switch_to(viewer, space)
        assert session(viewer).space == space
        control = switcher(viewer).slice
        control.setCurrentIndex(control.findData(axis))
        pump()
        if ndisplay == "3":
            viewer.dims.ndisplay = 2
            pump()
        assert int(viewer.dims.order[0]) == axis
        assert viewer.dims.point[axis] == pytest.approx(
            EAA535F_PLANES[(space, ndisplay)][axis], abs=1e-3)
        assert_rows_match_drawing(session(viewer))


@pytest.mark.parametrize("ndisplay", ["2", "3"])
def test_a_switch_moves_the_sliders_once_the_scene_it_replaces_is_gone(monkeypatch,
                                                                       ndisplay):
    """And in 3D, where they draw nothing, once 2D is entered.

    Moving them slices every shown layer again, and napari draws a 3D surface
    anew: 42 of 51 ms in a switch from FAFB14, when they were moved while it
    was still loaded.
    """
    from lobemap.viewer import scene

    real, moves = scene.center_sliders, []

    def center_sliders(viewer, *args, **kwargs):
        moves.append(({layer.name for layer in viewer.layers}, viewer.dims.ndisplay))
        return real(viewer, *args, **kwargs)

    monkeypatch.setattr(scene, "center_sliders", center_sliders)
    with launched(monkeypatch, "view", "FAFB14", "--ndisplay", ndisplay) as (code, viewer):
        assert code == 0
        assert len(moves) == 1, "the open put the sliders where they belong"
        old = set(layer_names(viewer))
        switch_to(viewer, "JRCFIB2018F")
        assert session(viewer).space == "JRCFIB2018F"
        if ndisplay == "3":
            assert len(moves) == 1, "the sliders moved in 3D"
            viewer.dims.ndisplay = 2
            pump()
        assert len(moves) == 2
        names, mode = moves[1]
        assert not names & old, "the sliders moved beside the scene being replaced"
        assert mode == 2
        viewer.dims.ndisplay = 5 - int(ndisplay)
        pump()
        viewer.dims.ndisplay = int(ndisplay)
        pump()
        assert len(moves) == 2, "the sliders moved a second time"


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
        camera = (viewer.scene.camera.zoom, viewer.scene.camera.center)

        tab = _open_tab(sess.panel, name)
        _buttons(tab)["Show all"].click()
        pump(300)
        assert name in sess.surfaces
        assert viewer.dims.range == sliders
        assert viewer.dims.point == plane
        assert (viewer.scene.camera.zoom, viewer.scene.camera.center) == camera
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
        # The outlines ride the affine; the surface reflects its vertices,
        # and so carries none, a stand-in it took over included.
        np.testing.assert_allclose(contour.layer.affine.affine_matrix,
                                   mirror_matrix(3, center), atol=1e-9)
        np.testing.assert_allclose(surface.layer.affine.affine_matrix, np.eye(4), atol=1e-9)
        assert surface.mirrored
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

        # Lit from outside, as a part built before the mirror is: read in 3D
        # off the node vispy shades, its geometry is not inside-out and its
        # transform is proper (`AtlasSurface._present`).
        viewer.dims.ndisplay = 3
        pump(300)
        v, f, _ = surface.meshset.select(sorted(surface.selection))
        plain = signed_volume(np.asarray(v, float), np.asarray(f))
        assert plain > 0, "unmirrored normals already point inward"
        assert shaded_normals(viewer, surface)[0] == pytest.approx(plain, rel=1e-4), (
            "the reflected geometry is inside-out under the mirror")
        assert node_determinant(viewer, surface) > 0, (
            "the surface is reflected by a transform, which lights it from inside")


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


def test_3d_uploads_the_stain_level_once_and_not_on_every_entry(monkeypatch):
    """The pinned level is 255-613 MB, and uploading it again on every entry
    into 3D was 0.35-0.55 s of the first frame. It is uploaded when it comes,
    and again only when other voxels do; a contrast set in 2D reaches 3D."""
    from vispy.visuals.volume import VolumeVisual

    from lobemap.viewer.images import level_for_3d
    from lobemap.viewer.napari_private import layer_visual

    uploads = []
    upload = VolumeVisual.set_data

    def counted(self, vol, *args, **kwargs):
        uploads.append(tuple(vol.shape))
        return upload(self, vol, *args, **kwargs)

    monkeypatch.setattr(VolumeVisual, "set_data", counted)
    with launched(monkeypatch, "view", "FAFB14") as (code, viewer):
        assert code == 0
        image = session(viewer).images[0]
        fine = level_for_3d(list(image.data))
        shape = tuple(image.data[fine].shape)
        render = viewer.window._qt_viewer.canvas._scene_canvas.render
        assert _wait(lambda: image.data_level == fine), "the fine level never came"
        render()
        assert uploads[-1] == shape
        del uploads[:]
        for ndisplay in (2, 3, 2, 3):
            viewer.dims.ndisplay = ndisplay
            pump()
            render()
        assert shape not in uploads, uploads

        viewer.dims.ndisplay = 2
        pump()
        lo, hi = image.contrast_limits
        image.contrast_limits = (lo, (lo + hi) / 2)
        viewer.dims.ndisplay = 3
        pump()
        render()
        node = layer_visual(viewer, image).node
        assert np.allclose(node.clim, image.contrast_limits)
        assert shape not in uploads, uploads


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


# -- the meshes, read while the space opens ---------------------------------


def _count_loads(monkeypatch, hold: dict | None = None):
    """Each mesh file read, in order: its stem, the thread reading it, and
    whether it has ended. `hold` maps a stem to what its read waits on."""
    import threading
    from pathlib import Path

    from lobemap.core.meshfmt import MeshSet

    real = MeshSet.load.__func__
    loads = []

    def load(cls, path, *args, **kwargs):
        read = {"stem": Path(path).stem, "thread": threading.current_thread().name,
                "ended": False}
        loads.append(read)
        (hold or {}).get(read["stem"], lambda: None)()
        try:
            return real(cls, path, *args, **kwargs)
        finally:
            read["ended"] = True

    monkeypatch.setattr(MeshSet, "load", classmethod(load))
    return loads


class _Gate:
    """Holds a read until it is opened, which another thread does a moment after
    `open_soon`, while the UI thread waits on that read."""

    def __init__(self) -> None:
        import threading

        self.started, self._open = threading.Event(), threading.Event()

    def __call__(self) -> None:
        self.started.set()
        assert self._open.wait(10), "the gate was never opened"

    def open_soon(self, seconds: float = 0.3) -> None:
        import threading

        threading.Timer(seconds, self._open.set).start()


def _reading() -> bool:
    import threading

    return any(t.name == "lobemap-meshes" for t in threading.enumerate())


@pytest.mark.parametrize("space", ["FAFB14", "JRCFIB2018F", "JRCFIB2022M"])
def test_every_deferred_mesh_is_read_once_by_the_thread_its_space_starts(monkeypatch,
                                                                         space):
    """And nothing reads one after: not a slider step, and not a tab.

    An atlas's mesh is read with the registry, for its compartment names.
    """
    loads = _count_loads(monkeypatch)
    with launched(monkeypatch, "view", space, "--ndisplay", "2") as (code, viewer):
        assert code == 0
        sess = session(viewer)
        shells = [sess.parts[n].asset.path.stem for n in sess.pending
                  if sess.parts[n].reference]
        assert shells
        assert _wait(lambda: not _reading())
        read = list(loads)
        assert sorted((r["stem"], r["thread"]) for r in read if r["stem"] in shells) == (
            sorted((stem, "lobemap-meshes") for stem in shells)), read
        axis = int(viewer.dims.order[0])
        for _ in range(10):
            viewer.dims.set_current_step(axis, viewer.dims.current_step[axis] + 1)
            pump(20)
        for name in list(sess.pending):
            tab = _open_tab(sess.panel, name)
            assert tab is sess.panel.tabs[name]
        assert loads == read, "a mesh was read after the thread"


def test_a_space_opens_without_its_deferred_meshes_and_a_tab_waits_for_one(monkeypatch):
    """The open waits for the corners of its parts, not for their meshes.

    A switch builds the rest of a scene fast enough that it used to wait for
    them. A tab opened while its mesh is read waits for that read, and reads
    none itself: not on the UI thread, and not beside the thread.
    """
    name = "fafb_neuropil"
    gate = _Gate()
    loads = _count_loads(monkeypatch, hold={name: gate})
    with launched(monkeypatch, "view", "FAFB14", "--ndisplay", "2") as (code, viewer):
        assert code == 0
        sess = session(viewer)
        assert gate.started.wait(10)
        assert [(r["stem"], r["ended"]) for r in loads if r["stem"] == name] == [
            (name, False)], "the open waited for the mesh"
        # Its corners were read: it holds its place.
        stand_in = viewer.layers[STANDIN_NAME.format(name=name)]

        gate.open_soon()
        tab = _open_tab(sess.panel, name)
        assert tab is sess.panel.tabs[name]
        assert tab.surface.layer is stand_in
        assert [(r["stem"], r["thread"]) for r in loads if r["stem"] == name] == [
            (name, "lobemap-meshes")]
        _buttons(tab)["Show all"].click()
        pump(300)
        assert drawn(tab.surface, sess.contours[name]), "no outline on the plane"
        assert_rows_match_drawing(sess)


@pytest.mark.parametrize("reading", ["corners", "mesh"])
def test_a_switch_that_fails_while_the_thread_reads_leaves_nothing(monkeypatch, reading):
    """Its thread reads no further file, and has ended once the switch is undone.

    It fails before the stand-ins, while the corners are read, or after them,
    while the meshes are. The scene the user had is untouched, and nothing
    of the failed one is left: no layer, no stand-in, no thread.
    """
    from lobemap.viewer import deferred, panel, scene

    space, shell = "JRCFIB2018F", "neuprint_hemibrain_neuropil"
    gate = _Gate()

    def fail(message):
        assert gate.started.wait(10)
        gate.open_soon()
        raise RuntimeError(message)

    if reading == "corners":
        real_bounds, real_images = deferred.mesh_bounds, scene.add_images

        def mesh_bounds(registry, part):
            if part.name == shell:
                gate()
            return real_bounds(registry, part)

        def add_images(viewer, registry, name):
            if name == space:
                fail("the images broke")
            return real_images(viewer, registry, name)

        monkeypatch.setattr(deferred, "mesh_bounds", mesh_bounds)
        monkeypatch.setattr(scene, "add_images", add_images)
        loads = _count_loads(monkeypatch)
        want = "the images broke"
    else:
        real_init = panel.CompartmentPanel.__init__

        def init(self, *args, **kwargs):
            real_init(self, *args, **kwargs)
            if kwargs.get("space") == space:
                fail("the panel broke")

        monkeypatch.setattr(panel.CompartmentPanel, "__init__", init)
        loads = _count_loads(monkeypatch, hold={shell: gate})
        want = "the panel broke"
    with launched(monkeypatch, "view", "FAFB14", "--ndisplay", "2") as (code, viewer):
        assert code == 0
        kept = session(viewer)
        before = layer_names(viewer)
        assert _wait(lambda: not _reading())
        switch_to(viewer, space)
        assert want in switcher(viewer).status.text()
        assert not _reading(), "the failed scene's thread outlived it"
        assert session(viewer) is kept
        assert layer_names(viewer) == before
        reads = [(r["thread"], r["ended"]) for r in loads if r["stem"] == shell]
        if reading == "corners":
            assert reads == [], "the torn-down scene's mesh was read"
        else:
            assert reads == [("lobemap-meshes", True)]
        pump(300)
        assert layer_names(viewer) == before
        assert_rows_match_drawing(kept)


def test_building_a_deferred_part_holds_the_contour_prefetch(monkeypatch):
    """The prefetch, cutting the primary atlas's planes from the open, cuts none
    while a tab builds its part, and finishes afterwards."""
    from lobemap.viewer import prefetch, scene

    real = scene.make_surface
    progress, plans = [], []

    def slow(*args, **kwargs):
        if plans:                           # the tab's build, not the open's
            before = plans[0].planes
            time.sleep(0.3)                 # ten of the worker's pauses, GIL free
            progress.append((plans[0].planes - before, plans[0].finished))
        return real(*args, **kwargs)

    monkeypatch.setattr(scene, "make_surface", slow)
    with launched(monkeypatch, "view", "JRCFIB2018F", "--ndisplay", "2") as (code, viewer):
        assert code == 0
        sess = session(viewer)
        plans.append(sess.contours[sess.registry.primary_atlas("JRCFIB2018F").id]._plan)
        assert prefetch.busy(), "the prefetch is over before the test begins"
        _open_tab(sess.panel, "neuprint_hemibrain_neuropil")
        assert progress == [(0, None)]
        assert prefetch.settle(60)
        assert plans[0].planes and not plans[0].skipped
