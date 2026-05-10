#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

import napari
import numpy as np
import pandas as pd
from napari.utils.transforms import Affine
from qtpy.QtCore import Qt
from qtpy.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


WORK_DIR = Path(__file__).resolve().parent
ROOT = WORK_DIR.parent
sys.path.insert(0, str(WORK_DIR))
sys.path.insert(0, str(ROOT / "scripts"))

from benton_2025_data import (  # noqa: E402
    AtlasVolume,
    label_name,
    label_short_name,
    label_slice_centroids,
    load_metadata,
    load_volume,
)
from ui_helpers import make_glomerulus_table, set_table_checked  # noqa: E402


def rotation_matrix(axis: int, degrees: float) -> np.ndarray:
    radians = np.deg2rad(degrees)
    sin = np.sin(radians)
    cos = np.cos(radians)
    matrix = np.eye(3)
    if axis == 0:
        matrix[1:, 1:] = ((cos, -sin), (sin, cos))
    elif axis == 1:
        matrix[np.ix_([0, 2], [0, 2])] = ((cos, sin), (-sin, cos))
    elif axis == 2:
        matrix[:2, :2] = ((cos, -sin), (sin, cos))
    else:
        raise ValueError(f"invalid axis {axis}")
    return matrix


def affine_for_rotation(
    shape: tuple[int, int, int],
    rotations: dict[int, float],
    mirror_vertical: bool = False,
    mirror_horizontal: bool = False,
) -> Affine:
    matrix = (
        rotation_matrix(0, rotations[0])
        @ rotation_matrix(1, rotations[1])
        @ rotation_matrix(2, rotations[2])
    )
    if mirror_vertical:
        matrix = np.diag((1.0, -1.0, 1.0)) @ matrix
    if mirror_horizontal:
        matrix = np.diag((1.0, 1.0, -1.0)) @ matrix
    center = (np.asarray(shape, dtype=np.float64) - 1.0) / 2.0
    translate = center - matrix @ center
    return Affine(linear_matrix=matrix, translate=translate, ndim=3)


def point_features(anchor_ids: list[int], atlas: AtlasVolume) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "label_id": anchor_ids,
            "name": [label_name(i, atlas) for i in anchor_ids],
            "short_name": [label_short_name(i, atlas) for i in anchor_ids],
            "receptor": [atlas.receptors.get(i, "") for i in anchor_ids],
            "sensillum": [atlas.sensilla.get(i, "") for i in anchor_ids],
        }
    )


def label_features(source_labels: np.ndarray, atlas: AtlasVolume) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "label_id": int(i),
                "name": label_name(int(i), atlas),
                "short_name": label_short_name(int(i), atlas),
                "receptor": atlas.receptors.get(int(i), ""),
                "sensillum": atlas.sensilla.get(int(i), ""),
            }
            for i in np.unique(source_labels)
        ]
    )


def load_atlas(viewer: napari.Viewer) -> QWidget:
    viewer.title = "lobemap - Benton 2025"
    viewer.dims.ndisplay = 2

    atlas = load_volume()
    source_labels = atlas.labels
    unique_ids = np.asarray(sorted(i for i in np.unique(source_labels) if i != 0))
    visible_glomeruli = set(atlas.glomeruli.values())
    axis_orders = {
        "Dorsal-Ventral": (1, 0, 2),
        "Anterior-Posterior": (0, 1, 2),
        "Lateral-Medial": (2, 0, 1),
    }
    reverse_slice_axis = {"Dorsal-Ventral": True}
    current_axis_order = axis_orders["Dorsal-Ventral"]
    current_reverse_slice_axis = reverse_slice_axis["Dorsal-Ventral"]
    rotation_degrees = {0: 0.0, 1: 0.0, 2: 0.0}
    mirror_vertical = True
    mirror_horizontal = True
    centroid_cache: dict[tuple[int, int, int, bool], tuple[np.ndarray, np.ndarray]] = {}

    def visible_ids() -> set[int]:
        return {
            label_id
            for label_id, glomerulus in atlas.glomeruli.items()
            if glomerulus in visible_glomeruli
        }

    def filtered_labels(labels: np.ndarray) -> np.ndarray:
        lut = np.zeros(int(source_labels.max()) + 1, dtype=np.uint16)
        for label_id in visible_ids():
            lut[label_id] = label_id
        return lut[labels]

    def centroids_for_axis(
        axis_order: tuple[int, int, int],
        reverse_axis: bool,
    ) -> tuple[np.ndarray, np.ndarray]:
        cache_key = (*axis_order, reverse_axis)
        cached = centroid_cache.get(cache_key)
        if cached is None:
            labels = source_labels.transpose(axis_order)
            if reverse_axis:
                labels = np.flip(labels, axis=0)
            cached = label_slice_centroids(
                labels, unique_ids
            )
            centroid_cache[cache_key] = cached
        return cached

    def current_scene_data() -> tuple[np.ndarray, np.ndarray, list[int]]:
        labels = source_labels.transpose(current_axis_order)
        if current_reverse_slice_axis:
            labels = np.flip(labels, axis=0)
        points, point_ids = centroids_for_axis(
            current_axis_order, current_reverse_slice_axis
        )
        visible_mask = np.isin(point_ids, list(visible_ids()))
        return (
            filtered_labels(labels),
            points[visible_mask],
            point_ids[visible_mask].astype(int).tolist(),
        )

    labels, anchor_points, anchor_ids = current_scene_data()
    labels_layer = viewer.add_labels(
        labels,
        name="glomerulus labels",
        opacity=0.62,
        features=label_features(source_labels, atlas),
    )
    labels_layer.color = atlas.colors

    points_layer = viewer.add_points(
        anchor_points,
        name="slice name anchors",
        size=0.0,
        features=point_features(anchor_ids, atlas),
        text={
            "string": "{short_name}",
            "size": 9,
            "color": "white",
            "anchor": "center",
        },
        face_color="transparent",
        border_color="transparent",
        border_width=0.0,
        out_of_slice_display=False,
    )

    hover_label = QLabel("Hover over a label")
    hover_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
    table = None

    def refresh_layers() -> None:
        labels, anchor_points, anchor_ids = current_scene_data()
        labels_layer.data = labels
        points_layer.data = anchor_points
        points_layer.features = point_features(anchor_ids, atlas)
        hover_label.setText(f"{len(visible_glomeruli)} glomeruli visible")

    def apply_rotation_transform() -> None:
        affine = affine_for_rotation(
            labels_layer.data.shape,
            rotation_degrees,
            mirror_vertical,
            mirror_horizontal,
        )
        labels_layer.affine = affine
        points_layer.affine = affine

    def set_checked_without_signals(checked: bool) -> None:
        if table is not None:
            set_table_checked(table, checked)

    def show_all() -> None:
        visible_glomeruli.clear()
        visible_glomeruli.update(atlas.glomeruli.values())
        set_checked_without_signals(True)
        refresh_layers()

    def show_none() -> None:
        visible_glomeruli.clear()
        set_checked_without_signals(False)
        refresh_layers()

    def on_glomerulus_toggled(name: str, checked: bool) -> None:
        if checked:
            visible_glomeruli.add(name)
        else:
            visible_glomeruli.discard(name)
        refresh_layers()

    axis_combo = QComboBox()
    for name in axis_orders:
        axis_combo.addItem(name)
    axis_combo.setCurrentText("Dorsal-Ventral")
    axis_combo.currentIndexChanged.connect(
        lambda index: on_axis_changed(axis_combo.itemText(index))
    )

    def on_axis_changed(name: str) -> None:
        nonlocal current_axis_order, current_reverse_slice_axis
        current_axis_order = axis_orders[name]
        current_reverse_slice_axis = reverse_slice_axis.get(name, False)
        refresh_layers()
        apply_rotation_transform()

    def on_rotation_changed(axis: int, value: float) -> None:
        rotation_degrees[axis] = value
        apply_rotation_transform()

    def on_mirror_changed(axis: str, checked: bool) -> None:
        nonlocal mirror_vertical, mirror_horizontal
        if axis == "vertical":
            mirror_vertical = checked
        else:
            mirror_horizontal = checked
        apply_rotation_transform()

    rotation_spinboxes: list[QDoubleSpinBox] = []
    for axis in (0, 1, 2):
        spinbox = QDoubleSpinBox()
        spinbox.setRange(-180.0, 180.0)
        spinbox.setSingleStep(1.0)
        spinbox.setDecimals(1)
        spinbox.setSuffix(" deg")
        spinbox.setWrapping(True)
        spinbox.valueChanged.connect(
            lambda value, axis=axis: on_rotation_changed(axis, value)
        )
        rotation_spinboxes.append(spinbox)

    show_all_button = QPushButton("Show all")
    show_none_button = QPushButton("Show none")
    show_all_button.clicked.connect(show_all)
    show_none_button.clicked.connect(show_none)

    table = make_glomerulus_table(
        sorted(set(atlas.glomeruli.values())),
        visible_glomeruli,
        load_metadata(atlas),
        on_glomerulus_toggled,
    )

    panel = QWidget()
    layout = QVBoxLayout()
    layout.addWidget(QLabel("View"))
    layout.addWidget(axis_combo)
    layout.addWidget(QLabel("Rotation around displayed axes"))
    for label, spinbox in zip(
        ("Z/slice", "Y/vertical", "X/horizontal"), rotation_spinboxes
    ):
        row = QHBoxLayout()
        row.addWidget(QLabel(label))
        row.addWidget(spinbox)
        layout.addLayout(row)
    mirror_vertical_checkbox = QCheckBox("Mirror vertical")
    mirror_horizontal_checkbox = QCheckBox("Mirror horizontal")
    mirror_vertical_checkbox.setChecked(mirror_vertical)
    mirror_horizontal_checkbox.setChecked(mirror_horizontal)
    mirror_vertical_checkbox.toggled.connect(
        lambda checked: on_mirror_changed("vertical", checked)
    )
    mirror_horizontal_checkbox.toggled.connect(
        lambda checked: on_mirror_changed("horizontal", checked)
    )
    layout.addWidget(mirror_vertical_checkbox)
    layout.addWidget(mirror_horizontal_checkbox)
    buttons = QHBoxLayout()
    buttons.addWidget(show_all_button)
    buttons.addWidget(show_none_button)
    layout.addLayout(buttons)
    layout.addWidget(table)
    layout.addWidget(hover_label)
    panel.setLayout(layout)

    @labels_layer.mouse_move_callbacks.append
    def show_hover_name(layer, event) -> None:  # type: ignore[no-untyped-def]
        try:
            value = layer.get_value(event.position, world=True)
        except Exception:
            value = None
        if value is None:
            return
        if isinstance(value, tuple):
            value = value[0]
        label_id = int(value)
        parts = [f"{label_id}: {label_name(label_id, atlas)}"]
        if atlas.receptors.get(label_id):
            parts.append(atlas.receptors[label_id])
        if atlas.sensilla.get(label_id):
            parts.append(atlas.sensilla[label_id])
        text = " | ".join(parts)
        viewer.status = text
        hover_label.setText(text)

    refresh_layers()
    apply_rotation_transform()
    return panel


def main() -> None:
    viewer = napari.Viewer(title="lobemap - Benton 2025", ndisplay=2)
    panel = load_atlas(viewer)
    viewer.window.add_dock_widget(panel, area="right", name="Benton 2025")
    napari.run()


if __name__ == "__main__":
    main()
