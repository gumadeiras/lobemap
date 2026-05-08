from __future__ import annotations

from pathlib import Path
from typing import Callable

import pandas as pd
from qtpy.QtCore import Qt
from qtpy.QtWidgets import QTableWidget, QTableWidgetItem


ROOT = Path(__file__).resolve().parents[1]
_MASTER_METADATA: dict[str, dict[str, str]] | None = None


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


def set_table_checked(table: QTableWidget, checked: bool) -> None:
    table.blockSignals(True)
    try:
        for row in range(table.rowCount()):
            table.item(row, 0).setCheckState(Qt.Checked if checked else Qt.Unchecked)
    finally:
        table.blockSignals(False)
