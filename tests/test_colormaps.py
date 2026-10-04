"""Display defaults live with the role, not scattered through the viewer."""

from __future__ import annotations

import numpy as np
import pytest

from lobemap.viewer.app import default_colormap


def test_stain_and_template_default_to_gray():
    assert default_colormap("virtual_stain") == "gray"
    assert default_colormap("template_image") == "gray"
    assert default_colormap("anything_else") == "magma"


def test_role_defaults_are_real_napari_colormaps():
    from napari.utils.colormaps import AVAILABLE_COLORMAPS

    for role in ("virtual_stain", "template_image", "other"):
        assert default_colormap(role) in AVAILABLE_COLORMAPS


def _registry_with_two_stains(root):
    """One atlas, so the scene builds, and two stains: one names a colormap."""
    from lobemap.core.imagefmt import Volume
    from lobemap.core.meshfmt import MeshSet
    from lobemap.core.registry import Registry

    (root / "atlases").mkdir(parents=True)
    (root / "spaces.toml").write_text('[S1]\ntitle = "S"\nunits = "um"\n')
    (root / "atlases" / "a1.toml").write_text(
        'id = "a1"\nnative_space = "S1"\nasset = "a1_mesh"\n')
    (root / "assets.toml").write_text(
        '[a1_mesh]\nrole = "glomeruli"\nspace = "S1"\nkind = "meshset"\n'
        'path = "data/a1.npz"\n\n'
        '[plain]\nrole = "virtual_stain"\nspace = "S1"\nkind = "image"\n'
        'path = "data/plain.npz"\n\n'
        '[tinted]\nrole = "virtual_stain"\nspace = "S1"\nkind = "image"\n'
        'path = "data/tinted.npz"\ncolormap = "cyan"\n')
    v = np.array([[0, 0, 0], [4, 0, 0], [0, 4, 0], [0, 0, 4]], np.float64)
    f = np.array([[0, 1, 2], [0, 1, 3], [0, 2, 3], [1, 2, 3]])
    MeshSet.from_parts([("DA1(R)", v, f)], meta={"units": "um"}).save(
        root / "data" / "a1.npz")
    for name in ("plain", "tinted"):
        Volume(np.zeros((4, 4, 4), np.uint8), voxel_um=(1.0, 1.0, 1.0)).save(
            root / "data" / f"{name}.npz")
    return Registry.load(root, data_root=root / "data")


def test_an_asset_colormap_reaches_its_layer(tmp_path):
    """From `assets.toml` to the layer napari draws, through the scene.

    This used to evaluate `asset.colormap or default_colormap(asset.role)`
    in the test itself, which held whatever the viewer did with the field.
    """
    napari = pytest.importorskip("napari")
    from lobemap.viewer.app import build_scene

    registry = _registry_with_two_stains(tmp_path / "registry")
    viewer = napari.Viewer(show=False)
    try:
        build_scene(viewer, registry, "S1")
        assert viewer.layers["tinted"].colormap.name == "cyan"
        assert viewer.layers["plain"].colormap.name == "gray"
    finally:
        viewer.close()


# -- a surface's own colormap entry --------------------------------------------


def _menu(viewer, layer):
    """The colormap menu napari's layer settings show for `layer`."""
    from qtpy.QtWidgets import QComboBox

    controls = viewer.window._qt_viewer.controls.widgets[layer]
    found = [c for c in controls.findChildren(QComboBox)
             if c.objectName() == "colormapComboBox"]
    assert len(found) == 1, found
    return found[0]


def _menu_items(viewer, layer) -> list[str]:
    menu = _menu(viewer, layer)
    return [menu.itemData(i) for i in range(menu.count())]


def _want(surface) -> np.ndarray:
    """The colors a surface paints: its own, transparent where unchecked, in
    the float32 napari keeps colors in."""
    want = np.array(surface.colors, float)
    want[:, 3] = [1.0 if i in surface.selection else 0.0 for i in range(len(want))]
    return want.astype(np.float32)


def test_toggling_rows_adds_no_colormap_and_each_layer_keeps_its_own():
    """Two surfaces of the same colors, rows toggled a hundred times: napari's
    colormap list and the layer settings menu stay as they were, each layer
    paints its own selection, and a surface built after one is torn down
    takes its entry back rather than adding one."""
    napari = pytest.importorskip("napari")
    import turned_harness as th
    from napari.utils.colormaps import AVAILABLE_COLORMAPS
    from viewer_harness import drawn, pump

    from lobemap.viewer.layers import AtlasSurface

    viewer = napari.Viewer(show=False, ndisplay=3)
    try:
        mesh = th.meshset()
        colors = np.array([[1.0, 0.0, 0.0, 1.0], [0.0, 1.0, 0.0, 1.0],
                           [0.0, 0.0, 1.0, 1.0]])
        surfaces = [AtlasSurface(viewer, mesh, name, colors=colors.copy(),
                                 compact_delay_ms=0) for name in ("one", "two")]
        one, two = surfaces
        assert one.layer.colormap is not two.layer.colormap
        pump()
        names = list(AVAILABLE_COLORMAPS)
        menu = _menu_items(viewer, one.layer)
        rng = np.random.default_rng(7)
        for _ in range(100):
            for surface in surfaces:
                picked = {i for i in range(3) if rng.random() < 0.5} or {0}
                surface.set_selection(picked)
            for surface in surfaces:
                assert np.array_equal(surface.layer.colormap.colors, _want(surface))
                assert drawn(surface) == surface.selection
        pump()
        assert list(AVAILABLE_COLORMAPS) == names
        assert _menu_items(viewer, one.layer) == menu

        # Torn down, its entry is free for the next surface, which paints its
        # own colors in it.
        name = one.layer.colormap.name
        one.stop()
        viewer.layers.remove(one.layer)
        three = AtlasSurface(viewer, mesh, "three", colors=colors[::-1].copy(),
                             compact_delay_ms=0)
        assert three.layer.colormap.name == name
        assert np.array_equal(three.layer.colormap.colors, _want(three))
        assert np.array_equal(two.layer.colormap.colors, _want(two))
        assert list(AVAILABLE_COLORMAPS) == names
    finally:
        viewer.close()


@pytest.mark.requires_data
def test_rows_toggled_in_every_brain_add_no_colormap(monkeypatch):
    """Through the tables, in every brain and back: after the first round,
    neither napari's colormap list nor the layer settings menu grows, and
    every surface paints its own checked rows."""
    from napari.utils.colormaps import AVAILABLE_COLORMAPS
    from viewer_harness import SPACES, launched, pump, session, switch_to

    def toggle_everything() -> None:
        sess = session(viewer)
        for name in list(sess.parts):
            tab = sess.panel.tab(name)
            if tab is None:
                continue
            n = tab.surface.meshset.n_compartments
            for k in range(6):
                tab.select(range(k % 3, n, 3))
            tab.select(range(n))
        pump(300)
        layers = {}
        for surface in sess.surfaces.values():
            assert np.array_equal(surface.layer.colormap.colors, _want(surface)), (
                surface.name)
            layers.setdefault(id(surface.layer.colormap), []).append(surface.name)
        assert all(len(held) == 1 for held in layers.values()), layers

    with launched(monkeypatch, "view", SPACES[0]) as (code, viewer):
        assert code == 0
        for space in (*SPACES[1:], SPACES[0]):
            toggle_everything()
            switch_to(viewer, space)
        toggle_everything()
        names = list(AVAILABLE_COLORMAPS)
        primary = session(viewer).surfaces[
            session(viewer).registry.primary_atlas(SPACES[0]).id].layer
        menu = _menu_items(viewer, primary)
        for space in (*SPACES[1:], SPACES[0]):
            switch_to(viewer, space)
            toggle_everything()
        assert list(AVAILABLE_COLORMAPS) == names
        primary = session(viewer).surfaces[
            session(viewer).registry.primary_atlas(SPACES[0]).id].layer
        assert _menu_items(viewer, primary) == menu


@pytest.mark.requires_data
def test_each_colormap_is_named_after_its_atlas_in_every_brain(monkeypatch):
    """Through every brain and back, every part built: each surface's entry
    in the layer settings menu is named after its atlas, or its brain's
    neuropils, never numbered, one name per atlas, and no wider than leaves
    the canvas 560 px of a 1440 px window."""
    import gc
    import re

    from napari.utils.colormaps import AVAILABLE_COLORMAPS
    from qtpy.QtCore import Qt
    from viewer_harness import SPACES, launched, pump, session, switch_to

    # A window closed by an earlier test of this process can still hold its
    # entries until its surfaces are collected: two windows at once number
    # theirs. lobemap opens one.
    gc.collect()
    with launched(monkeypatch, "view", SPACES[0]) as (code, viewer):
        assert code == 0
        window = viewer.window._qt_window
        window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        window.resize(1440, 900)
        window.show()
        pump(300)
        seen: dict[str, str] = {}
        for space in (*SPACES, SPACES[0]):
            if space != SPACES[0] or seen:
                switch_to(viewer, space)
                pump(300)
            sess = session(viewer)
            brain = sess.registry.spaces[space].title.split(" (")[0]
            for name in list(sess.parts):
                assert sess.panel.tab(name) is not None, name
            pump(300)
            for name, surface in sess.surfaces.items():
                menu = _menu(viewer, surface.layer)
                shown = menu.currentText()
                assert shown == surface.layer.colormap.name, (space, name, shown)
                assert not re.search(r"\(\d+\)$", shown), (space, name, shown)
                if surface.layer.metadata["lobemap"]["role"] == "neuropil":
                    assert shown == f"{brain} neuropil colors", (space, shown)
                else:
                    title = sess.panel.source_title(name)
                    assert shown in (f"{title} colors", f"{brain} {title} colors"), shown
                assert seen.setdefault(shown, name) == name, (shown, seen[shown], name)
            canvas = viewer.window._qt_viewer.canvas.native
            assert canvas.width() >= 560, (space, canvas.width())
        # Back in the first brain, its surfaces took back their entries.
        assert all(name in AVAILABLE_COLORMAPS for name in seen)
