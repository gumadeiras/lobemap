"""napari's keys that would leave the window in a state no control of
lobemap's shows do nothing, and say why; delete passes lobemap's layers by,
and says they are part of the brain and can be hidden instead.

Every key goes through Qt to the canvas, or to the layer list, as a key
pressed there does. What is checked is the viewer: the axis order, every
layer's place, grid mode, which layers exist, and the sign of the
specimen's map to the screen (`chrome_harness.assert_no_hidden_mirror`).
"""

from __future__ import annotations

import numpy as np
import pytest
from chrome_harness import assert_no_hidden_mirror, baseline, press, told
from viewer_harness import launched, pump, session, switcher

pytestmark = pytest.mark.requires_data
pytest.importorskip("napari")

SPACE = "GRABE"


@pytest.fixture
def opened(monkeypatch):
    with launched(monkeypatch, "view", SPACE) as (code, viewer):
        assert code == 0
        yield viewer


def _placed(viewer) -> dict:
    """Every layer's transform from its data to the world."""
    return {layer.name: np.asarray(layer.affine.affine_matrix).copy() for layer in viewer.layers}


def test_transpose_rotate_and_grid_keys_do_nothing_and_say_why(opened, monkeypatch):
    from qtpy.QtCore import QEvent, QPointF, Qt
    from qtpy.QtGui import QMouseEvent
    from qtpy.QtWidgets import QApplication

    from lobemap.viewer.buttons import GRID_OFF, ROTATE_OFF, TRANSPOSE_OFF

    viewer = opened
    sw, sess = switcher(viewer), session(viewer)
    signs = baseline(viewer, sess, sw)
    canvas = viewer.window._qt_viewer.canvas.native
    for ndisplay in (2, 3):
        viewer.dims.ndisplay = ndisplay
        pump()
        order, placed = tuple(viewer.dims.order), _placed(viewer)
        for keys, why in ((("T", "Control"), TRANSPOSE_OFF),
                          (("T", "Control", "Alt"), ROTATE_OFF),
                          (("G", "Control"), GRID_OFF)):
            with told() as said:
                press(canvas, *keys)
            assert said == [why], (keys, said)
            assert tuple(viewer.dims.order) == order, keys
            for name, matrix in _placed(viewer).items():
                assert np.array_equal(matrix, placed[name]), (keys, name)
            assert not viewer.canvas.grid.enabled
            assert_no_hidden_mirror(viewer, sess, sw, signs)
        # Option-click on transpose turned every layer 90°: no more.
        button = viewer.window._qt_viewer.viewerButtons.transposeDimsButton
        monkeypatch.setattr(QApplication, "keyboardModifiers",
                            staticmethod(lambda: Qt.KeyboardModifier.AltModifier))
        for kind in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease):
            QApplication.sendEvent(button, QMouseEvent(
                kind, QPointF(4, 4), QPointF(4, 4), Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton, Qt.KeyboardModifier.AltModifier))
        pump()
        monkeypatch.undo()
        for name, matrix in _placed(viewer).items():
            assert np.array_equal(matrix, placed[name]), name
        assert tuple(viewer.dims.order) == order
    # The model refuses a swap however it is asked for.
    viewer.dims.ndisplay = 2
    pump()
    order = tuple(viewer.dims.order)
    with told() as said:
        viewer.dims.transpose()
        pump()
    assert tuple(viewer.dims.order) == order
    assert any("keep their order" in s for s in said), said
    assert_no_hidden_mirror(viewer, sess, sw, signs)


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
    from lobemap.viewer.guards import KEPT

    for route, do in routes.items():
        # lobemap's own, alone: kept, and said why, in lobemap's words, not
        # napari's "locked and cannot be deleted".
        for layer in (main, ours[0]):
            viewer.layers.selection.active = layer
            with told() as said:
                do()
                pump()
            assert list(viewer.layers) == ours, route
            assert said == [KEPT.format(names=repr(layer.name))], (route, said)
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
        assert said == [KEPT.format(names=repr(main.name))], (route, said)
        assert set(viewer.layers.selection) == {main}, route
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
