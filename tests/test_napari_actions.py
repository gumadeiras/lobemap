"""napari's actions in lobemap: roll steps the Sections menu, and grid, rotate
layers, transpose and the scene axes say why they are off, by whatever key
they are bound to.

Keys go through Qt to the canvas, as a key pressed there does; actions bound
to other keys are rebound through napari's action manager, as napari's
Preferences does, and put back after. What is checked is the viewer: the
slice axis and its plane, every layer's place, grid mode and the overlays.
"""

from __future__ import annotations

import contextlib

import numpy as np
import pytest
from chrome_harness import assert_no_hidden_mirror, baseline, press, told
from viewer_harness import (
    SPACES,
    assert_rows_match_drawing,
    launched,
    pump,
    session,
    switcher,
)

pytestmark = pytest.mark.requires_data
pytest.importorskip("napari")


@contextlib.contextmanager
def rebound(name: str, *keys):
    """napari's action `name` on ⌘ (Ctrl off macOS) and `keys` alone while
    inside, as Preferences binds it; its own keys again after. No setting is
    written. `keys` are app-model's: `KeyCode.KeyK`, `KeyMod.Alt`."""
    from app_model.types import KeyBinding, KeyMod
    from napari.utils.action_manager import action_manager

    combo = KeyMod.CtrlCmd
    for key in keys:
        combo |= key
    old = action_manager.unbind_shortcut(name) or []
    action_manager.bind_shortcut(name, KeyBinding.from_int(combo))
    try:
        yield
    finally:
        action_manager.unbind_shortcut(name)
        for shortcut in old:
            action_manager.bind_shortcut(name, shortcut)


def _plane(viewer) -> tuple:
    return int(viewer.dims.order[0]), float(viewer.dims.point[int(viewer.dims.order[0])])


@pytest.mark.parametrize("space", SPACES)
def test_roll_steps_through_the_sections_menu_in_order_and_wraps(monkeypatch, space):
    """Hemibrain and GRABE went Horizontal, Sagittal, Frontal, Sagittal; FAFB14
    and the male CNS only Sagittal and Horizontal. Now each press is the
    menu's next choice, by the button, its key and a key it is rebound to."""
    with launched(monkeypatch, "view", space) as (code, viewer):
        sw, sess = switcher(viewer), session(viewer)
        signs = baseline(viewer, sess, sw)
        sw.slice_view.click()
        pump()
        roll = viewer.window._qt_viewer.viewerButtons.rollDimsButton
        canvas = viewer.window._qt_viewer.canvas.native
        count = sw.slice.count()
        assert count == 3
        from app_model.types import KeyCode

        for route in (roll.click, lambda: press(canvas, "E", "Control"), "rebound"):
            with rebound("napari:roll_axes", KeyCode.KeyK) if route == "rebound" else (
                    contextlib.nullcontext()):
                do = (lambda: press(canvas, "K", "Control")) if route == "rebound" else route
                start = sw.slice.currentIndex()
                for step in range(1, count + 1):
                    do()
                    pump(100)
                    index = sw.slice.currentIndex()
                    assert index == (start + step) % count, (route, step, index)
                    axis = int(sw.slice.itemData(index))
                    assert sess.slice_axis == axis == _plane(viewer)[0]
                    assert_rows_match_drawing(sess)
                    assert_no_hidden_mirror(viewer, sess, sw, signs)
                assert sw.slice.currentIndex() == start
        # In 3D, as Sections is, it is off.
        sw.three_d.click()
        pump()
        index = sw.slice.currentIndex()
        press(canvas, "E", "Control")
        assert sw.slice.currentIndex() == index and tuple(viewer.dims.order) == (0, 1, 2)


def _placed(viewer) -> dict:
    return {layer.name: np.asarray(layer.affine.affine_matrix).copy() for layer in viewer.layers}


def test_grid_rotate_and_transpose_are_off_on_any_key(monkeypatch):
    """Rebound in Preferences, grid on ⌘J turned grid mode on, and rotate
    layers on ⌘⌥U turned every layer of lobemap's 90 degrees."""
    from app_model.types import KeyCode, KeyMod

    from lobemap.viewer.buttons import GRID_OFF, ROTATE_OFF, TRANSPOSE_OFF

    with launched(monkeypatch, "view", "GRABE") as (code, viewer):
        sw, sess = switcher(viewer), session(viewer)
        signs = baseline(viewer, sess, sw)
        sw.slice_view.click()
        pump()
        canvas = viewer.window._qt_viewer.canvas.native
        for name, keys, pressed, why in (
                ("napari:toggle_grid", (KeyCode.KeyJ,), ("J", "Control"), GRID_OFF),
                ("napari:rotate_layers", (KeyMod.Alt, KeyCode.KeyU), ("U", "Control", "Alt"),
                 ROTATE_OFF),
                ("napari:transpose_axes", (KeyCode.KeyH,), ("H", "Control"), TRANSPOSE_OFF)):
            order, placed = tuple(viewer.dims.order), _placed(viewer)
            with rebound(name, *keys), told() as said:
                press(canvas, *pressed)
                pump()
            assert said == [why], (name, said)
            assert tuple(viewer.dims.order) == order, name
            assert not viewer.canvas.grid.enabled, name
            for layer, matrix in _placed(viewer).items():
                assert np.array_equal(matrix, placed[layer]), (name, layer)
            assert_no_hidden_mirror(viewer, sess, sw, signs)


def test_napari_scene_axes_stay_off_and_say_why(monkeypatch):
    """View > Scene Axes drew napari's axes at the image's origin, the x
    arrow 180 degrees off under the mirror and both 30 degrees off at a spin
    of 30: they are kept off, and the corner arrows stay."""
    from napari._app_model import get_app_model

    from lobemap.viewer.axes import SCENE_AXES_OFF

    with launched(monkeypatch, "view", "GRABE") as (code, viewer):
        sw = switcher(viewer)
        sw.mirror.setChecked(True)
        sw.rotation.box["spin"].setValue(30.0)
        pump()
        model = viewer.scene.overlays["axes"]
        for ndisplay in (3, 2):
            viewer.dims.ndisplay = ndisplay
            pump()
            with told() as said:
                get_app_model().commands.execute_command("napari.scene.toggle_axes").result()
                pump()
            assert not model.visible and said == [SCENE_AXES_OFF], said
            assert viewer.canvas.overlays["axes"].visible
