"""A table header with one checkbox for each checkbox column.

Each checkbox column of the panel's tables -- Show, Label, Fill -- has a
checkbox in its header, before its name, that stands for the whole column:
ticked when every listed row is ticked, half ticked when some are, clear
when none are. Its table sets that state (`set_state`) and decides what a
click does (`toggled`); clicking any other header sorts, as before.

The checkbox is the style's own item checkbox, drawn where and as large as
the table draws the boxes in its cells, so it stands right above them, with
the column's name after it. A section that cannot act is drawn disabled,
and a click on it does nothing.
"""

from __future__ import annotations

from qtpy.QtCore import QRect, QSize, Qt, Signal
from qtpy.QtGui import QPalette
from qtpy.QtWidgets import QHeaderView, QStyle, QStyleOptionHeader, QStyleOptionViewItem

_STATE_FLAG = {
    Qt.CheckState.Checked: QStyle.StateFlag.State_On,
    Qt.CheckState.PartiallyChecked: QStyle.StateFlag.State_NoChange,
    Qt.CheckState.Unchecked: QStyle.StateFlag.State_Off,
}


class CheckHeader(QHeaderView):
    """A horizontal header whose `columns` each carry a checkbox."""

    #: A checkbox section was clicked, and can act: its column.
    toggled = Signal(int)

    def __init__(self, columns, parent=None) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self._state = {column: Qt.CheckState.Unchecked for column in columns}
        self._enabled = dict.fromkeys(columns, True)
        #: The checkbox section the left button went down on, until it is up.
        self._pressed: int | None = None

    def state(self, column: int) -> Qt.CheckState:
        """What the checkbox of `column` shows."""
        return self._state[column]

    def is_enabled(self, column: int) -> bool:
        """Whether the checkbox of `column` can act."""
        return self._enabled[column]

    def set_state(self, column: int, state: Qt.CheckState, enabled: bool) -> None:
        if (self._state[column], self._enabled[column]) != (state, enabled):
            self._state[column], self._enabled[column] = state, enabled
            self.updateSection(column)

    # -- drawing ---------------------------------------------------------
    #
    # A checkbox section is drawn in three parts: the section as Qt draws
    # it, without its name; the checkbox, where and as large as the table
    # draws the boxes of its cells, so it stands right above them; and the
    # name after it, as the style writes a header's name.

    def initStyleOptionForIndex(self, option, index: int) -> None:
        super().initStyleOptionForIndex(option, index)
        if index in self._state:
            option.text = ""
            if not self._enabled[index]:
                option.state &= ~QStyle.StateFlag.State_Enabled

    def paintSection(self, painter, rect, index: int) -> None:
        super().paintSection(painter, rect, index)
        if index not in self._state:
            return
        view = self.parentWidget()
        box = self._item_option(index, rect)
        box.rect = view.style().subElementRect(
            QStyle.SubElement.SE_ItemViewItemCheckIndicator, box, view)
        view.style().drawPrimitive(QStyle.PrimitiveElement.PE_IndicatorItemViewItemCheck,
                                   box, painter, view)
        option = QStyleOptionHeader()
        self.initStyleOption(option)
        self.initStyleOptionForIndex(option, index)
        option.text = self._name(index)
        option.textAlignment = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        if not self._enabled[index]:
            # The style writes a name in the palette's current colors.
            option.palette.setCurrentColorGroup(QPalette.ColorGroup.Disabled)
        option.rect = rect.adjusted(box.rect.right() + 1 - rect.left() + self._spacing(), 0, 0, 0)
        self.style().drawControl(QStyle.ControlElement.CE_HeaderLabel, option, painter, self)

    def sectionSizeFromContents(self, index: int) -> QSize:
        """The checkbox as far from the left as in a cell, the name after it,
        and as much room again on the right. Never room for a sort arrow,
        which a checkbox column does not show."""
        size = super().sectionSizeFromContents(index)
        if index not in self._state:
            return size
        view = self.parentWidget()
        box = self._item_option(index, QRect(0, 0, size.width(), size.height()))
        box = view.style().subElementRect(QStyle.SubElement.SE_ItemViewItemCheckIndicator,
                                          box, view)
        name = self.fontMetrics().horizontalAdvance(self._name(index))
        return QSize(2 * box.left() + box.width() + self._spacing() + name, size.height())

    def _name(self, index: int) -> str:
        return str(self.model().headerData(index, Qt.Orientation.Horizontal) or "")

    def _spacing(self) -> int:
        """Between the checkbox and the name: as in a checkbox of the style."""
        return self.style().pixelMetric(QStyle.PixelMetric.PM_CheckBoxLabelSpacing, None, self)

    def _item_option(self, index: int, rect: QRect) -> QStyleOptionViewItem:
        """A cell of this column holding a checkbox in the column's state."""
        view = self.parentWidget()
        option = QStyleOptionViewItem()
        option.initFrom(view)
        option.rect = rect
        option.features |= QStyleOptionViewItem.ViewItemFeature.HasCheckIndicator
        option.checkState = self._state[index]
        option.state = (option.state & ~(QStyle.StateFlag.State_On | QStyle.StateFlag.State_Off
                                         | QStyle.StateFlag.State_NoChange)
                        | _STATE_FLAG[option.checkState])
        if not self._enabled[index]:
            option.state &= ~QStyle.StateFlag.State_Enabled
        return option

    # -- clicks ----------------------------------------------------------
    #
    # A checkbox section takes the left button itself: pressed and released
    # over the same section, it toggles. Qt's own handling would sort by
    # the column instead, which for a column of checkboxes means nothing.

    def _checkbox_at(self, event) -> int | None:
        if event.button() != Qt.MouseButton.LeftButton:
            return None
        index = self.logicalIndexAt(event.position().toPoint())
        return index if index in self._state else None

    def mousePressEvent(self, event) -> None:
        column = self._checkbox_at(event)
        if column is None:
            super().mousePressEvent(event)
            return
        self._pressed = column
        event.accept()

    def mouseDoubleClickEvent(self, event) -> None:
        """A quick second click is a click of its own, not a double click."""
        if self._checkbox_at(event) is None:
            super().mouseDoubleClickEvent(event)
        else:
            self.mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._pressed is None:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        pressed, self._pressed = self._pressed, None
        if pressed is None:
            super().mouseReleaseEvent(event)
            return
        event.accept()
        if self._checkbox_at(event) == pressed and self._enabled[pressed]:
            self.toggled.emit(pressed)


__all__ = ["CheckHeader"]
