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
    assert_rows_match_drawing,
    checked,
    drawn,
    hover,
    launched,
    layer_names,
    pump,
    session,
    switch_to,
)

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
        # Two layers more, and nothing of them drawn: it opens unchecked.
        assert len(layer_names(viewer)) == len(before) + 2
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
