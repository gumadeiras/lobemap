"""napari's two button rows and their popups, back, and in step with the View dock.

Each button is clicked, each popup opened with a right-click and driven, and
each pair of controls is changed from either side. What is checked is the
viewer and the picture: the display mode, the axis order, the camera, which
layers exist, and the sign of the specimen's map to the screen, which a
hidden mirror would turn over (`chrome_harness.assert_no_hidden_mirror`);
and that both corner triads point where they say.
"""

from __future__ import annotations

import numpy as np
import pytest
import turned_harness as th
from chrome_harness import (
    assert_no_hidden_mirror,
    baseline,
    close_popups,
    open_popups,
    popups_offscreen,
    right_click,
    told,
)
from viewer_harness import launched, pump, session, switcher

pytestmark = pytest.mark.requires_data
pytest.importorskip("napari")

SPACE = "JRCFIB2018F"


@pytest.fixture
def opened(monkeypatch):
    """The hemibrain as `lobemap view` opens it, laid out at 1440 x 900."""
    from qtpy.QtCore import Qt

    with popups_offscreen(), launched(monkeypatch, "view", SPACE) as (code, viewer):
        assert code == 0
        window = viewer.window._qt_window
        window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        window.resize(1440, 900)
        window.show()
        pump(300)
        try:
            yield viewer
        finally:
            close_popups(viewer)


def _rows(viewer):
    qt_viewer = viewer.window._qt_viewer
    return qt_viewer.viewerButtons, qt_viewer.layerButtons


def _triads_right(viewer) -> None:
    th.settle_canvas(viewer)
    th.assert_triads_point_where_they_say(viewer, session(viewer).registry.spaces[SPACE])


def test_both_rows_are_back_and_what_is_off_says_why(opened):
    """Every button shows, around the layer list; transpose and grid are off,
    do nothing when clicked and open no popup; roll is off in 3D only."""
    from qtpy.QtWidgets import QDockWidget

    viewer = opened
    row, layer_row = _rows(viewer)
    sw = switcher(viewer)
    window = viewer.window._qt_window
    layers = next(d for d in window.findChildren(QDockWidget) if d.windowTitle() == "Layers")
    canvas = viewer.window._qt_viewer.canvas.native
    canvas_left = canvas.mapTo(window, canvas.rect().topLeft()).x()
    names = {row: ("consoleButton", "ndisplayButton", "rollDimsButton",
                   "transposeDimsButton", "gridViewButton", "resetViewButton"),
             layer_row: ("newPointsButton", "newShapesButton", "newLabelsButton",
                         "deleteButton")}
    for frame, buttons in names.items():
        assert frame.isVisible() and layers.isAncestorOf(frame)
        for name in buttons:
            button = getattr(frame, name)
            corner = button.mapTo(window, button.rect().topLeft())
            assert button.isVisible() and corner.x() + button.width() < canvas_left, name
    assert layer_row.y() < viewer.window._qt_viewer.layers.y() < row.y()
    assert canvas.width() >= 560

    signs = baseline(viewer, session(viewer), sw)
    for ndisplay in (3, 2):
        viewer.dims.ndisplay = ndisplay
        pump()
        assert row.rollDimsButton.isEnabled() is (ndisplay == 2)
        if ndisplay == 3:
            assert row.rollDimsButton.toolTip().startswith("Slice view only")
        for button in (row.transposeDimsButton, row.gridViewButton):
            assert not button.isEnabled()
            assert button.toolTip().startswith("Off in lobemap:")
            assert button.graphicsEffect().isEnabled()      # drawn faded
            order = tuple(viewer.dims.order)
            button.click()
            pump()
            assert right_click(button) == []
            assert tuple(viewer.dims.order) == order
            assert not viewer.canvas.grid.enabled
        assert_no_hidden_mirror(viewer, session(viewer), sw, signs)
        _triads_right(viewer)
    for button in (row.consoleButton, row.ndisplayButton, row.resetViewButton,
                   layer_row.newPointsButton, layer_row.newShapesButton,
                   layer_row.deleteButton):
        assert button.isEnabled(), button.toolTip()
    # The console opens and closes, and the picture is as it was.
    for shown in (True, False):
        row.consoleButton.click()
        pump(200)
        assert viewer.window._qt_viewer.dockConsole.isVisible() is shown
        assert_no_hidden_mirror(viewer, session(viewer), sw, signs)


def test_the_2d_3d_button_and_home_are_the_view_docks(opened):
    """2D/3D and 3D/Slice follow each other; home and Fit to window give the
    same camera, the rotation and the flip kept, from either side."""
    viewer = opened
    row, _layers = _rows(viewer)
    sw, sess = switcher(viewer), session(viewer)
    camera = viewer.scene.camera
    signs = baseline(viewer, sess, sw)

    row.ndisplayButton.click()
    pump()
    assert viewer.dims.ndisplay == 2 and sw.slice_view.isChecked()
    assert not row.ndisplayButton.isChecked()
    sw.three_d.click()
    pump()
    assert viewer.dims.ndisplay == 3 and row.ndisplayButton.isChecked()

    sw.rotation.box["spin"].setValue(20.0)
    sw.rotation.box["tilt"].setValue(15.0)
    sw.flip.setChecked(True)
    pump()
    for ndisplay in (3, 2):
        viewer.dims.ndisplay = ndisplay
        pump()
        homes = []
        for press in (sw.home.click, row.resetViewButton.click, sw.home.click):
            camera.zoom = camera.zoom * 1.7
            camera.center = tuple(np.asarray(camera.center) + 9.0)
            if ndisplay == 3:
                camera.angles = (17.0, 42.0, -63.0)        # a drag
            press()
            pump()
            homes.append((*camera.center, camera.zoom, *camera.angles,
                          sw.camera.zoom.value()))
            assert sw.rotation.angles() == (20.0, 15.0, 0.0)
            assert sess.flipped and sw.flip.isChecked()
            assert_no_hidden_mirror(viewer, sess, sw, signs)
            _triads_right(viewer)
        for home in homes[1:]:
            assert home == pytest.approx(homes[0]), homes
        # Fit to window leaves the zoom box showing the fitted zoom.
        assert sw.camera.zoom.value() == pytest.approx(camera.zoom, abs=5e-4)


def test_roll_and_its_popup_are_the_sections_menu(opened):
    """Roll steps the Sections menu, its popup lists the axes in the menu's
    order, a drag to the top picks the sections, and a drag that swaps the
    two axes on screen is undone, with the reason said."""
    from qtpy.QtWidgets import QAbstractItemView, QWidget

    from lobemap.viewer.buttons import ROLL_POPUP_TIP
    from lobemap.viewer.slicing import order_for

    viewer = opened
    row, _layers = _rows(viewer)
    sw, sess = switcher(viewer), session(viewer)
    signs = baseline(viewer, sess, sw)
    viewer.dims.ndisplay = 2
    pump()
    seen = set()
    for _ in range(3):
        before = int(sw.slice.currentData())
        row.rollDimsButton.click()
        pump()
        axis = int(sw.slice.currentData())
        assert axis != before and axis == sess.slice_axis == int(viewer.dims.order[0])
        seen.add(axis)
        assert_no_hidden_mirror(viewer, sess, sw, signs)
        _triads_right(viewer)
    assert len(seen) >= 2

    def sorter():
        popups = right_click(row.rollDimsButton)
        assert len(popups) == 1
        found = popups[0].findChildren(QWidget, "dim_sorter")
        assert len(found) == 1
        for view in found[0].findChildren(QAbstractItemView):
            assert view.toolTip() == ROLL_POPUP_TIP
        assert found[0].findChild(QWidget, "help_label").toolTip() == ROLL_POPUP_TIP
        return popups[0], found[0]

    # The menu picks; the popup lists the axes as the menu has them.
    for i in range(sw.slice.count()):
        sw.slice.setCurrentIndex(i)
        pump()
        popup, found = sorter()
        listed = tuple(axis.axis for axis in found.axis_list)
        assert listed == tuple(viewer.dims.order) == order_for(int(sw.slice.currentData()))
        # A swap of the two axes on screen is undone, and said why.
        with told() as said:
            found.axis_list.move(1, 3)
            pump()
        assert tuple(viewer.dims.order) == listed
        assert any("keep their order" in s for s in said), said
        assert tuple(axis.axis for axis in found.axis_list) == listed
        assert_no_hidden_mirror(viewer, sess, sw, signs)
        popup.close()
        pump()
    # Locked axes stay in place when napari rolls: whichever are locked, a
    # roll picks sections the menu names, or nothing.
    from qtpy.QtCore import Qt

    for locked in ((0,), (1,), (2,), (0, 1)):
        popup, found = sorter()
        model = found.view.model()
        for i in range(model.rowCount()):
            state = Qt.CheckState.Unchecked if i in locked else Qt.CheckState.Checked
            model.setData(model.index(i, 0), state.value, Qt.ItemDataRole.CheckStateRole)
        popup.close()
        pump()
        row.rollDimsButton.click()
        pump()
        assert int(sw.slice.currentData()) == sess.slice_axis == int(viewer.dims.order[0])
        assert_no_hidden_mirror(viewer, sess, sw, signs)
        viewer.dims.rollable = (True,) * viewer.dims.ndim
    # A drag to the top picks the sections, and the menu follows.
    popup, found = sorter()
    last = found.axis_list[2].axis
    found.axis_list.move(2, 0)
    pump()
    assert int(sw.slice.currentData()) == last == int(viewer.dims.order[0])
    assert_no_hidden_mirror(viewer, sess, sw, signs)
    _triads_right(viewer)
    popup.close()


def test_the_camera_popup_is_the_view_docks_flip_zoom_and_perspective(opened):
    """Each pair from either side: the popup's up/down and the flip, its zoom
    and the zoom box, its perspective and the perspective box. Left/right
    and away are off. Its angles turn the camera as a drag does."""
    from napari.utils.camera_orientations import VerticalAxisOrientation

    from lobemap.viewer.buttons import DEPTH_OFF, HORIZONTAL_OFF
    from lobemap.viewer.napari_private import layer_visual

    viewer = opened
    row, _layers = _rows(viewer)
    sw, sess = switcher(viewer), session(viewer)
    camera = viewer.scene.camera
    signs = baseline(viewer, sess, sw)
    main = sess.surfaces[sess.registry.primary_atlas(SPACE).id]

    for ndisplay in (2, 3):
        viewer.dims.ndisplay = ndisplay
        pump()
        (popup,) = right_click(row.ndisplayButton)
        assert not row.horizontal_combo.isEnabled()
        assert row.horizontal_combo.toolTip() == HORIZONTAL_OFF
        if ndisplay == 3:
            assert not row.depth_combo.isEnabled()
            assert row.depth_combo.toolTip() == DEPTH_OFF
        # Up/down and the flip.
        row.vertical_combo.setCurrentEnum(VerticalAxisOrientation("up"))
        pump()
        assert sw.flip.isChecked() and sess.flipped
        assert_no_hidden_mirror(viewer, sess, sw, signs)
        _triads_right(viewer)
        if ndisplay == 3:
            # Lit from outside: the faces vispy takes for the front turn over too.
            assert layer_visual(viewer, main.layer).node._lobemap_face == "cw"
        sw.flip.setChecked(False)
        pump()
        assert str(row.vertical_combo.currentEnum()) == "down" and not sess.flipped
        assert_no_hidden_mirror(viewer, sess, sw, signs)
        # Zoom.
        row.zoom.setValue(2.5)
        pump()
        assert camera.zoom == pytest.approx(2.5) and sw.camera.zoom.value() == pytest.approx(2.5)
        sw.camera.zoom.setValue(1.25)
        pump()
        assert camera.zoom == pytest.approx(1.25) and row.zoom.value() == pytest.approx(1.25)
        # Its sync box is napari's, and moves nothing.
        for synced in (False, True):
            row.camera_synced_checkbox.setChecked(synced)
            pump()
            assert camera.synced is synced
            assert_no_hidden_mirror(viewer, sess, sw, signs)
        if ndisplay == 3:
            # Perspective.
            row.perspective.setValue(40)
            pump()
            assert camera.perspective == 40 and sw.camera.perspective.value() == 40
            sw.camera.perspective.setValue(25)
            pump()
            assert camera.perspective == 25 and row.perspective.value() == 25
            # The angles turn the camera as a drag does: the rotation boxes
            # keep theirs, and Fit to window faces them again.
            sw.rotation.box["turn"].setValue(30.0)
            pump()

            def facing():
                return np.r_[camera.view_direction, camera.up_direction]

            axes = facing()
            row.rz.setValue(55.0)
            row.rx.setValue(-20.0)
            pump()
            assert not np.allclose(facing(), axes, atol=1e-3)
            assert sw.rotation.angles() == (0.0, 0.0, 30.0)
            assert_no_hidden_mirror(viewer, sess, sw, signs)
            _triads_right(viewer)
            popup.close()
            pump()
            sw.home.click()
            pump()
            assert np.allclose(facing(), axes, atol=1e-6)
            sw.rotation.reset.click()
            sw.camera.perspective.setValue(0)
            pump()
        popup.close()
        pump()
        # Closed, it follows the camera no longer.
        assert not open_popups(row)

    # A mirroring orientation from anywhere -- napari's preferences, say --
    # is put back.
    for wrong in (("towards", "down", "left"), ("away", "down", "right")):
        camera.orientation = wrong
        pump()
        assert_no_hidden_mirror(viewer, sess, sw, signs)


def test_new_layers_are_the_users_and_move_nothing_of_lobemaps(opened):
    """New points, shapes and labels layers are added, unlocked and editable;
    lobemap's layers are drawn where they were; delete takes the new ones."""
    viewer = opened
    _row, layer_row = _rows(viewer)
    sw, sess = switcher(viewer), session(viewer)
    signs = baseline(viewer, sess, sw)
    ours = list(viewer.layers)
    contour = sess.contours[sess.registry.primary_atlas(SPACE).id]
    specimen = contour.meshset.centroid(0)

    def drawn_at():
        th.settle_canvas(viewer)
        world = np.asarray(contour.layer.data_to_world(specimen), float)
        return th.screen_axes(viewer) if viewer.dims.ndisplay == 3 else world

    for ndisplay in (3, 2):
        viewer.dims.ndisplay = ndisplay
        pump()
        before = drawn_at()
        added = []
        for button in (layer_row.newPointsButton, layer_row.newShapesButton):
            button.click()
            pump()
            added.append(viewer.layers.selection.active)
        viewer.layers.selection.active = added[0]
        layer_row.newLabelsButton.click()
        pump()
        added.append(viewer.layers.selection.active)
        assert [type(layer).__name__ for layer in added] == ["Points", "Shapes", "Labels"]
        for layer in added:
            assert layer not in ours and "lobemap" not in layer.metadata
            assert not layer.locked
            # napari edits shapes in 2D only.
            assert layer.editable or (ndisplay == 3 and type(layer).__name__ == "Shapes")
        assert np.allclose(drawn_at(), before)
        assert_no_hidden_mirror(viewer, sess, sw, signs)
        viewer.layers.selection.clear()
        viewer.layers.selection.update(added)
        layer_row.deleteButton.click()
        pump()
        assert list(viewer.layers) == ours
