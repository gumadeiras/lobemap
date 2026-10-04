"""The two tab bars, measured where the window draws them.

The panel's Glomeruli and Neuropils tabs, on the right, and the View and
Layer settings tabs, on the left, are one kind of tab bar: as tall, as
padded, each title in the middle of its tab by its capital letters, every
title of a bar on one baseline. Each is read off the window as it is drawn,
so whatever covers a tab counts: a measure of the tab bar alone missed the
dock's title bar hiding the top of the panel's tabs. Each bar stands on an
edge across its section, which its current tab joins.

The wheel over either bar changes no tab.
"""

from __future__ import annotations

import contextlib
from collections import Counter

import pytest
from viewer_harness import docks, launched, pump, session, switch_to

from lobemap.viewer.chrome import EDGE

pytestmark = pytest.mark.requires_data
pytest.importorskip("napari")

SPACES = ("FAFB14", "JRCFIB2018F", "JRCFIB2022M", "GRABE")
LEFT_TITLES = ["View", "Layer settings"]

#: How much the room above a title's capitals may differ from the room
#: below them, and the room left of it from the room right of it, in
#: screen pixels.
OFF_CENTRE = 1.0
#: The least room between a title and its tab's drawn edges, in pixels.
ROOM_X, ROOM_Y = 10, 8


def _lay_out(viewer) -> None:
    from qtpy.QtCore import Qt

    window = viewer.window._qt_window
    window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    window.resize(1440, 900)
    window.show()
    pump(300)


@contextlib.contextmanager
def _style(name: str | None):
    """The whole application drawn in another style, `None` its own, and
    given back after."""
    from qtpy.QtWidgets import QApplication

    own = QApplication.style().name()
    if name is not None:
        QApplication.setStyle(name)
        pump(100)
    try:
        yield
    finally:
        if name is not None:
            QApplication.setStyle(own)
            pump(100)


def left_bar(viewer):
    """The tab bar Qt keeps for the View dock and napari's layer settings."""
    from qtpy.QtWidgets import QTabBar

    found = [bar for bar in viewer.window._qt_window.findChildren(QTabBar)
             if bar.isVisible()
             and [bar.tabText(i) for i in range(bar.count())] == LEFT_TITLES]
    assert len(found) == 1, found
    return found[0]


def drawn_tabs(window, bar) -> list[dict]:
    """Each tab of `bar` as the window draws it, in logical pixels.

    `shape`: the box of the tab's paint -- its rows and columns that differ
    from what is beside the tab in the same row. `top` and `base`: its
    title's capitals, from the top of its first letter to the line most of
    its letters stand on. `left` and `right`: its title's ink.
    """
    pixmap = window.grab()
    image = pixmap.toImage()
    ratio = pixmap.devicePixelRatio()

    def color(x, y):
        return image.pixelColor(x, y).getRgb()[:3]

    def far(a, b, by):
        return sum(abs(p - q) for p, q in zip(a, b, strict=True)) > by

    corner = bar.mapTo(window, bar.rect().topLeft())
    last = bar.tabRect(bar.count() - 1)
    # Beside the tabs, in the same row: right of the last one.
    beside = round((corner.x() + last.right() + 4) * ratio)
    out = []
    for i in range(bar.count()):
        rect = bar.tabRect(i)
        x0 = round((corner.x() + rect.left()) * ratio)
        x1 = round((corner.x() + rect.right() + 1) * ratio)
        y0 = round((corner.y() + rect.top()) * ratio)
        y1 = round((corner.y() + rect.bottom() + 1) * ratio)
        inner = range(x0 + round(6 * ratio), x1 - round(6 * ratio))
        rows = [y for y in range(y0, y1)
                if sum(far(color(x, y), color(beside, y), 30) for x in inner) > 0.8 * len(inner)]
        assert rows, (bar.tabText(i), "nothing drawn")
        top, bottom = min(rows), max(rows) + 1
        middle = range(top + round(4 * ratio), bottom - round(4 * ratio))
        cols = [x for x in range(x0, x1)
                if sum(far(color(x, y), color(beside, y), 30) for y in middle) > 0.8 * len(middle)]
        left, right = min(cols), max(cols) + 1
        ink = []
        edge = round(2 * ratio)
        for y in range(top + edge, bottom - edge):
            row = [(x, color(x, y)) for x in range(left + edge, right - edge)]
            fill = Counter(c for _x, c in row).most_common(1)[0][0]
            ink += [(x, y) for x, c in row if far(c, fill, 90)]
        assert ink, (bar.tabText(i), "no title drawn")
        xs = sorted({x for x, _y in ink})
        first = [xs[0]]
        for x in xs[1:]:
            if x != first[-1] + 1:
                break
            first.append(x)
        letter = [y for x, y in ink if x in set(first)]
        # The line most letters stand on: what most columns of ink end at.
        ends = Counter(max(y for x, y in ink if x == column) for column in xs)
        out.append({
            "title": bar.tabText(i),
            "shape": (left / ratio, top / ratio, right / ratio, bottom / ratio),
            "top": min(letter) / ratio,
            "base": (ends.most_common(1)[0][0] + 1) / ratio,
            "left": xs[0] / ratio,
            "right": (xs[-1] + 1) / ratio,
        })
    return out


def _check_bar(window, bar, where) -> list[dict]:
    """Every title of `bar` in the middle of its drawn tab, with room round
    it, in full, and on one baseline with the others. Its tabs, as drawn."""
    tabs = drawn_tabs(window, bar)
    for tab in tabs:
        left, top, right, bottom = tab["shape"]
        rooms = (tab["left"] - left, right - tab["right"], tab["top"] - top, bottom - tab["base"])
        said = (where, tab["title"], tab["shape"], rooms)
        assert abs(rooms[0] - rooms[1]) <= OFF_CENTRE, said
        assert abs(rooms[2] - rooms[3]) <= OFF_CENTRE, said
        assert min(rooms[:2]) >= ROOM_X and min(rooms[2:]) >= ROOM_Y, said
        full = bar.fontMetrics().horizontalAdvance(tab["title"])
        assert tab["right"] - tab["left"] >= full - 3, said
    bases = {tab["base"] - tab["shape"][1] for tab in tabs}
    assert max(bases) - min(bases) <= 0.5, (where, tabs)
    return tabs


@pytest.mark.parametrize("style", [None, "Fusion"], ids=["native", "fusion"])
def test_every_tab_title_sits_in_the_middle_of_its_drawn_tab(monkeypatch, style):
    """Both bars, in every brain, with each tab current in turn, under the
    platform's own style and under Fusion. The left tabs are as tall as the
    panel's, with as much room on either side of their titles."""
    from qtpy.QtWidgets import QApplication, QToolButton

    with launched(monkeypatch, "view", SPACES[0]) as (code, viewer), _style(style):
        assert code == 0
        if style is None:
            assert QApplication.style().name() == "macos"
        _lay_out(viewer)
        window = viewer.window._qt_window
        for space in SPACES:
            if space != SPACES[0]:
                switch_to(viewer, space)
                pump(100)
            bar = session(viewer).panel.tabBar()
            assert [bar.tabText(i) for i in range(bar.count())] == (
                ["Glomeruli"] if space == "GRABE" else ["Glomeruli", "Neuropils"])
            # No scroll arrows: the tabs fit the column.
            assert not [b for b in bar.findChildren(QToolButton) if b.isVisible()], space
            left = left_bar(viewer)
            for each in (bar, left):
                for current in range(each.count()):
                    each.setCurrentIndex(current)
                    pump(50)
                    drawn = _check_bar(window, each, space)
                each.setCurrentIndex(0)
                pump(50)
            right_tabs, left_tabs = drawn_tabs(window, bar), drawn_tabs(window, left)
            heights = {round(t["shape"][3] - t["shape"][1]) for t in right_tabs + left_tabs}
            assert len(heights) == 1, (space, right_tabs, left_tabs)
            sides = {round(t["left"] - t["shape"][0]) for t in right_tabs + left_tabs}
            assert max(sides) - min(sides) <= 1, (space, sides)
            assert drawn


@pytest.mark.parametrize("style", [None, "Fusion"], ids=["native", "fusion"])
def test_the_wheel_over_a_tab_bar_changes_no_tab(monkeypatch, style):
    """Wheel events over every tab of both bars, either way: the same tab
    stays open. Under Fusion, Qt turned the tabs with the wheel."""
    from qtpy.QtCore import QPoint, QPointF, Qt
    from qtpy.QtGui import QWheelEvent
    from qtpy.QtWidgets import QApplication

    def wheel(bar, pos, dy):
        local = QPointF(pos)
        event = QWheelEvent(local, QPointF(bar.mapToGlobal(pos)), QPoint(0, 0), QPoint(0, dy),
                            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                            Qt.ScrollPhase.NoScrollPhase, False)
        QApplication.sendEvent(bar, event)
        pump(20)

    with launched(monkeypatch, "view", "JRCFIB2018F") as (code, viewer), _style(style):
        assert code == 0
        _lay_out(viewer)
        panel = session(viewer).panel
        for bar in (panel.tabBar(), left_bar(viewer)):
            for current in range(bar.count()):
                bar.setCurrentIndex(current)
                pump(50)
                for i in range(bar.count()):
                    for dy in (120, -120, 360, -360):
                        wheel(bar, bar.tabRect(i).center(), dy)
                        assert bar.currentIndex() == current, (bar.tabText(i), dy)


def _edge(window, bar, section, color) -> dict:
    """The edge under `bar`, as the window draws it: the rows right under
    the current tab's drawn shape, which must be `color` across the whole
    of `section`, and the row above, in which the current tab's foot must
    be `color` too while what is beside the tabs is not."""
    from qtpy.QtGui import QColor

    pixmap = window.grab()
    image = pixmap.toImage()
    ratio = pixmap.devicePixelRatio()
    want = QColor(color).getRgb()[:3]

    def near(x, y) -> bool:
        got = image.pixelColor(x, y).getRgb()[:3]
        return sum(abs(p - q) for p, q in zip(got, want, strict=True)) <= 30

    tab = drawn_tabs(window, bar)[bar.currentIndex()]
    left, _top, right, bottom = (round(v * ratio) for v in tab["shape"])
    corner = section.mapTo(window, section.rect().topLeft())
    x0, x1 = round(corner.x() * ratio), round((corner.x() + section.width()) * ratio)
    span = range(x0 + round(2 * ratio), x1 - round(2 * ratio))
    rows = [y for y in range(bottom, bottom + round(3 * EDGE * ratio))
            if sum(near(x, y) for x in span) >= 0.98 * len(span)]
    beside = round((bar.mapTo(window, bar.rect().topLeft()).x()
                    + bar.tabRect(bar.count() - 1).right() + 4) * ratio)
    foot = range(left + round(4 * ratio), right - round(4 * ratio))
    return {"rows": rows, "bottom": bottom, "ratio": ratio,
            "foot": sum(near(x, bottom - 1) for x in foot) / len(foot),
            "beside": near(beside, bottom - 1)}


@pytest.mark.parametrize("style", [None, "Fusion"], ids=["native", "fusion"])
def test_each_tab_bar_stands_on_an_edge_across_its_section(monkeypatch, style):
    """Both bars, in every brain, with each tab current in turn: right under
    the tabs a line of the theme's selected-tab color runs across the whole
    section, the View dock's column on the left and the panel on the right,
    and the current tab's foot joins it, with no gap. In the light theme,
    the line takes the light theme's color."""
    from lobemap.viewer.app import VIEW_TITLE
    from lobemap.viewer.chrome import LAYER_SETTINGS, edge_color

    with launched(monkeypatch, "view", SPACES[0]) as (code, viewer), _style(style):
        assert code == 0
        _lay_out(viewer)
        window = viewer.window._qt_window
        # The left column's sections: the dock of each of its tabs.
        column = [docks(viewer, title)[0] for title in (VIEW_TITLE, LAYER_SETTINGS)]
        for space in SPACES:
            if space != SPACES[0]:
                switch_to(viewer, space)
                pump(100)
            panel = session(viewer).panel
            themes = ("dark", "light") if space == SPACES[-1] and style is None else ("dark",)
            for theme in themes:
                viewer.theme = theme
                pump(100)
                color = edge_color(viewer)
                for bar, sections in ((panel.tabBar(), [panel, panel]),
                                      (left_bar(viewer), column)):
                    for current in range(bar.count()):
                        bar.setCurrentIndex(current)
                        pump(50)
                        edge = _edge(window, bar, sections[current], color)
                        said = (space, theme, bar.tabText(current), edge)
                        # Right under the tab, and as thick as it is meant to be.
                        assert edge["rows"] and edge["rows"][0] == edge["bottom"], said
                        assert len(edge["rows"]) == round(EDGE * edge["ratio"]), said
                        assert edge["foot"] >= 0.95 and not edge["beside"], said
                    bar.setCurrentIndex(0)
                    pump(50)
            viewer.theme = "dark"
            pump(100)
