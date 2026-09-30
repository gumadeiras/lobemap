"""Drive the real viewer the way a user does, and read back what it draws.

`launched` runs `lobemap.cli.main` end to end with only the window hidden
and the event loop stubbed. The readers below report what is rendered --
which layer is visible, which compartments its colors or shapes draw --
rather than what a widget claims, so a test can compare the two.
"""

from __future__ import annotations

import contextlib
import os
import time
from pathlib import Path

import numpy as np

REGISTRY = Path(__file__).resolve().parents[1] / "registry"
SPACES = ("FAFB14", "JRCFIB2018F", "JRCFIB2022M", "GRABE")


def data_root() -> Path:
    """The data the registry reads by default, wherever it is."""
    from lobemap.core.registry import default_data_root

    return Path(default_data_root(REGISTRY))


def pump(ms: float = 0) -> None:
    """Let Qt run: queued signals, timers, and deferred widget deletion."""
    from qtpy.QtCore import QCoreApplication, QEvent
    from qtpy.QtWidgets import QApplication

    end = time.perf_counter() + ms / 1000
    while True:
        QApplication.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        if time.perf_counter() >= end:
            return
        time.sleep(0.01)


@contextlib.contextmanager
def launched(monkeypatch, *argv):
    """Run `lobemap <argv>`; yield (exit code, viewer or None).

    The window is created hidden and never maximized -- `maximize` would
    show it -- and `napari.run` returns at once, so the viewer is left as
    the user would first see it. It is closed afterwards.
    """
    import napari

    from lobemap import cli

    created = []
    real = napari.Viewer

    def hidden(*args, **kwargs):
        kwargs["show"] = False
        viewer = real(*args, **kwargs)
        created.append(viewer)
        return viewer

    monkeypatch.setattr(napari, "Viewer", hidden)
    monkeypatch.setattr(napari, "run", lambda *a, **k: None)
    monkeypatch.setattr("lobemap.viewer.app.maximize", lambda viewer: False)
    monkeypatch.setenv("LOBEMAP_CRASH_LOG", os.devnull)
    try:
        code = cli.main(["--registry", str(REGISTRY), *argv])
        yield code, (created[0] if created else None)
    finally:
        for viewer in created:
            viewer.close()
        pump()


def dead_network(monkeypatch) -> None:
    """Make every download fail as a refused connection, so nothing leaves the host.

    Patched at `urlopen` rather than through proxy variables: urllib builds
    its default opener once per process, from the environment at the first
    download, so a proxy set here had no effect after any earlier test had
    downloaded.
    """
    import urllib.error
    import urllib.request

    def refuse(url, *args, **kwargs):
        raise urllib.error.URLError(ConnectionRefusedError(61, "Connection refused"))

    monkeypatch.setattr(urllib.request, "urlopen", refuse)


def switcher(viewer):
    from lobemap.viewer.switcher import SpaceSwitcher

    found = viewer.window._qt_window.findChildren(SpaceSwitcher)
    assert len(found) == 1, found
    return found[0]


def session(viewer):
    return switcher(viewer).session


def switch_to(viewer, space: str) -> None:
    """Pick `space` in the space menu, as a user would."""
    combo = switcher(viewer).combo
    combo.setCurrentIndex(combo.findData(space))
    pump()


def docks(viewer, title: str) -> list:
    from qtpy.QtWidgets import QDockWidget

    pump()
    return [d for d in viewer.window._qt_window.findChildren(QDockWidget)
            if d.windowTitle() == title]


def handler_counts(viewer) -> dict[str, int]:
    """Every hook a scene can leave behind on objects that outlive it."""
    canvas = viewer.window._qt_viewer.canvas
    out = {
        f"dims.{name}": len(getattr(viewer.dims.events, name).callbacks)
        for name in ("ndisplay", "current_step", "order", "point")
    }
    out.update({
        f"canvas.{name}": len(getattr(canvas.events, name).callbacks)
        for name in ("draw", "resize", "mouse_press", "mouse_wheel", "key_press")
    })
    out["viewer.mouse_move_callbacks"] = len(viewer.mouse_move_callbacks)
    return out


def layer_names(viewer) -> list[str]:
    return sorted(layer.name for layer in viewer.layers)


# -- what is drawn --------------------------------------------------------


def mode_layer(surface, contour=None):
    """The layer that draws this atlas in the current mode."""
    if contour is not None and surface.viewer.dims.ndisplay == 2:
        return contour.layer
    return surface.layer


def drawn(surface, contour=None) -> set[int]:
    """Compartment indices this atlas puts on screen right now.

    3D: the mesh layer is visible, the compartment's geometry is resident,
    and its color is opaque. 2D, with a contour overlay: the contour layer
    is visible and holds a shape of that compartment -- and the mesh, if it
    is on as well, draws everything it holds.
    """
    names = surface.meshset.names
    out: set[int] = set()
    if contour is not None and surface.viewer.dims.ndisplay == 2:
        if contour.layer.visible:
            out = {names.index(contour.name_at_shape(i))
                   for i in range(len(contour.layer.data))}
        if not surface.layer.visible:
            return out
    if not surface.layer.visible:
        return set()
    resident = {round(float(v)) for v in np.unique(surface.layer.data[2])}
    alpha = np.asarray(surface.layer.colormap.colors)[:, 3]
    n = surface.meshset.n_compartments
    opaque = {i for i in range(n) if alpha[min(i, len(alpha) - 1)] > 0}
    return out | (resident & opaque)


def checked(tab) -> set[int]:
    from qtpy.QtCore import Qt

    from lobemap.viewer.panel import VISIBLE_COL

    return {tab._index_of(r) for r in range(tab.table.rowCount())
            if tab.table.item(r, VISIBLE_COL).checkState() == Qt.Checked}


def planes_cut(surface) -> set[int]:
    """Checked compartments the current 2D plane actually crosses."""
    axis = int(surface.viewer.dims.order[0])
    point = float(surface.viewer.dims.point[axis])
    out = set()
    for i in surface.selection:
        v, _ = surface.meshset.compartment(i)
        if len(v) and v[:, axis].min() <= point <= v[:, axis].max():
            out.add(i)
    return out


def assert_rows_match_drawing(sess) -> None:
    """Every tab: checked rows, count text and rendered geometry agree.

    Call it once the scene has settled (`pump(300)`): a compartment checked
    after compaction reaches the mesh with the next compaction. In 2D only
    the checked compartments this plane crosses can have a contour, so
    those are what must be drawn.
    """
    two_d = sess.viewer.dims.ndisplay == 2
    for name, tab in sess.panel.tabs.items():
        contour = sess.contours.get(name)
        rows = checked(tab)
        got = drawn(tab.surface, contour)
        want = planes_cut(tab.surface) if two_d else rows
        n = tab.table.rowCount()
        assert rows == tab.surface.selection, (name, "rows != selection")
        assert got == want, (name, sorted(got ^ want)[:8])
        assert tab.count.text() == f"{len(rows)} / {n} shown", (name, tab.count.text())
        if not rows:
            assert not tab.surface.layer.visible, name
            if contour is not None:
                assert not contour.layer.visible, name
        elif two_d and contour is not None:
            assert not tab.surface.layer.visible, (name, "mesh drawn in 2D")


# -- the cursor -----------------------------------------------------------


def canvas_position(viewer, world) -> tuple[float, float]:
    """Canvas pixel at which `world` is drawn: `_map_canvas2world` inverted."""
    canvas = viewer.window._qt_viewer.canvas
    transform = canvas.view.transform * canvas.view.scene.transform
    point = np.asarray(world, float)[list(viewer.dims.displayed)][::-1]
    mapped = np.asarray(transform.map(np.r_[point, 0.0][:3] if len(point) == 2
                                      else point), float)
    return float(mapped[0] / mapped[3]), float(mapped[1] / mapped[3])


def hover(viewer, world) -> str:
    """Move the mouse over `world` through napari's own event path."""
    from vispy.app.canvas import MouseEvent

    canvas = viewer.window._qt_viewer.canvas
    viewer.status = ""
    event = MouseEvent(type="mouse_move", pos=canvas_position(viewer, world),
                       modifiers=(), buttons=[])
    canvas._on_mouse_move(event)
    pump()
    status = viewer.status
    return status if isinstance(status, str) else str(status)
