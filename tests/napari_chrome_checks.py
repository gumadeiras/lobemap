"""What lobemap reaches of napari's own window: its docks, its buttons, their
popups and its keys. Split out of `test_napari_private`, which imports these
tests, so that `CHECKED` there names them, and which runs them with its
`viewer` and `opened` fixtures and its `need` and `reaching`.
"""

from __future__ import annotations


def _helpers():
    from test_napari_private import need, reaching

    return need, reaching


def test_the_window_and_canvas_lobemap_reaches(opened):
    from qtpy.QtWidgets import QMainWindow

    need, reaching = _helpers()
    used = "viewer.chrome docking and viewer.view.maximize"
    with reaching("napari Window._qt_window", used):
        window = opened.viewer.window._qt_window
    need(isinstance(window, QMainWindow)
         and all(callable(getattr(window, name, None))
                 for name in ("addDockWidget", "splitDockWidget", "tabifyDockWidget",
                              "setTabPosition", "resizeDocks", "showNormal",
                              "showMaximized")),
         "Window._qt_window, a QMainWindow", used)
    used = "viewer.view.install_initial_fit"
    with reaching("viewer.window._qt_viewer.canvas.events", used):
        events = opened.viewer.window._qt_viewer.canvas.events
    need(all(hasattr(events, name) for name in
             ("resize", "draw", "mouse_press", "mouse_wheel", "key_press")),
         "QtViewer.canvas.events resize, draw, mouse_press, mouse_wheel and key_press", used)


def test_the_napari_chrome_lobemap_tidies(viewer):
    """What `viewer.chrome` reaches in napari's window: its dock class, which
    takes `close_btn` and keeps it when the dock floats; its two button rows,
    which `buttons` keeps; and its two layer docks, which `tidy` renames."""
    from qtpy.QtCore import Qt
    from qtpy.QtWidgets import QDockWidget, QLabel, QMenu, QWidget

    from lobemap.viewer import chrome

    need, reaching = _helpers()
    used = "viewer.chrome.add_dock"
    where = "napari._qt.widgets.qt_viewer_dock_widget.QtViewerDockWidget(close_btn=False)"
    with reaching(where, used):
        dock = chrome.add_dock(viewer, QWidget(), "Lobemap dock", "left")
    need(isinstance(dock, QDockWidget) and not hasattr(dock.title, "close_button"),
         where, used)
    need(isinstance(viewer.window.window_menu, QMenu)
         and dock.toggleViewAction() in viewer.window.window_menu.actions(),
         "Window.window_menu, a QMenu", used)
    with reaching("QtViewerDockWidget rebuilding its title bar as it floats", used):
        dock.setFloating(True)
        dock.setFloating(False)
        title = dock.title
    need(not hasattr(title, "close_button") and title.title.text() == "Lobemap dock",
         "QtViewerDockWidget._update_title_bar, from its name and close_btn", used)

    used = "viewer.buttons.install"
    qt_viewer = viewer.window._qt_viewer
    buttons = {
        "viewerButtons": ("consoleButton", "ndisplayButton", "rollDimsButton",
                          "transposeDimsButton", "gridViewButton", "resetViewButton"),
        "layerButtons": ("newPointsButton", "newShapesButton", "newLabelsButton",
                         "deleteButton"),
    }
    for row, names in buttons.items():
        with reaching(f"QtViewer.{row}", used):
            frame = getattr(qt_viewer, row)
        # Every button of the rows is one `buttons` knows of.
        held = frame.findChildren(QWidget, options=Qt.FindChildOption.FindDirectChildrenOnly)
        need({id(widget) for widget in held}
             == {id(getattr(frame, name, None)) for name in names},
             f"QtViewer.{row} holding {', '.join(names)} and no other widget", used)
    used = "viewer.chrome.tidy"
    for name in ("dockLayerControls", "dockLayerList"):
        with reaching(f"QtViewer.{name}.name and .title.title", used):
            layer_dock = getattr(qt_viewer, name)
            label = layer_dock.title.title
        need(isinstance(layer_dock, QDockWidget) and isinstance(label, QLabel)
             and isinstance(layer_dock.name, str),
             f"QtViewer.{name}, a dock with a name and a title label", used)


def test_the_buttons_popups_and_keys_lobemap_keeps_in_step(viewer):
    """What `viewer.buttons` reaches: the popups each right-click opens, the
    widgets napari keeps of the camera popup, the axis-order popup's list and
    help, transpose's Option-click filter, the keys of the actions it turns
    off, and napari's lock against deletion."""
    from chrome_harness import popups_offscreen, right_click
    from napari.settings import get_settings
    from napari.utils.camera_orientations import VerticalAxisOrientation
    from qtpy.QtCore import QEvent, Qt
    from qtpy.QtWidgets import QAbstractItemView, QPushButton, QWidget
    from viewer_harness import pump

    need, reaching = _helpers()
    used = "viewer.buttons.install"
    row = viewer.window._qt_viewer.viewerButtons
    for name in ("ndisplayButton", "rollDimsButton"):
        button = getattr(row, name)
        need(isinstance(button, QPushButton)
             and button.contextMenuPolicy() == Qt.ContextMenuPolicy.CustomContextMenu,
             f"QtViewerButtons.{name}, opening a popup on a right-click", used)

    # Transpose rotates every layer from its row's event filter, on an
    # Option-click; `install` removes that filter.
    transpose = row.transposeDimsButton
    with reaching("QtViewerButtons.eventFilter on transposeDimsButton", used):
        filtered = []
        real = type(row).eventFilter

        def spy(self, obj, event):
            if obj is transpose and event.type() == QEvent.Type.MouseButtonPress:
                filtered.append(obj)
            return real(self, obj, event)

        type(row).eventFilter = spy
        try:
            from qtpy.QtTest import QTest

            QTest.mousePress(transpose, Qt.MouseButton.LeftButton)
            QTest.mouseRelease(transpose, Qt.MouseButton.LeftButton)
        finally:
            type(row).eventFilter = real
    need(filtered == [transpose],
         "QtViewerButtons filtering transposeDimsButton's presses for Option-click", used)

    with popups_offscreen():
        for ndisplay in (2, 3):
            viewer.dims.ndisplay = ndisplay
            pump()
            with reaching(f"the {ndisplay}D camera popup's widgets", used):
                popups = right_click(row.ndisplayButton)
                combos = [row.vertical_combo, row.horizontal_combo]
                combos += [row.depth_combo] if ndisplay == 3 else []
                sliders = [row.zoom] + ([row.perspective] if ndisplay == 3 else [])
                row.vertical_combo.setCurrentEnum(VerticalAxisOrientation("down"))
            need(len(popups) == 1
                 and all(c.window() is popups[0] for c in combos + sliders)
                 and all(callable(getattr(s, "setValue", None)) for s in sliders)
                 and hasattr(popups[0], "finished"),
                 "QtViewerButtons.open_ndisplay_camera_popup keeping its vertical_combo, "
                 "horizontal_combo, depth_combo, zoom and perspective", used)
            popups[0].close()
        viewer.dims.ndisplay = 2
        pump()
        with reaching("the axis-order popup, its dim_sorter and help_label", used):
            popups = right_click(row.rollDimsButton)
            sorter = popups[0].findChild(QWidget, "dim_sorter")
            sorter.axis_list.move(0, 0)
        need(sorter.findChild(QWidget, "help_label") is not None
             and sorter.findChildren(QAbstractItemView)
             and [axis.axis for axis in sorter.axis_list] == list(viewer.dims.order),
             "QtDimsSorter named dim_sorter, listing dims.order, with a help_label", used)
        popups[0].close()

    used = "viewer.buttons.guard_keys"
    from lobemap.viewer.buttons import OFF_KEYS

    shortcuts = get_settings().shortcuts.shortcuts
    need(all(shortcuts.get(action) for action in OFF_KEYS),
         f"napari's preferences holding keys for {', '.join(OFF_KEYS)}", used)

    used = "viewer.chrome.lock_layers"
    layer = viewer.add_points(ndim=3)
    with reaching("Layer.locked and its event", used):
        layer.locked = True
        viewer.layers.selection.active = layer
        viewer.layers.remove_selected()
    need(layer in viewer.layers and hasattr(layer.events, "locked"),
         "Layer.locked keeping a layer from LayerList.remove_selected", used)
