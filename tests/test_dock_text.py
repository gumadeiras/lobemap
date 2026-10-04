"""The View dock's text sits where it is read: each row's label on its control's
baseline, every Sections choice in full whatever the alignment and the brain,
the legend's letters with their words, and a disabled box drawn disabled.

Measured from the widgets as Qt lays them out and draws them, at 1440 x 900:
where each draws its text, how much room a menu gives its text, and the pixels
of a box.
"""

from __future__ import annotations

import pytest
from viewer_harness import SPACES, launched, pump, switcher

pytestmark = pytest.mark.requires_data
pytest.importorskip("napari")


def _shown(monkeypatch, space):
    """`lobemap view` on `space`, laid out at 1440 x 900, as a context."""
    from qtpy.QtCore import Qt

    context = launched(monkeypatch, "view", space)
    code, viewer = context.__enter__()
    assert code == 0
    window = viewer.window._qt_window
    window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    window.resize(1440, 900)
    window.show()
    pump(300)
    return context, viewer


def _text_rect(widget):
    """The rectangle `widget` centers its text in, in its own coordinates."""
    from qtpy.QtWidgets import (
        QAbstractSpinBox,
        QCheckBox,
        QComboBox,
        QLabel,
        QPushButton,
        QStyle,
        QStyleOptionButton,
        QStyleOptionComboBox,
    )

    style = widget.style()
    if isinstance(widget, QComboBox):
        option = QStyleOptionComboBox()
        widget.initStyleOption(option)
        return style.subControlRect(QStyle.ComplexControl.CC_ComboBox, option,
                                    QStyle.SubControl.SC_ComboBoxEditField, widget)
    if isinstance(widget, QAbstractSpinBox):
        edit = widget.lineEdit()
        margins = edit.textMargins()
        return edit.contentsRect().adjusted(margins.left(), margins.top(),
                                            -margins.right(), -margins.bottom()
                                            ).translated(edit.pos())
    if isinstance(widget, (QCheckBox, QPushButton)):
        option = QStyleOptionButton()
        widget.initStyleOption(option)
        element = (QStyle.SubElement.SE_CheckBoxContents if isinstance(widget, QCheckBox)
                   else QStyle.SubElement.SE_PushButtonContents)
        return style.subElementRect(element, option, widget)
    assert isinstance(widget, QLabel), widget
    return widget.contentsRect()


def baseline(widget, root) -> float:
    """Where `widget` draws its text's baseline, in `root`'s coordinates:
    Qt centers a line of text in its rectangle, or tops a label's."""
    from qtpy.QtCore import QPoint, Qt
    from qtpy.QtWidgets import QLabel

    rect, metrics = _text_rect(widget), widget.fontMetrics()
    top = rect.top() + (rect.height() - metrics.height()) // 2
    if isinstance(widget, QLabel) and not widget.alignment() & Qt.AlignmentFlag.AlignVCenter:
        top = rect.top()
    return widget.mapTo(root, QPoint(0, 0)).y() + top + metrics.ascent()


def labelled_rows(sw) -> list:
    """(label, the first control of its row) for every labelled row of the dock."""
    from qtpy.QtWidgets import QFormLayout

    form, rows = sw.layout(), []
    for row in range(form.rowCount()):
        label = form.itemAt(row, QFormLayout.ItemRole.LabelRole)
        field = form.itemAt(row, QFormLayout.ItemRole.FieldRole)
        if label is None or label.widget() is None or field is None:
            continue
        control = field.widget()
        if control is None:
            control = field.layout().itemAt(0).widget()
        rows.append((label.widget(), control))
    return rows


def elided(menu) -> list:
    """The choices of `menu` its text field is too narrow to show in full."""
    metrics, out = menu.fontMetrics(), []
    current = menu.currentIndex()
    menu.blockSignals(True)
    try:
        for i in range(menu.count()):
            menu.setCurrentIndex(i)
            room = _text_rect(menu).width()
            need = metrics.horizontalAdvance(menu.itemText(i))
            if need > room:
                out.append((menu.itemText(i), need, room))
    finally:
        menu.setCurrentIndex(current)
        menu.blockSignals(False)
    return out


@pytest.mark.parametrize("ndisplay", [3, 2])
def test_every_label_sits_on_its_controls_baseline(monkeypatch, ndisplay):
    """"Sections" sat 3 px below its menu's text."""
    context, viewer = _shown(monkeypatch, "FAFB14")
    try:
        sw = switcher(viewer)
        viewer.dims.ndisplay = ndisplay
        pump(100)
        rows = labelled_rows(sw)
        assert len(rows) >= 7, [label.text() for label, _ in rows]
        for label, control in rows:
            gap = baseline(label, sw) - baseline(control, sw)
            assert abs(gap) <= 0.5, (label.text(), type(control).__name__, gap)
    finally:
        context.__exit__(None, None, None)


def test_no_sections_choice_is_ever_cut_short(monkeypatch):
    """Aligned and back, in every brain, the menu keeps one width and shows
    each choice in full: in FAFB14 it went 260, 205, 258 px, and lost the
    closing parenthesis."""
    context, viewer = _shown(monkeypatch, SPACES[0])
    try:
        sw = switcher(viewer)
        viewer.dims.ndisplay = 2
        pump(100)
        width = sw.slice.width()
        for space in (*SPACES, SPACES[0]):
            if sw.session.space != space:
                sw.combo.setCurrentIndex(sw.combo.findData(space))
                pump(300)
            for aligned in (False, True, False):
                sw.align.setChecked(aligned)
                pump(50)
                assert not elided(sw.slice), (space, aligned, elided(sw.slice))
                assert sw.slice.width() == width, (space, aligned, sw.slice.width(), width)
    finally:
        context.__exit__(None, None, None)


def test_the_legend_keeps_each_letter_with_its_word_in_both_views(monkeypatch):
    """It wrapped between "R" and "right."; it shows in Slice view too."""
    from qtpy.QtCore import Qt

    context, viewer = _shown(monkeypatch, "GRABE")
    try:
        sw = switcher(viewer)
        legend = sw.legend
        for ndisplay in (3, 2):
            viewer.dims.ndisplay = ndisplay
            pump(100)
            assert legend.isVisible(), ndisplay
            # Each line as Qt wraps it, from the label's own width.
            metrics = legend.fontMetrics()
            words, lines, line = legend.text().split(" "), [], ""
            for word in words:
                trial = f"{line} {word}".strip()
                if line and metrics.horizontalAdvance(trial) > legend.contentsRect().width():
                    lines.append(line)
                    line = word
                else:
                    line = trial
            lines.append(line)
            letters = {"A", "P", "D", "V", "L", "R"}
            for text in lines:
                assert text.split()[-1].rstrip(",.") not in letters, lines
            assert legend.heightForWidth(legend.width()) <= legend.height(), ndisplay
            assert legend.alignment() & Qt.AlignmentFlag.AlignLeft
    finally:
        context.__exit__(None, None, None)


def test_a_disabled_perspective_box_is_drawn_as_a_fresh_one(monkeypatch):
    """A value typed in 3D left its text selected, drawn highlighted, once
    Slice view disabled the box."""
    from qtpy.QtCore import Qt
    from qtpy.QtTest import QTest

    context, viewer = _shown(monkeypatch, "GRABE")
    try:
        sw = switcher(viewer)
        box = sw.camera.perspective
        viewer.dims.ndisplay = 2
        pump(100)
        fresh = box.grab().toImage()
        viewer.dims.ndisplay = 3
        pump(100)
        box.setFocus()
        QTest.keyClick(box, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
        QTest.keyClicks(box, "0")
        QTest.keyClick(box, Qt.Key.Key_Return)
        box.selectAll()
        pump(50)
        assert box.lineEdit().hasSelectedText()
        viewer.dims.ndisplay = 2
        pump(100)
        assert not box.isEnabled()
        assert not box.lineEdit().hasSelectedText()
        assert box.grab().toImage() == fresh
    finally:
        context.__exit__(None, None, None)


def test_the_align_box_does_not_repeat_its_rows_label(monkeypatch):
    """"Align sections to the anatomical axes" repeated "Sections"; its
    tooltip names the three axes in the menu's words."""
    context, viewer = _shown(monkeypatch, "GRABE")
    try:
        sw = switcher(viewer)
        assert "section" not in sw.align.text().lower()
        for axis in ("anterior–posterior", "dorsal–ventral", "medial–lateral"):
            assert axis in sw.align.toolTip()
            assert any(axis in sw.slice.itemText(i) for i in range(sw.slice.count())) or (
                sw.slice.count() < 3)
    finally:
        context.__exit__(None, None, None)
