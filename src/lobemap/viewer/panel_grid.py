"""The panel's grid, and the label column its forms share.

The panel is laid out on the View dock's grid (`chrome.GRID`): its menus,
search and button as tall as the dock's controls and as wide as their
content, a grid unit between the parts of a group and two between groups.
Every label of a form -- Source, Driver line, each detail -- is a
`ColumnLabel`, as wide as the widest of them, so the controls and values
beside them start at one edge in every tab.
"""

from __future__ import annotations

from qtpy.QtCore import QSize, Qt
from qtpy.QtWidgets import QFormLayout, QLabel, QSizePolicy

from . import rows as R
from .chrome import CONTROL_HEIGHT, GRID

#: The panel's spacing grid: the View dock's (`chrome.GRID`). The parts of
#: one group -- a search and its driver lines, a table and its count, a
#: value and the next -- and a label and what it labels sit `GAP` apart;
#: groups sit `GROUP_GAP` apart, and a tab's contents `MARGIN` inside its
#: frame. Every menu, button and the search are as tall as the View dock's
#: controls, `chrome.CONTROL_HEIGHT`.
GAP, GROUP_GAP, MARGIN = GRID, 2 * GRID, GRID
#: What labels the source menu at the top of each tab.
SOURCE = "Source"

#: What labels the driver-line menu.
DRIVER_LINE = "Driver line"

#: Every label of the panel's label column, in either kind of tab.
COLUMN_LABELS = (SOURCE, DRIVER_LINE, *R.GLOMERULUS_DETAILS, *R.NEUROPIL_DETAILS)


def fit_control(control) -> None:
    """As wide as its content and as tall as the View dock's controls."""
    control.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    control.setFixedHeight(CONTROL_HEIGHT)


class ColumnLabel(QLabel):
    """A label of the panel's label column, its text against the right.

    As wide as the widest of `COLUMN_LABELS` in the font and padding it is
    drawn with, so every label of the column ends at one edge, and the menu
    and the values beside them start at one. Measured when laid out, once
    napari's style has set the font, not when built, before it has. No
    indent: napari's style gives a label a frame, and a framed label with
    none set keeps half an x clear of its right edge, which pushed the
    widest label's first letter out of its box.
    """

    def __init__(self, text: str = "") -> None:
        super().__init__(text)
        self.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.setIndent(0)

    def sizeHint(self) -> QSize:
        metrics, margins = self.fontMetrics(), self.contentsMargins()
        widest = max(metrics.horizontalAdvance(text) for text in COLUMN_LABELS)
        return QSize(widest + margins.left() + margins.right(), super().sizeHint().height())

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()


def form_layout(widget=None) -> QFormLayout:
    """A form on the panel's label column: each label against the column's
    right edge, `GAP` before its value, and `GAP` between rows. The values
    take the width there is, whatever their text -- on macOS they kept
    their own, so each row selected moved them -- but for a control of a
    fixed size, and the form starts at the left: macOS centred it."""
    form = QFormLayout(widget) if widget is not None else QFormLayout()
    form.setContentsMargins(0, 0, 0, 0)
    form.setVerticalSpacing(GAP)
    form.setHorizontalSpacing(GAP)
    form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
    form.setFormAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
    return form


class SteadyLabel(QLabel):
    """A label as tall as the longest of the texts it can show needs.

    Sized again whenever its width changes, so selecting another row changes
    its text and nothing else. Measured on a plain label with its font and
    margins: this one can be selected with the mouse, so Qt lays its text
    out in a text document, whose height for a width the macOS style gave
    as a line per word -- 66 px held for a value that takes 18.
    """

    def __init__(self, values) -> None:
        super().__init__()
        self.setWordWrap(True)
        self.setTextInteractionFlags(Qt.TextSelectableByMouse)
        #: Every text this value can show.
        self._values = values
        self._width = None

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.width() != self._width:
            self._width = self.width()
            self.setFixedHeight(self.needed())

    def needed(self) -> int:
        """The height the longest of its values takes at its width."""
        probe = QLabel()
        probe.setWordWrap(True)
        probe.setFont(self.font())
        margins = self.contentsMargins()
        inner = max(1, self.width() - margins.left() - margins.right())
        heights = []
        for text in self._values():
            probe.setText(text)
            heights.append(probe.heightForWidth(inner))
        tallest = max(heights, default=probe.sizeHint().height())
        return tallest + margins.top() + margins.bottom()




__all__ = [
    "COLUMN_LABELS",
    "DRIVER_LINE",
    "GAP",
    "GROUP_GAP",
    "MARGIN",
    "SOURCE",
    "ColumnLabel",
    "SteadyLabel",
    "fit_control",
    "form_layout",
]
