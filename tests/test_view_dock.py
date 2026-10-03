"""The View dock and napari's own window, as lobemap lays them out.

The outline layers are checked by napari's own layer state, not by any
widget's text.
"""

from __future__ import annotations

import pytest
from viewer_harness import launched, pump, session

pytestmark = pytest.mark.requires_data
pytest.importorskip("napari")


def test_the_main_layer_is_active_and_outlines_cannot_be_drawn_in(monkeypatch):
    """By napari's layer state: what is active, what is editable, what mode."""
    with launched(monkeypatch, "view", "JRCFIB2018F", "--ndisplay", "2") as (code, viewer):
        assert code == 0
        sess = session(viewer)
        main = sess.surfaces[sess.registry.primary_atlas(sess.space).id].layer
        assert viewer.layers.selection.active is main
        assert set(viewer.layers.selection) == {main}

        # An outline built later, its tab opened, is locked too.
        sess.panel.tab("neuprint_hemibrain_neuropil")
        pump()
        outlines = [layer for layer in viewer.layers
                    if layer.metadata.get("lobemap", {}).get("kind") == "contours"]
        assert len(outlines) == 2, [layer.name for layer in outlines]

        def assert_locked() -> None:
            for layer in outlines:
                assert layer.editable is False, layer.name
                assert layer.help == "", layer.name
                layer.mode = "add_rectangle"
                assert layer.mode == "pan_zoom", layer.name

        assert_locked()
        # napari makes a Shapes layer editable again on entering 2D.
        for ndisplay in (3, 2):
            viewer.dims.ndisplay = ndisplay
            pump()
            assert_locked()
        viewer.layers.selection.active = outlines[0]
        pump()
        assert viewer.help == ""

        # A Shapes layer of the user's own can still be drawn in.
        mine = viewer.add_shapes(ndim=3)
        pump()
        mine.mode = "add_rectangle"
        assert mine.editable and mine.mode == "add_rectangle"
