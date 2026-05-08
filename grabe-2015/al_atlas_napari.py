#!/usr/bin/env python3
from __future__ import annotations

import csv
import re
import warnings
from dataclasses import dataclass
from pathlib import Path

import napari
import numpy as np
import pandas as pd
import tifffile as tf
from napari.utils.transforms import Affine
from qtpy.QtCore import Qt
from qtpy.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


WORK_DIR = Path(__file__).resolve().parent
DATA_DIR = WORK_DIR / "data"
SOURCE_DIR = DATA_DIR / "source"
DERIVED_DIR = DATA_DIR / "derived"

GRAYSCALE_TIF = SOURCE_DIR / "invivoALstack.tif"
LABEL_TIF = SOURCE_DIR / "Merged_2-101221a-labels_only_sure_ones_Sensillarcolors.tif"
AMIRA_LABELS = SOURCE_DIR / "Merged_2-101221a-labels_only_sure_ones_Sensillarcolors.am"
MATERIALS_CSV = DERIVED_DIR / "al_atlas_materials.csv"

warnings.filterwarnings(
    "ignore",
    message=(
        "Non-orthogonal slicing is being requested, but is not fully supported.*"
    ),
    category=UserWarning,
    module=r"napari\.layers\.utils\._slice_input",
)


@dataclass(frozen=True)
class Material:
    label_id: int
    name: str
    color: tuple[float, float, float]

    @property
    def short_name(self) -> str:
        name = self.name
        if name == "Exterior":
            return name
        return name.split("_", 1)[0]

    @property
    def voxel_value(self) -> int:
        return self.label_id - 1


def parse_amira_materials(path: Path) -> dict[int, Material]:
    data = path.read_bytes()
    header = data.split(b"\n@1", 1)[0].decode("latin-1", errors="ignore")
    id_pattern = re.compile(r"\bId\s+(?P<id>\d+)")
    color_pattern = re.compile(
        r"\bColor\s+"
        r"(?P<r>[0-9.]+)\s+"
        r"(?P<g>[0-9.]+)\s+"
        r"(?P<b>[0-9.]+)"
    )

    materials: dict[int, Material] = {}
    in_materials = False
    current_name: str | None = None
    current_body: list[str] = []

    for line in header.splitlines():
        stripped = line.strip()
        if stripped == "Materials {":
            in_materials = True
            continue
        if not in_materials:
            continue

        if current_name is None:
            if stripped == "}":
                break
            if stripped.endswith("{"):
                current_name = stripped[:-1].strip()
                current_body = []
            continue

        if stripped == "}":
            body = "\n".join(current_body)
            id_match = id_pattern.search(body)
            color_match = color_pattern.search(body)
            if id_match:
                label_id = int(id_match.group("id"))
                if color_match:
                    color = (
                        float(color_match.group("r")),
                        float(color_match.group("g")),
                        float(color_match.group("b")),
                    )
                else:
                    color = (1.0, 1.0, 1.0)
                materials[label_id] = Material(label_id, current_name, color)
            current_name = None
            current_body = []
            continue

        current_body.append(stripped)

    return materials


def write_materials_csv(materials: dict[int, Material]) -> None:
    MATERIALS_CSV.parent.mkdir(parents=True, exist_ok=True)
    with MATERIALS_CSV.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["voxel_value", "amira_id", "name", "short_name", "r", "g", "b"])
        for material in sorted(materials.values(), key=lambda m: m.label_id):
            writer.writerow(
                [
                    material.voxel_value,
                    material.label_id,
                    material.name,
                    material.short_name,
                    *material.color,
                ]
            )


def label_slice_centroids(
    labels: np.ndarray, ids: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    valid_ids = {int(i) for i in ids if i != 0}
    centroid_ids: list[int] = []
    centroids: list[tuple[float, float, float]] = []
    for z in range(labels.shape[0]):
        ys, xs = np.nonzero(labels[z])
        if len(ys) == 0:
            continue
        values = labels[z, ys, xs].astype(np.int64)
        max_id = int(values.max())
        count = np.bincount(values, minlength=max_id + 1)
        y_sum = np.bincount(values, weights=ys, minlength=max_id + 1)
        x_sum = np.bincount(values, weights=xs, minlength=max_id + 1)

        for label_id in np.nonzero(count)[0]:
            if label_id == 0:
                continue
            label_id = int(label_id)
            if label_id not in valid_ids:
                continue
            n = int(count[label_id])
            centroids.append((float(z), y_sum[label_id] / n, x_sum[label_id] / n))
            centroid_ids.append(label_id)

    if not centroids:
        return np.empty((0, 3), dtype=float), np.empty((0,), dtype=np.uint16)
    return np.asarray(centroids, dtype=float), np.asarray(centroid_ids, dtype=np.uint16)


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


def affine_for_rotation(shape: tuple[int, int, int], rotations: dict[int, float]) -> Affine:
    matrix = (
        rotation_matrix(0, rotations[0])
        @ rotation_matrix(1, rotations[1])
        @ rotation_matrix(2, rotations[2])
    )
    center = (np.asarray(shape, dtype=np.float64) - 1.0) / 2.0
    translate = center - matrix @ center
    return Affine(linear_matrix=matrix, translate=translate, ndim=3)


def label_name(label_id: int, materials: dict[int, Material]) -> str:
    material = materials.get(label_id + 1)
    if material is None:
        return f"unknown voxel {label_id}"
    return material.name


def label_short_name(label_id: int, materials: dict[int, Material]) -> str:
    material = materials.get(label_id + 1)
    if material is None:
        return f"?{label_id}"
    return material.short_name


def group_ids_by_short_name(
    labels: np.ndarray, materials: dict[int, Material]
) -> dict[str, list[int]]:
    present_ids = {int(i) for i in np.unique(labels) if i != 0}
    groups: dict[str, list[int]] = {}
    for label_id in sorted(present_ids):
        groups.setdefault(label_short_name(label_id, materials), []).append(label_id)
    return groups


def validate_material_mapping(labels: np.ndarray, materials: dict[int, Material]) -> None:
    missing = [int(i) for i in np.unique(labels) if int(i) + 1 not in materials]
    if missing:
        raise ValueError(f"Missing Amira material names for voxel values: {missing}")


def load_atlas(viewer: napari.Viewer) -> QWidget:
    source_image = tf.imread(GRAYSCALE_TIF)
    source_labels = tf.imread(LABEL_TIF).astype(np.uint16, copy=False)
    materials = parse_amira_materials(AMIRA_LABELS)
    validate_material_mapping(source_labels, materials)
    write_materials_csv(materials)

    unique_ids = np.unique(source_labels)
    features = pd.DataFrame(
        [
            {
                "label_id": int(i),
                "name": label_name(int(i), materials),
                "short_name": label_short_name(int(i), materials),
            }
            for i in unique_ids
        ]
    )
    groups = group_ids_by_short_name(source_labels, materials)
    visible_group_names = set(groups)
    axis_orders = {
        "Dorsal-Ventral": (0, 1, 2),
        "Anterior-Posterior": (1, 0, 2),
        "Lateral-Medial": (2, 0, 1),
    }
    current_axis_order = axis_orders["Dorsal-Ventral"]
    rotation_degrees = {0: 0.0, 1: 0.0, 2: 0.0}
    centroid_cache: dict[tuple[int, int, int], tuple[np.ndarray, np.ndarray]] = {}

    def filtered_labels(labels: np.ndarray) -> np.ndarray:
        lut = np.zeros(int(source_labels.max()) + 1, dtype=np.uint16)
        visible_ids = set().union(
            *(set(groups[name]) for name in visible_group_names)
        ) if visible_group_names else set()
        for label_id in visible_ids:
            lut[label_id] = label_id
        return lut[labels]

    def centroids_for_axis(
        axis_order: tuple[int, int, int],
    ) -> tuple[np.ndarray, np.ndarray]:
        cached = centroid_cache.get(axis_order)
        if cached is None:
            cached = label_slice_centroids(
                source_labels.transpose(axis_order), unique_ids
            )
            centroid_cache[axis_order] = cached
        return cached

    def current_scene_data() -> tuple[np.ndarray, np.ndarray, np.ndarray, list[int]]:
        image = source_image.transpose(current_axis_order)
        labels = source_labels.transpose(current_axis_order)
        points, point_ids = centroids_for_axis(current_axis_order)
        visible_ids = set().union(
            *(set(groups[name]) for name in visible_group_names)
        ) if visible_group_names else set()
        visible_mask = np.isin(point_ids, list(visible_ids))
        return (
            image,
            filtered_labels(labels),
            points[visible_mask],
            point_ids[visible_mask].astype(int).tolist(),
        )

    image, labels, anchor_points, anchor_ids = current_scene_data()

    viewer.title = "lobemap - Grabe 2015"
    viewer.dims.ndisplay = 2
    image_layer = viewer.add_image(
        image,
        name="invivoALstack",
        colormap="gray",
        contrast_limits=(0, 255),
    )

    labels_layer = viewer.add_labels(
        labels,
        name="glomerulus labels",
        opacity=0.55,
        features=features,
    )

    points_layer = viewer.add_points(
        anchor_points,
        name="slice name anchors",
        size=0.0,
        features=pd.DataFrame(
            {
                "label_id": anchor_ids,
                "name": [label_name(i, materials) for i in anchor_ids],
                "short_name": [label_short_name(i, materials) for i in anchor_ids],
            }
        ),
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

    checkbox_by_group: dict[str, QCheckBox] = {}

    def refresh_layers() -> None:
        image, labels, anchor_points, anchor_ids = current_scene_data()
        image_layer.data = image
        labels_layer.data = labels
        points_layer.data = anchor_points
        points_layer.features = pd.DataFrame(
            {
                "label_id": anchor_ids,
                "name": [label_name(i, materials) for i in anchor_ids],
                "short_name": [label_short_name(i, materials) for i in anchor_ids],
            }
        )
        hover_label.setText(f"{len(visible_group_names)} glomeruli visible")

    def apply_rotation_transform() -> None:
        affine = affine_for_rotation(image_layer.data.shape, rotation_degrees)
        image_layer.affine = affine
        labels_layer.affine = affine
        points_layer.affine = affine

    def set_checked_without_signals(checked: bool) -> None:
        for checkbox in checkbox_by_group.values():
            checkbox.blockSignals(True)
            checkbox.setChecked(checked)
            checkbox.blockSignals(False)

    def show_all() -> None:
        visible_group_names.clear()
        visible_group_names.update(groups)
        set_checked_without_signals(True)
        refresh_layers()

    def show_none() -> None:
        visible_group_names.clear()
        set_checked_without_signals(False)
        refresh_layers()

    def on_glomerulus_toggled(group_name: str, checked: bool) -> None:
        if checked:
            visible_group_names.add(group_name)
        else:
            visible_group_names.discard(group_name)
        refresh_layers()

    axis_combo = QComboBox()
    for name in axis_orders:
        axis_combo.addItem(name)

    def on_axis_changed(index: int) -> None:
        nonlocal current_axis_order
        current_axis_order = axis_orders[axis_combo.itemText(index)]
        refresh_layers()
        apply_rotation_transform()

    def on_rotation_changed(axis: int, value: float) -> None:
        rotation_degrees[axis] = value
        apply_rotation_transform()

    axis_combo.currentIndexChanged.connect(on_axis_changed)

    rotation_spinboxes: list[QDoubleSpinBox] = []
    for axis, label in ((0, "Z/slice"), (1, "Y/vertical"), (2, "X/horizontal")):
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

    scroll_contents = QWidget()
    scroll_layout = QVBoxLayout()
    scroll_layout.setContentsMargins(0, 0, 0, 0)
    for group_name in sorted(groups):
        group_label_ids = groups[group_name]
        full_names = [label_name(i, materials) for i in group_label_ids]
        suffix = f" ({len(group_label_ids)})" if len(group_label_ids) > 1 else ""
        checkbox = QCheckBox(f"{group_name}{suffix}")
        checkbox.setToolTip("\n".join(full_names))
        checkbox.setChecked(True)
        checkbox.toggled.connect(
            lambda checked, name=group_name: on_glomerulus_toggled(
                name, checked
            )
        )
        checkbox_by_group[group_name] = checkbox
        scroll_layout.addWidget(checkbox)
    scroll_layout.addStretch()
    scroll_contents.setLayout(scroll_layout)

    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setWidget(scroll_contents)

    panel = QWidget()
    layout = QVBoxLayout()
    layout.addWidget(QLabel("View"))
    layout.addWidget(axis_combo)
    layout.addWidget(QLabel("Rotation around displayed axes"))
    for label, spinbox in zip(("Z/slice", "Y/vertical", "X/horizontal"), rotation_spinboxes):
        row = QHBoxLayout()
        row.addWidget(QLabel(label))
        row.addWidget(spinbox)
        layout.addLayout(row)
    buttons = QHBoxLayout()
    buttons.addWidget(show_all_button)
    buttons.addWidget(show_none_button)
    layout.addLayout(buttons)
    layout.addWidget(QLabel("Glomeruli"))
    layout.addWidget(scroll)
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
        name = label_name(label_id, materials)
        viewer.status = f"{label_id}: {name}"
        hover_label.setText(f"{label_id}: {name}")

    refresh_layers()
    apply_rotation_transform()
    return panel


def main() -> None:
    viewer = napari.Viewer(title="lobemap - Grabe 2015", ndisplay=2)
    panel = load_atlas(viewer)
    viewer.window.add_dock_widget(panel, area="right", name="Grabe 2015")
    napari.run()


if __name__ == "__main__":
    main()
