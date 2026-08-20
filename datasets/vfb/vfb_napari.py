#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import textwrap

import napari
import pandas as pd
from qtpy.QtCore import Qt
from qtpy.QtWidgets import (
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


def load_terms() -> pd.DataFrame:
    terms = pd.read_csv(SOURCE_DIR / "vfb_glomerulus_terms.csv").fillna("")
    terms = terms[terms["glomerulus"].astype(str).str.len() > 0]
    return terms.sort_values("glomerulus").reset_index(drop=True)


def term_text(row: pd.Series) -> str:
    parts = [
        str(row.get("glomerulus", "")),
        str(row.get("vfb_name", "")),
        str(row.get("fbbt_id", "")),
        "",
        str(row.get("definition", "")),
    ]
    synonyms = str(row.get("synonyms", ""))
    if synonyms:
        parts.extend(["", f"Synonyms: {synonyms}"])
    url = str(row.get("vfb_url", ""))
    if url:
        parts.extend(["", url])
    return "\n".join(part for part in parts if part is not None)


def load_atlas(viewer: napari.Viewer) -> QWidget:
    terms = load_terms()
    viewer.title = "lobemap - VFB"
    viewer.dims.ndisplay = 2

    title = QLabel("VFB term")
    title.setTextInteractionFlags(Qt.TextSelectableByMouse)

    details = QPlainTextEdit()
    details.setReadOnly(True)
    details.setMinimumHeight(240)

    def show_term(index: int) -> None:
        row = terms.iloc[index]
        title.setText(f"{row['glomerulus']}  {row['fbbt_id']}")
        details.setPlainText(
            textwrap.fill(term_text(row), width=88, replace_whitespace=False)
        )

    def open_selected_url() -> None:
        import webbrowser

        row = table.currentRow()
        if row < 0:
            return
        url = str(terms.iloc[row].get("vfb_url", ""))
        if url:
            webbrowser.open(url)

    table = QTableWidget(len(terms), 3)
    table.setHorizontalHeaderLabels(["glomerulus", "FBbt", "VFB name"])
    table.setSelectionBehavior(QTableWidget.SelectRows)
    table.setSelectionMode(QTableWidget.SingleSelection)
    table.verticalHeader().setVisible(False)
    table.setAlternatingRowColors(True)
    for row, term in terms.iterrows():
        for column, key in enumerate(("glomerulus", "fbbt_id", "vfb_name")):
            item = QTableWidgetItem(str(term.get(key, "")))
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            table.setItem(row, column, item)
    table.resizeColumnsToContents()
    table.horizontalHeader().setStretchLastSection(True)
    table.currentCellChanged.connect(lambda row, *_: show_term(row) if row >= 0 else None)

    open_button = QPushButton("Open VFB")
    open_button.clicked.connect(open_selected_url)

    panel = QWidget()
    layout = QVBoxLayout()
    layout.addWidget(QLabel("VFB terms"))
    layout.addWidget(table)
    layout.addWidget(open_button)
    layout.addWidget(title)
    layout.addWidget(details)
    panel.setLayout(layout)

    table.selectRow(0)
    show_term(0)
    return panel


def main() -> None:
    viewer = napari.Viewer(title="lobemap - VFB", ndisplay=2)
    panel = load_atlas(viewer)
    viewer.window.add_dock_widget(panel, area="right", name="VFB")
    napari.run()


if __name__ == "__main__":
    main()
