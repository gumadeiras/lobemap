"""napari's own window as lobemap lays it out: its docks, buttons and drawing tools.

napari opens with controls for making and editing data: new and delete
layer buttons, a console, grid, roll and transpose buttons, sixteen
drawing tools for the outline layers, and a transform tool on every layer.
lobemap's layers are made non-editable and locked against deletion, and
the window is arranged as lobemap's: the View dock tabbed with napari's
layer settings above the layer list on the left, and the compartment
tables alone on the right. The buttons stay where napari puts them, around
the layer list; `buttons` keeps them in step with the View dock.

napari has no public API for its own docks, or a dock with no close
button. These go through `Window._qt_viewer`, `Window._qt_window` and
napari's dock widget class, and `tests/test_napari_private.py` checks each.
lobemap's layers are locked by napari's public `editable` and `locked`.
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

#: The spacing unit of the View dock and napari's button rows, in pixels:
#: one between a label and its control, between controls in a row and
#: between rows of a group, two between groups, one at the dock's edges.
GRID = 8

#: The height of every control of the View dock: a line of text, with half a
#: grid unit above and below it, as napari pads its buttons -- three grid
#: units, so its rows fall on the grid.
CONTROL_HEIGHT = 3 * GRID

#: The look of every tab bar of the window: the panel's Glomeruli and
#: Neuropils, and the View dock's tab beside napari's layer settings. Room
#: round each title -- napari's 3 x 6 px left the text almost touching the
#: tab's edges -- and no band of napari's tab color behind the tabs. Qt
#: centres a title's line in the tab, which centres its capitals: every
#: title of a bar stands on one line.
TAB_STYLE = "QTabBar { background: transparent; } QTabBar::tab { padding: 8px 12px; }"

#: napari's own docks, by the names lobemap shows for them.
LAYER_SETTINGS = "Layer settings"
LAYERS = "Layers"

#: Said when a layer of lobemap's is unlocked from the layer list's menu.
STAYS_LOCKED = (
    "lobemap's own layers stay locked: the panel and the View tab draw them, "
    "and deleting one would leave them naming a layer that is gone. To hide "
    "one, click its eye, or untick its rows in the panel."
)

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
    fit = functools.partial(_fit_title_bar, dock)
    fit()
    # napari builds the title bar again when the dock floats or docks.
    dock.topLevelChanged.connect(fit)
    dock.dockLocationChanged.connect(fit)
    window._qt_window.addDockWidget(dock.qt_area, dock)
    window.window_menu.addAction(dock.toggleViewAction())
    return dock


def _fit_title_bar(dock, *_) -> None:
    """Keep a dock's title bar to the room the dock gives it.

    napari's title bar tells the dock it is 20 px tall, its size hint, and
    holds itself to 26, its minimum: the dock put its widget 20 px down
    and the title bar covered the top 6 px of it -- the top of the panel's
    tabs, their rounded corners and frame, so each title sat high in what
    was left. Its title fits 20 px.
    """
    from qtpy.QtWidgets import QDockWidget

    bar = dock.titleBarWidget()
    if bar is None or dock.features() & QDockWidget.DockWidgetFeature.DockWidgetVerticalTitleBar:
        return
    room = bar.sizeHint().height()
    if 0 < room < bar.minimumHeight():
        bar.setMinimumHeight(room)


def tidy_tab_bar(bar) -> None:
    """Give a tab bar the window's look (`TAB_STYLE`), and let the wheel
    change its tab only once it has focus, as on a menu (`wheel`): under
    some styles a scroll passing over the tabs turned them."""
    from .wheel import guard_wheel

    bar.setStyleSheet(TAB_STYLE)
    # The line Qt draws under a dock's tabs: the panel's, in a tab widget,
    # has none.
    bar.setDrawBase(False)
    guard_wheel(bar)


def _watch_tab_bars(window) -> None:
    """Tidy each tab bar the main window makes for its docks' tabs, once.

    Qt makes one for a group of tabbed docks when it lays the group out,
    and can make another when a dock leaves the group and comes back: each
    is tidied as Qt polishes it, and any there already now.
    """
    from qtpy.QtCore import QEvent, QObject, Qt
    from qtpy.QtWidgets import QTabBar

    def tidy_once(widget) -> None:
        if isinstance(widget, QTabBar) and not widget.property("lobemap_tidied"):
            widget.setProperty("lobemap_tidied", True)
            tidy_tab_bar(widget)

    class Polished(QObject):
        def eventFilter(self, watched, event) -> bool:
            if event.type() == QEvent.Type.ChildPolished:
                tidy_once(event.child())
            return False

    window.installEventFilter(Polished(window))
    for bar in window.findChildren(QTabBar, options=Qt.FindChildOption.FindDirectChildrenOnly):
        tidy_once(bar)


def tidy(viewer, view_dock, panel_dock) -> None:
    """Arrange the docks as lobemap's.

    Left: the View dock, tabbed with napari's layer settings, above the
    layer list with napari's buttons. Right: the compartment panel, at
    full height.
    """
    from qtpy.QtCore import Qt, QTimer
    from qtpy.QtWidgets import QTabWidget, QWidget

    qt_viewer = viewer.window._qt_viewer
    window = viewer.window._qt_window
    controls, layers = qt_viewer.dockLayerControls, qt_viewer.dockLayerList
    _retitle(controls, LAYER_SETTINGS)
    _retitle(layers, LAYERS)
    window.setTabPosition(Qt.DockWidgetArea.LeftDockWidgetArea,
                          QTabWidget.TabPosition.North)
    # The list goes under the View dock, then the settings join its tabs:
    # the View tab first, and the one shown.
    window.splitDockWidget(view_dock, layers, Qt.Orientation.Vertical)
    _watch_tab_bars(window)
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
    """Keep lobemap's own layers out of napari's editing modes, and undeleted.

    lobemap draws its layers itself, and napari's modes edit them behind
    its back: a shape drawn into an outline layer is lost at the next
    slice, and the transform tool, on key 2 for a surface, moved a mesh
    away from the image it was registered to, with nothing to put it back.
    napari's `editable` is the public switch for both: off, the drawing
    and transform tools are disabled and no mode but pan and zoom can be
    entered. Its key help, which lists those modes, is cleared too.

    Deleting one -- the main 3D layer is the one selected at open -- left
    the panel and hover naming a layer that was gone, with no undo. napari's
    `locked` keeps a layer from napari's delete button, its keys and its
    conversions, which delete the layer they convert; it marks the layer
    with a lock in the list, and says so when a delete passes it by. A layer
    unlocked from the list's menu is locked again, and that is said too.

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
    layer.events.locked.connect(functools.partial(_relock, layer))
    QTimer.singleShot(0, lock)


def _lock(layer) -> None:
    if "lobemap" not in layer.metadata:
        return
    if layer.editable:
        layer.editable = False
    if layer.help:
        layer.help = ""
    if not layer.locked:
        layer.locked = True


def _relock(layer) -> None:
    """Lock again a layer of lobemap's unlocked from the layer list's menu."""
    if "lobemap" in layer.metadata and not layer.locked:
        from napari.utils.notifications import show_info

        layer.locked = True
        show_info(STAYS_LOCKED)


__all__ = [
    "CONTROL_HEIGHT",
    "GRID",
    "LAYERS",
    "LAYER_SETTINGS",
    "LEFT_WIDTH",
    "RIGHT_WIDTH",
    "STAYS_LOCKED",
    "TAB_STYLE",
    "add_dock",
    "lock_layers",
    "tidy",
    "tidy_tab_bar",
]
