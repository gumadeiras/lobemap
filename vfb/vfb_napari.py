#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import textwrap

import napari
import numpy as np
import pandas as pd
from qtpy.QtCore import Qt
from qtpy.QtWidgets import (
    QComboBox,
    QLabel,
    QPushButton,
    QPlainTextEdit,
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
    names = terms["glomerulus"].astype(str).tolist()

    columns = 8
    spacing = 12.0
    positions = np.asarray(
        [
            ((index // columns) * spacing, (index % columns) * spacing)
            for index in range(len(names))
        ],
        dtype=float,
    )

    viewer.title = "lobemap - VFB"
    viewer.dims.ndisplay = 2
    points = viewer.add_points(
        positions,
        name="VFB glomerulus terms",
        size=1.0,
        face_color="#d8dee9",
        border_color="#2e3440",
        features=terms,
        text={
            "string": "{glomerulus}",
            "size": 10,
            "color": "white",
            "anchor": "center",
        },
    )
    viewer.camera.zoom = 1.5

    selector = QComboBox()
    for name in names:
        selector.addItem(name)

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
        points.selected_data = {index}
        viewer.dims.set_point(0, 0)
        viewer.camera.center = tuple(positions[index])

    def open_selected_url() -> None:
        import webbrowser

        url = str(terms.iloc[selector.currentIndex()].get("vfb_url", ""))
        if url:
            webbrowser.open(url)

    selector.currentIndexChanged.connect(show_term)
    open_button = QPushButton("Open VFB")
    open_button.clicked.connect(open_selected_url)

    panel = QWidget()
    layout = QVBoxLayout()
    layout.addWidget(QLabel("Glomerulus"))
    layout.addWidget(selector)
    layout.addWidget(open_button)
    layout.addWidget(title)
    layout.addWidget(details)
    panel.setLayout(layout)

    show_term(0)
    return panel


def main() -> None:
    viewer = napari.Viewer(title="lobemap - VFB", ndisplay=2)
    panel = load_atlas(viewer)
    viewer.window.add_dock_widget(panel, area="right", name="VFB")
    napari.run()


if __name__ == "__main__":
    main()
