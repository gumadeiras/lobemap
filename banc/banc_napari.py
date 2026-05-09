#!/usr/bin/env python3
from __future__ import annotations

import json
import textwrap
import webbrowser
from pathlib import Path

import napari
import pandas as pd
from qtpy.QtCore import Qt
from qtpy.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QPlainTextEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


WORK_DIR = Path(__file__).resolve().parent
SOURCE_DIR = WORK_DIR / "data/source"


def load_resources() -> pd.DataFrame:
    resources = pd.read_csv(SOURCE_DIR / "banc_resources.csv").fillna("")
    return resources.sort_values(["type", "name"]).reset_index(drop=True)


def state_details(local_file: str) -> str:
    if not local_file:
        return ""
    path = SOURCE_DIR / local_file
    if not path.exists() or path.suffix != ".json":
        return ""
    state = json.loads(path.read_text(encoding="utf-8"))
    rows = [
        f"Neuroglancer title: {state.get('title', '')}",
        f"Layout: {state.get('layout', '')}",
        f"Position: {state.get('position', '')}",
        "",
        "Layers:",
    ]
    for layer in state.get("layers", []):
        name = layer.get("name", "")
        layer_type = layer.get("type", "")
        segments = len(layer.get("segments", []))
        if segments:
            rows.append(f"- {name} ({layer_type}, {segments} segments)")
        else:
            rows.append(f"- {name} ({layer_type})")
    return "\n".join(rows)


def resource_text(row: pd.Series) -> str:
    parts = [
        str(row.get("name", "")),
        str(row.get("type", "")),
        str(row.get("source", "")),
        "",
        str(row.get("description", "")),
        "",
        str(row.get("url", "")),
    ]
    details = state_details(str(row.get("local_file", "")))
    if details:
        parts.extend(["", details])
    return "\n".join(part for part in parts if part is not None)


def add_button(layout: QHBoxLayout, label: str, url: str) -> None:
    button = QPushButton(label)
    button.clicked.connect(lambda _checked=False: webbrowser.open(url))
    layout.addWidget(button)


def load_atlas(viewer: napari.Viewer) -> QWidget:
    resources = load_resources()
    viewer.title = "lobemap - BANC"
    viewer.dims.ndisplay = 2

    title = QLabel("BANC")
    title.setTextInteractionFlags(Qt.TextSelectableByMouse)

    details = QPlainTextEdit()
    details.setReadOnly(True)
    details.setMinimumHeight(300)

    def show_resource(index: int) -> None:
        row = resources.iloc[index]
        title.setText(f"{row['name']}  {row['type']}")
        details.setPlainText(
            textwrap.fill(resource_text(row), width=88, replace_whitespace=False)
        )

    def open_selected_url() -> None:
        row = table.currentRow()
        if row < 0:
            return
        url = str(resources.iloc[row].get("url", ""))
        if url:
            webbrowser.open(url)

    table = QTableWidget(len(resources), 3)
    table.setHorizontalHeaderLabels(["resource", "type", "source"])
    table.setSelectionBehavior(QTableWidget.SelectRows)
    table.setSelectionMode(QTableWidget.SingleSelection)
    table.verticalHeader().setVisible(False)
    table.setAlternatingRowColors(True)
    for row, resource in resources.iterrows():
        for column, key in enumerate(("name", "type", "source")):
            item = QTableWidgetItem(str(resource.get(key, "")))
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            table.setItem(row, column, item)
    table.resizeColumnsToContents()
    table.horizontalHeader().setStretchLastSection(True)
    table.currentCellChanged.connect(
        lambda row, *_: show_resource(row) if row >= 0 else None
    )

    button_row = QHBoxLayout()
    open_button = QPushButton("Open Selected")
    open_button.clicked.connect(open_selected_url)
    button_row.addWidget(open_button)
    add_button(button_row, "Codex", "https://codex.flywire.ai/banc")
    add_button(button_row, "Neuroglancer", "https://ng.banc.community/view")

    panel = QWidget()
    layout = QVBoxLayout()
    layout.addWidget(table)
    layout.addLayout(button_row)
    layout.addWidget(title)
    layout.addWidget(details)
    panel.setLayout(layout)

    table.selectRow(0)
    show_resource(0)
    return panel


def main() -> None:
    viewer = napari.Viewer(title="lobemap - BANC", ndisplay=2)
    panel = load_atlas(viewer)
    viewer.window.add_dock_widget(panel, area="right", name="BANC")
    napari.run()


if __name__ == "__main__":
    main()
