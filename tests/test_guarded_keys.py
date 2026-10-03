"""Delete passes lobemap's layers by, which napari's lock keeps.

Every key goes through Qt to the canvas, or to the layer list, as a key
pressed there does. What is checked is which layers exist.
"""

from __future__ import annotations

import pytest
from chrome_harness import press, told
from viewer_harness import launched, pump, session

pytestmark = pytest.mark.requires_data
pytest.importorskip("napari")

SPACE = "GRABE"


@pytest.fixture
def opened(monkeypatch):
    with launched(monkeypatch, "view", SPACE) as (code, viewer):
        assert code == 0
        yield viewer


def test_delete_passes_lobemaps_layers_by_and_takes_the_users(opened):
    """The button, ⌘⌫ and ⌘⌦ on the canvas, and ⌫ and ⌦ in the layer list."""
    viewer = opened
    qt_viewer = viewer.window._qt_viewer
    canvas, listing = qt_viewer.canvas.native, qt_viewer.layers
    delete = qt_viewer.layerButtons.deleteButton
    sess = session(viewer)
    main = sess.surfaces[sess.registry.primary_atlas(SPACE).id].layer
    ours = list(viewer.layers)
    assert viewer.layers.selection.active is main
    assert all(layer.locked for layer in ours)

    routes = {
        "button": delete.click,
        "⌘⌫": lambda: press(canvas, "Backspace", "Control"),
        "⌘⌦": lambda: press(canvas, "Delete", "Control"),
        "⌫ in the list": lambda: press(listing, "Backspace"),
        "⌦ in the list": lambda: press(listing, "Delete"),
    }
    for route, do in routes.items():
        # lobemap's own, alone: kept, and said why.
        for layer in (main, ours[0]):
            viewer.layers.selection.active = layer
            with told() as said:
                do()
                pump()
            assert list(viewer.layers) == ours, route
            assert any("locked" in s and layer.name in s for s in said), (route, said)
        # The user's own: deleted.
        mine = viewer.add_points(ndim=3)
        viewer.layers.selection.active = mine
        do()
        pump()
        assert mine not in viewer.layers and list(viewer.layers) == ours, route
        # Both: only the user's.
        mine = viewer.add_points(ndim=3)
        viewer.layers.selection.clear()
        viewer.layers.selection.update({mine, main})
        with told() as said:
            do()
            pump()
        assert mine not in viewer.layers and list(viewer.layers) == ours, route
        assert any("locked" in s for s in said), (route, said)
    # Hover still names what the main layer draws: nothing went away.
    assert set(sess.surfaces) and all(s.layer in viewer.layers for s in sess.surfaces.values())


def test_a_layer_of_lobemaps_stays_locked(opened):
    """napari's Toggle lock, from the layer list's menu, cannot unlock one."""
    from napari._app_model import get_app_model

    from lobemap.viewer.chrome import STAYS_LOCKED

    viewer = opened
    sess = session(viewer)
    main = sess.surfaces[sess.registry.primary_atlas(SPACE).id].layer
    viewer.layers.selection.active = main
    with told() as said:
        get_app_model().commands.execute_command("napari.layer.toggle_lock").result()
        pump()
    assert main.locked and said == [STAYS_LOCKED], said
    mine = viewer.add_points(ndim=3)
    viewer.layers.selection.active = mine
    get_app_model().commands.execute_command("napari.layer.toggle_lock").result()
    pump()
    assert mine.locked
