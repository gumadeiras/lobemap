from __future__ import annotations

from pathlib import Path
from typing import Callable, Collection

import pandas as pd
from qtpy.QtCore import Qt
from qtpy.QtWidgets import QComboBox, QTableWidget, QTableWidgetItem


ROOT = Path(__file__).resolve().parents[1]
_MASTER_METADATA: dict[str, dict[str, str]] | None = None
_GLOMERULUS_LINE_PRESETS: dict[str, set[str]] | None = None
LINE_PRESET_COLUMNS = ("sensory_neuron_lines", "projection_neuron_lines")
INTERSECTION_LINE_PRESETS = (
    ("Orco-GAL4 & GH146-GAL4", ("Orco-GAL4", "GH146-GAL4")),
)


def normalize_sensilla(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    seen: list[str] = []
    seen_keys: set[str] = set()
    for part in str(value).split(";"):
        text = part.strip()
        key = text.casefold()
        if text and key not in seen_keys:
            seen.append(text)
            seen_keys.add(key)
    return "; ".join(seen)


def load_master_metadata() -> dict[str, dict[str, str]]:
    global _MASTER_METADATA
    if _MASTER_METADATA is not None:
        return _MASTER_METADATA
    path = ROOT / "reference-tables/glomerulus_ground_truth.csv"
    if not path.exists():
        _MASTER_METADATA = {}
        return _MASTER_METADATA
    table = pd.read_csv(path).fillna("")
    metadata: dict[str, dict[str, str]] = {}
    for row in table.to_dict("records"):
        name = str(row.get("canonical_glomerulus", ""))
        if not name:
            continue
        metadata[name] = {
            "receptor": str(row.get("receptor_consensus", "")),
            "sensillum": normalize_sensilla(row.get("sensillum_consensus", "")),
        }
    _MASTER_METADATA = metadata
    return _MASTER_METADATA


def load_glomerulus_line_presets() -> dict[str, set[str]]:
    global _GLOMERULUS_LINE_PRESETS
    if _GLOMERULUS_LINE_PRESETS is not None:
        return _GLOMERULUS_LINE_PRESETS
    path = ROOT / "reference-tables/glomerulus_ground_truth.csv"
    if not path.exists():
        _GLOMERULUS_LINE_PRESETS = {}
        return _GLOMERULUS_LINE_PRESETS
    table = pd.read_csv(path).fillna("")
    presets: dict[str, set[str]] = {}
    for column in LINE_PRESET_COLUMNS:
        for row in table.to_dict("records"):
            glomerulus = str(row.get("canonical_glomerulus", ""))
            if not glomerulus:
                continue
            for line in str(row.get(column, "")).split(";"):
                line = line.strip()
                if line:
                    presets.setdefault(line, set()).add(glomerulus)
    for label, line_names in INTERSECTION_LINE_PRESETS:
        line_sets = [presets.get(line_name, set()) for line_name in line_names]
        if all(line_sets):
            presets[label] = set.intersection(*line_sets)
    _GLOMERULUS_LINE_PRESETS = presets
    return _GLOMERULUS_LINE_PRESETS


def glomerulus_metadata(name: str, fallback: dict[str, str] | None = None) -> dict[str, str]:
    fallback = fallback or {}
    master = load_master_metadata().get(name, {})
    return {
        "receptor": master.get("receptor") or fallback.get("receptor", ""),
        "sensillum": normalize_sensilla(
            master.get("sensillum") or fallback.get("sensillum", "")
        ),
    }


def make_glomerulus_table(
    names: list[str],
    visible_names: set[str],
    metadata: dict[str, dict[str, str]],
    on_toggled: Callable[[str, bool], None],
) -> QTableWidget:
    table = QTableWidget(len(names), 3)
    table.setHorizontalHeaderLabels(["glomerulus", "receptor", "sensilla"])
    table.setSelectionBehavior(QTableWidget.SelectRows)
    table.setSelectionMode(QTableWidget.ExtendedSelection)
    table.verticalHeader().setVisible(False)
    table.setAlternatingRowColors(True)
    table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

    for row, name in enumerate(names):
        meta = glomerulus_metadata(name, metadata.get(name, {}))
        item = QTableWidgetItem(name)
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        item.setCheckState(Qt.Checked if name in visible_names else Qt.Unchecked)
        item.setData(Qt.UserRole, name)
        table.setItem(row, 0, item)
        for column, value in enumerate((meta["receptor"], meta["sensillum"]), start=1):
            detail = QTableWidgetItem(value)
            detail.setFlags(detail.flags() & ~Qt.ItemIsEditable)
            table.setItem(row, column, detail)

    table.resizeColumnsToContents()
    table.horizontalHeader().setStretchLastSection(True)
    table.resizeRowsToContents()
    table_height = (
        table.horizontalHeader().height()
        + sum(table.rowHeight(row) for row in range(table.rowCount()))
        + 6
    )
    table.setMinimumHeight(table_height)
    table.setMaximumHeight(table_height)

    def on_item_changed(item: QTableWidgetItem) -> None:
        if item.column() != 0:
            return
        name = str(item.data(Qt.UserRole))
        on_toggled(name, item.checkState() == Qt.Checked)

    table.itemChanged.connect(on_item_changed)
    return table


def make_glomerulus_preset_combo(
    available_names: Collection[str],
    visible_names: set[str],
    table: QTableWidget,
    on_applied: Callable[[], None] | None = None,
) -> QComboBox:
    combo = QComboBox()
    combo.addItem("Line preset...", ())
    available = set(available_names)
    for line, preset_names in load_glomerulus_line_presets().items():
        names = tuple(sorted(available.intersection(preset_names)))
        if names:
            combo.addItem(f"{line} ({len(names)})", names)

    def on_index_changed(index: int) -> None:
        if index <= 0:
            return
        apply_glomerulus_preset(
            set(combo.itemData(index) or ()),
            visible_names,
            table,
            on_applied,
        )

    combo.currentIndexChanged.connect(on_index_changed)
    return combo


def apply_glomerulus_preset(
    names: set[str],
    visible_names: set[str],
    table: QTableWidget,
    on_applied: Callable[[], None] | None = None,
) -> None:
    visible_names.clear()
    visible_names.update(names)
    set_table_checked_names(table, visible_names)
    if on_applied is not None:
        on_applied()


def set_table_checked(table: QTableWidget, checked: bool) -> None:
    checked_names = (
        {
            str(table.item(row, 0).data(Qt.UserRole))
            for row in range(table.rowCount())
        }
        if checked
        else set()
    )
    set_table_checked_names(table, checked_names)


def set_table_checked_names(table: QTableWidget, checked_names: set[str]) -> None:
    table.blockSignals(True)
    try:
        for row in range(table.rowCount()):
            name = str(table.item(row, 0).data(Qt.UserRole))
            table.item(row, 0).setCheckState(
                Qt.Checked if name in checked_names else Qt.Unchecked
            )
    finally:
        table.blockSignals(False)
