#!/usr/bin/env python3
from __future__ import annotations

import hashlib
from pathlib import Path

import napari
import numpy as np
import pandas as pd
from qtpy.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


WORK_DIR = Path(__file__).resolve().parent
SOURCE_DIR = WORK_DIR / "data/source"


def stable_color(name: str) -> tuple[float, float, float, float]:
    seed = int.from_bytes(hashlib.sha256(name.encode("utf-8")).digest()[:8], "little")
    rgb = np.random.default_rng(seed).random(3)
    return (float(rgb[0]), float(rgb[1]), float(rgb[2]), 0.45)


def transformed(points: np.ndarray, view_name: str, bounds: tuple[float, float, float, float]) -> np.ndarray:
    y_min, y_max, x_min, x_max = bounds
    y = points[:, 0]
    x = points[:, 1]
    if view_name == "Left-right mirror":
        return np.column_stack((y, x_min + x_max - x))
    if view_name == "Up-down mirror":
        return np.column_stack((y_min + y_max - y, x))
    if view_name == "Rotate 90 deg":
        y_center = (y_min + y_max) / 2
        x_center = (x_min + x_max) / 2
        return np.column_stack((y_center + (x - x_center), x_center - (y - y_center)))
    if view_name == "Rotate 180 deg":
        return np.column_stack((y_min + y_max - y, x_min + x_max - x))
    return points.copy()


def load_metadata() -> dict[str, dict[str, str]]:
    metadata: dict[str, dict[str, str]] = {}
    mappings = pd.read_csv(SOURCE_DIR / "door_mappings.csv").fillna("")
    for row in mappings.to_dict("records"):
        glomerulus = str(row.get("glomerulus", ""))
        if not glomerulus:
            continue
        receptor = str(row.get("Ors", "") or row.get("receptor", ""))
        metadata[glomerulus] = {
            "receptor": receptor,
            "sensillum": str(row.get("sensillum", "")),
            "osn": str(row.get("OSN", "")),
            "co_receptor": str(row.get("co.receptor", "")),
        }
    return metadata


def load_atlas(viewer: napari.Viewer) -> QWidget:
    viewer.title = "lobemap - DoOR 2D"
    glomeruli = pd.read_csv(SOURCE_DIR / "door_al_map_glomeruli.csv")
    labels = pd.read_csv(SOURCE_DIR / "door_al_map_labels.csv")
    metadata = load_metadata()

    names = sorted(glomeruli["glomerulus"].unique())
    visible_names = set(names)
    polygon_by_name = {
        str(name): group[["y", "x"]].to_numpy(dtype=float)
        for name, group in glomeruli.groupby("glomerulus", sort=True)
    }
    label_by_name = {
        str(row["glomerulus"]): np.asarray([[float(row["y"]), float(row["x"])]])
        for row in labels.to_dict("records")
    }
    all_points = glomeruli[["y", "x"]].to_numpy(dtype=float)
    bounds = (
        float(all_points[:, 0].min()),
        float(all_points[:, 0].max()),
        float(all_points[:, 1].min()),
        float(all_points[:, 1].max()),
    )
    current_view = "Published map"
    initial_features = pd.DataFrame(
        {
            "name": names,
            "receptor": [metadata.get(name, {}).get("receptor", "") for name in names],
            "sensillum": [metadata.get(name, {}).get("sensillum", "") for name in names],
        }
    )

    shapes = viewer.add_shapes(
        [polygon_by_name[name] for name in names],
        shape_type="polygon",
        name="glomeruli",
        edge_color=(1.0, 1.0, 1.0, 0.55),
        edge_width=0.35,
        face_color=[stable_color(name) for name in names],
        opacity=0.75,
        features=initial_features,
    )

    points = viewer.add_points(
        np.empty((0, 2), dtype=float),
        name="glomerulus names",
        size=0.0,
        face_color="transparent",
        border_color="transparent",
        border_width=0.0,
        features=pd.DataFrame({"name": []}),
        text={
            "string": "{name}",
            "size": 10,
            "color": "white",
            "anchor": "center",
        },
    )
    viewer.dims.ndisplay = 2
    viewer.camera.angles = (0, 0, 0)

    checkbox_by_name: dict[str, QCheckBox] = {}

    def visible_ordered_names() -> list[str]:
        return [name for name in names if name in visible_names]

    def refresh_layers() -> None:
        shown = visible_ordered_names()
        shapes.data = [
            transformed(polygon_by_name[name], current_view, bounds) for name in shown
        ]
        shapes.features = pd.DataFrame(
            {
                "name": shown,
                "receptor": [metadata.get(name, {}).get("receptor", "") for name in shown],
                "sensillum": [
                    metadata.get(name, {}).get("sensillum", "") for name in shown
                ],
            }
        )
        shapes.face_color = [stable_color(name) for name in shown]

        label_names = [name for name in shown if name in label_by_name]
        if label_names:
            points.data = np.concatenate(
                [transformed(label_by_name[name], current_view, bounds) for name in label_names]
            )
        else:
            points.data = np.empty((0, 2), dtype=float)
        points.features = pd.DataFrame({"name": label_names})

    def set_checked_without_signals(checked: bool) -> None:
        for checkbox in checkbox_by_name.values():
            checkbox.blockSignals(True)
            checkbox.setChecked(checked)
            checkbox.blockSignals(False)

    def show_all() -> None:
        visible_names.clear()
        visible_names.update(names)
        set_checked_without_signals(True)
        refresh_layers()

    def show_none() -> None:
        visible_names.clear()
        set_checked_without_signals(False)
        refresh_layers()

    def on_glomerulus_toggled(name: str, checked: bool) -> None:
        if checked:
            visible_names.add(name)
        else:
            visible_names.discard(name)
        refresh_layers()

    view_combo = QComboBox()
    for view_name in (
        "Published map",
        "Left-right mirror",
        "Up-down mirror",
        "Rotate 90 deg",
        "Rotate 180 deg",
    ):
        view_combo.addItem(view_name)

    def on_view_changed(index: int) -> None:
        nonlocal current_view
        current_view = view_combo.itemText(index)
        refresh_layers()

    view_combo.currentIndexChanged.connect(on_view_changed)

    show_all_button = QPushButton("All")
    show_none_button = QPushButton("None")
    show_all_button.clicked.connect(show_all)
    show_none_button.clicked.connect(show_none)

    scroll_contents = QWidget()
    scroll_layout = QVBoxLayout()
    scroll_layout.setContentsMargins(0, 0, 0, 0)
    scroll_layout.setSpacing(1)
    for name in names:
        meta = metadata.get(name, {})
        receptor = meta.get("receptor", "")
        label = f"{name}  {receptor}" if receptor and receptor != "?" else name
        checkbox = QCheckBox(label)
        checkbox.setChecked(True)
        checkbox.toggled.connect(
            lambda checked, name=name: on_glomerulus_toggled(name, checked)
        )
        checkbox_by_name[name] = checkbox
        scroll_layout.addWidget(checkbox)
    scroll_layout.addStretch()
    scroll_contents.setLayout(scroll_layout)

    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setWidget(scroll_contents)

    panel = QWidget()
    layout = QVBoxLayout()
    layout.setContentsMargins(4, 4, 4, 4)
    layout.setSpacing(4)
    layout.addWidget(QLabel("View"))
    layout.addWidget(view_combo)
    buttons = QHBoxLayout()
    buttons.setContentsMargins(0, 0, 0, 0)
    buttons.setSpacing(4)
    buttons.addWidget(show_all_button)
    buttons.addWidget(show_none_button)
    layout.addLayout(buttons)
    layout.addWidget(QLabel("Glomeruli"))
    layout.addWidget(scroll)
    panel.setLayout(layout)

    refresh_layers()

    return panel


def main() -> None:
    viewer = napari.Viewer(title="lobemap - DoOR 2D", ndisplay=2)
    panel = load_atlas(viewer)
    viewer.window.add_dock_widget(panel, area="right", name="DoOR 2D")
    napari.run()


if __name__ == "__main__":
    main()
