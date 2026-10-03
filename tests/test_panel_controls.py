"""The panel's bulk buttons, and what they are called.

The label buttons read "Labels" and "No labels", which named the thing rather
than the action and sat confusingly beside the mesh-visibility buttons. They
are verbs now. The wiring is tested alongside the text so a future rename
cannot quietly point a button at the wrong handler.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.requires_data


def _panel(registry, space="GRABE"):
    import napari

    from lobemap.viewer.app import build_scene
    from lobemap.viewer.panel import CompartmentPanel

    viewer = napari.Viewer(show=False)
    surfaces, contours = build_scene(viewer, registry, space)
    panel = CompartmentPanel(viewer, surfaces, registry=registry,
                             contours=contours)
    return viewer, panel


def _tab(panel, name="grabe2015"):
    """One atlas's tab. The buttons live per-tab, not on the panel."""
    return panel.tabs[name]


def _buttons(widget):
    from qtpy.QtWidgets import QPushButton

    return {b.text(): b for b in widget.findChildren(QPushButton)}


def test_the_label_buttons_are_named_as_actions(registry):
    pytest.importorskip("napari")
    viewer, panel = _panel(registry)
    try:
        names = set(_buttons(_tab(panel)))
        assert "Names" in names, names
        assert "No names" in names, names
        assert "Labels" not in names
        assert "No labels" not in names
    finally:
        viewer.close()


def test_label_all_then_none_round_trips(registry):
    """The renamed buttons must still be wired to the label handlers."""
    pytest.importorskip("napari")
    viewer, panel = _panel(registry)
    try:
        tab = _tab(panel)
        buttons = _buttons(tab)
        overlay = tab.contour
        assert overlay is not None, "the tab has no contour overlay bound"

        buttons["Names"].click()
        assert overlay.labels, "Label all labeled nothing"
        labeled = set(overlay.labels)

        buttons["No names"].click()
        assert not overlay.labels, "Label none left labels behind"

        buttons["Names"].click()
        assert set(overlay.labels) == labeled, "not reproducible"
    finally:
        viewer.close()


def test_the_switcher_only_offers_spaces_that_can_load(registry):
    """Offering a space with no ingested data would be a dead end."""
    pytest.importorskip("qtpy")
    from lobemap.viewer.switcher import SpaceSwitcher

    spaces = SpaceSwitcher.loadable_spaces(registry)
    assert "GRABE" in spaces
    assert "FAFB14" in spaces
    for space_id in spaces:
        assert space_id in registry.spaces
