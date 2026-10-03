"""napari's own window as lobemap lays it out: its docks, buttons and drawing tools.

napari opens with controls for making and editing data: new and delete
layer buttons, a console, grid, roll and transpose buttons, sixteen
drawing tools for the outline layers, and a transform tool on every layer.
None of them changes what a lobemap scene shows, and three -- 2D/3D, roll and transpose -- do what the View
dock does without its bookkeeping. So the buttons are hidden, lobemap's
layers are made non-editable, and the window is arranged as lobemap's: the
View dock tabbed with napari's layer settings above the layer list on the
left, and the compartment tables alone on the right.

napari has no public API for its buttons, its own docks, or a dock with no
close button. These go through `Window._qt_viewer`, `Window._qt_window`
and napari's dock widget class, and `tests/test_napari_private.py` checks
each. lobemap's layers are locked by napari's public `editable`.
"""

from __future__ import annotations

import contextlib
import functools
import weakref

#: The left column's width and the right column's at open, in pixels. The
#: left one is no narrower than napari's layer settings, 354 to 416 px, so
#: at 1440 px the canvas keeps 558 to 620.
LEFT_WIDTH = 330
RIGHT_WIDTH = 440

#: napari's own docks, by the names lobemap shows for them.
LAYER_SETTINGS = "Layer settings"
LAYERS = "Layers"

#: The viewers whose own layers are kept locked; see `lock_layers`.
_LOCKING: weakref.WeakSet = weakref.WeakSet()


def add_dock(viewer, widget, name: str, area: str):
    """Dock `widget` with no close button, and list it in the Window menu.

    napari's `add_dock_widget` gives a dock a close button that deletes it,
    and lists it in no menu unless told to: a closed dock was gone until
    the next launch. napari makes its own layer docks with the same class
    and no close button, and so does this. The Window menu lists the dock,
    so one hidden from its title bar comes back from there.
    """
    from napari._qt.widgets.qt_viewer_dock_widget import QtViewerDockWidget

    window = viewer.window
    dock = QtViewerDockWidget(window._qt_viewer, widget, name=name, area=area,
                              close_btn=False)
    window._qt_window.addDockWidget(dock.qt_area, dock)
    window.window_menu.addAction(dock.toggleViewAction())
    return dock


def tidy(viewer, view_dock, panel_dock) -> None:
    """Hide napari's buttons and arrange the docks as lobemap's.

    Left: the View dock, tabbed with napari's layer settings, above the
    layer list. Right: the compartment panel, at full height.

    Hidden: the viewer buttons (console, 2D/3D, roll, transpose, grid,
    Home) and the layer buttons (new points, shapes and labels, delete).
    The View dock does 2D/3D, Home and the slice axis; nothing in a scene
    needs the others. Their keyboard shortcuts stay napari's.
    """
    from qtpy.QtCore import Qt, QTimer
    from qtpy.QtWidgets import QTabWidget, QWidget

    qt_viewer = viewer.window._qt_viewer
    window = viewer.window._qt_window
    qt_viewer.viewerButtons.hide()
    qt_viewer.layerButtons.hide()
    controls, layers = qt_viewer.dockLayerControls, qt_viewer.dockLayerList
    _retitle(controls, LAYER_SETTINGS)
    _retitle(layers, LAYERS)
    window.setTabPosition(Qt.DockWidgetArea.LeftDockWidgetArea,
                          QTabWidget.TabPosition.North)
    # The list goes under the View dock, then the settings join its tabs:
    # the View tab first, and the one shown.
    window.splitDockWidget(view_dock, layers, Qt.Orientation.Vertical)
    window.tabifyDockWidget(view_dock, controls)
    for dock in (view_dock, controls):
        # The tab names each; a title bar under it named it again. napari
        # gives a dock a title bar back when it floats.
        dock.setTitleBarWidget(QWidget(dock))
    QTimer.singleShot(0, functools.partial(_settle, window, view_dock, layers, panel_dock))


def _settle(window, view_dock, layers, panel_dock) -> None:
    """Show the View tab and size the columns, once the window has laid them out.

    Until it has, Qt has no tab to raise and keeps no size it is given: the
    panel fell to its minimum width. A window closed first is left alone.
    """
    from qtpy.QtCore import Qt

    with contextlib.suppress(RuntimeError):         # its Qt objects are gone
        view_dock.raise_()
        window.resizeDocks([view_dock, panel_dock], [LEFT_WIDTH, RIGHT_WIDTH],
                           Qt.Orientation.Horizontal)
        # Qt shares the column by ratio and keeps each dock's minimum: the
        # tabs get the height they need and the layer list the rest. What
        # the View tab needs is its rows' full height, laid out; below it,
        # Qt squeezed the rotation rows into each other.
        controls = view_dock.widget()
        controls.setMinimumHeight(controls.sizeHint().height())
        window.resizeDocks([view_dock, layers], [1, 10_000], Qt.Orientation.Vertical)


def _retitle(dock, name: str) -> None:
    """Rename one of napari's docks: its tab, its title bar, its next title bar.

    napari builds the title bar again from `name` when the dock floats.
    """
    dock.name = name
    dock.setWindowTitle(name)
    dock.title.title.setText(name)


def lock_layers(viewer) -> None:
    """Keep lobemap's own layers out of napari's editing modes.

    lobemap draws its layers itself, and napari's modes edit them behind
    its back: a shape drawn into an outline layer is lost at the next
    slice, and the transform tool, on key 2 for a surface, moved a mesh
    away from the image it was registered to, with nothing to put it back.
    napari's `editable` is the public switch for both: off, the drawing
    and transform tools are disabled and no mode but pan and zoom can be
    entered. Its key help, which lists those modes, is cleared too.

    A layer of lobemap's is known by the `lobemap` metadata its maker
    writes, which some write only once napari has added the layer. So each
    layer added is looked at again as soon as the event loop turns, and
    the layers present now are locked at once. napari turns `editable`
    back on whenever it resets a layer -- a Shapes layer entering 2D, a
    surface given new data -- so it is turned off again each time. A layer
    the user adds is left alone.

    Installed once per viewer; later calls only lock the layers present.
    """
    if viewer not in _LOCKING:
        _LOCKING.add(viewer)
        viewer.layers.events.inserted.connect(lambda event: _watch(event.value))
        for layer in viewer.layers:
            _watch(layer)
    for layer in viewer.layers:
        _lock(layer)


def _watch(layer) -> None:
    from qtpy.QtCore import QTimer

    lock = functools.partial(_lock, layer)
    layer.events.editable.connect(lock)
    QTimer.singleShot(0, lock)


def _lock(layer) -> None:
    if "lobemap" not in layer.metadata:
        return
    if layer.editable:
        layer.editable = False
    if layer.help:
        layer.help = ""


__all__ = [
    "LAYERS",
    "LAYER_SETTINGS",
    "LEFT_WIDTH",
    "RIGHT_WIDTH",
    "add_dock",
    "lock_layers",
    "tidy",
]
