#!/usr/bin/env python3
from __future__ import annotations

import colorsys
import gzip
import hashlib
import re
import sys
import webbrowser
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
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


WORK_DIR = Path(__file__).resolve().parent
ROOT = WORK_DIR.parent
sys.path.insert(0, str(ROOT / "scripts"))
from volume_helpers import LabelVisibilityFilter  # noqa: E402

SOURCE_DIR = WORK_DIR / "data/source"
TEMPLATE_ID = "VFB_00101567"


def cache_path(vfb_id: str) -> Path:
    return SOURCE_DIR / "vfb" / f"{vfb_id}.nrrd"


def label_volume_path() -> Path:
    return SOURCE_DIR / "jrc2018unisex_roi_labels.npz"


def parse_nrrd(path: Path) -> tuple[np.ndarray, dict[str, str]]:
    raw = path.read_bytes()
    header_end = raw.find(b"\n\n")
    separator_len = 2
    if header_end == -1:
        header_end = raw.find(b"\r\n\r\n")
        separator_len = 4
    if header_end == -1:
        raise ValueError(f"NRRD header terminator not found: {path}")

    header_text = raw[:header_end].decode("ascii")
    header: dict[str, str] = {}
    for line in header_text.splitlines():
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        header[key.strip().lower()] = value.strip()

    if header.get("type") != "uint8":
        raise ValueError(f"Unsupported NRRD type in {path}: {header.get('type')}")
    if header.get("encoding") != "gzip":
        raise ValueError(f"Unsupported NRRD encoding in {path}: {header.get('encoding')}")

    sizes = tuple(int(value) for value in header["sizes"].split())
    payload = raw[header_end + separator_len :]
    data = np.frombuffer(gzip.decompress(payload), dtype=np.uint8)
    if data.size != int(np.prod(sizes)):
        raise ValueError(f"NRRD size mismatch in {path}: {data.size} != {sizes}")
    return data.reshape(sizes, order="F").transpose(2, 1, 0), header


def spacing(header: dict[str, str]) -> tuple[float, float, float]:
    directions = header.get("space directions", "")
    vectors = re.findall(r"\(([^)]+)\)", directions)
    values: list[float] = []
    for vector in vectors:
        coords = [float(part) for part in vector.split(",")]
        values.append(float(np.linalg.norm(coords)))
    if len(values) != 3:
        return (1.0, 1.0, 1.0)
    return (values[2], values[1], values[0])


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


def load_template() -> tuple[np.ndarray, dict[str, str]]:
    return parse_nrrd(cache_path(TEMPLATE_ID))


def load_rois() -> pd.DataFrame:
    rois = pd.read_csv(SOURCE_DIR / "jrc2018unisex_rois.csv").fillna("")
    return rois.sort_values("label", key=lambda labels: labels.str.lower()).reset_index(
        drop=True
    )


def roi_manifest_key(rois: pd.DataFrame) -> str:
    rows = "\n".join(f"{row.label},{row.vfb_id}" for row in rois.itertuples(index=False))
    return hashlib.sha256(rows.encode("utf-8")).hexdigest()


def label_colors(label_ids: list[int]) -> dict[int, tuple[float, float, float, float]]:
    colors = {0: (0.0, 0.0, 0.0, 0.0)}
    for index, label_id in enumerate(label_ids):
        hue = (index * 0.61803398875) % 1.0
        red, green, blue = colorsys.hsv_to_rgb(hue, 0.78, 0.95)
        colors[label_id] = (red, green, blue, 0.58)
    return colors


def load_label_volume(rois: pd.DataFrame) -> tuple[np.ndarray, dict[int, str]]:
    cache = label_volume_path()
    manifest_key = roi_manifest_key(rois)
    with np.load(cache, allow_pickle=False) as data:
        if "manifest_key" not in data.files or str(data["manifest_key"][0]) != manifest_key:
            raise ValueError(f"JRC2018Unisex label cache does not match ROI manifest: {cache}")
        label_ids = data["label_ids"].astype(int).tolist()
        label_names = data["label_names"].astype(str).tolist()
        return (
            data["labels"].astype(np.uint16, copy=False),
            dict(zip(label_ids, label_names, strict=True)),
        )


def build_label_volume(rois: pd.DataFrame) -> tuple[np.ndarray, dict[int, str]]:
    labels = None
    names: dict[int, str] = {}
    for label_id, row in enumerate(rois.itertuples(index=False), start=1):
        path = cache_path(row.vfb_id)
        roi, _header = parse_nrrd(path)
        if labels is None:
            labels = np.zeros(roi.shape, dtype=np.uint16)
        labels[roi > 0] = label_id
        names[label_id] = str(row.label)
    if labels is None:
        raise ValueError("No JRC2018Unisex ROIs found")
    return labels, names


def make_roi_table(rois: pd.DataFrame, visible: set[str], on_change) -> QTableWidget:
    table = QTableWidget(len(rois), 2)
    table.setHorizontalHeaderLabels(["ROI", "VFB ID"])
    table.setSelectionBehavior(QTableWidget.SelectRows)
    table.setSelectionMode(QTableWidget.SingleSelection)
    table.verticalHeader().setVisible(False)
    table.setAlternatingRowColors(True)
    table.setSortingEnabled(False)
    for row, record in rois.reset_index(drop=True).iterrows():
        name = str(record["label"])
        item = QTableWidgetItem(name)
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        item.setCheckState(Qt.Checked if name in visible else Qt.Unchecked)
        table.setItem(row, 0, item)
        vfb_item = QTableWidgetItem(str(record["vfb_id"]))
        vfb_item.setFlags(vfb_item.flags() & ~Qt.ItemIsEditable)
        table.setItem(row, 1, vfb_item)
    table.resizeColumnsToContents()
    table.setColumnWidth(0, 112)
    table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
    table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
    table.itemChanged.connect(
        lambda item: on_change(item.text(), item.checkState() == Qt.Checked)
        if item.column() == 0
        else None
    )
    return table


def load_atlas(viewer: napari.Viewer) -> QWidget:
    viewer.title = "lobemap - JRC2018Unisex"
    viewer.dims.ndisplay = 2

    template, header = load_template()
    rois = load_rois()
    labels_source, names = load_label_volume(rois)
    visible: set[str] = set()
    labels_layer = None
    axis_orders = {
        "Dorsal-Ventral": (1, 0, 2),
        "Anterior-Posterior": (0, 1, 2),
        "Lateral-Medial": (2, 0, 1),
    }
    current_axis_order = axis_orders["Dorsal-Ventral"]
    rotation_degrees = {0: 0.0, 1: 0.0, 2: 0.0}
    mirror_vertical = False
    mirror_horizontal = False

    source_scale = spacing(header)
    colors = label_colors(sorted(names))
    label_filter = LabelVisibilityFilter(set(names))

    def displayed_scale() -> tuple[float, float, float]:
        return tuple(source_scale[axis] for axis in current_axis_order)

    template_layer = viewer.add_image(
        template.transpose(current_axis_order),
        name="JRC2018Unisex template",
        colormap="gray",
        contrast_limits=(0, 255),
        scale=displayed_scale(),
    )

    status = QLabel("Template and ROI labels loaded from tracked VFB data.")
    status.setWordWrap(True)
    status.setTextInteractionFlags(Qt.TextSelectableByMouse)

    def visible_ids() -> list[int]:
        return [label_id for label_id, name in names.items() if name in visible]

    def displayed_labels() -> np.ndarray:
        return label_filter.apply(
            labels_source.transpose(current_axis_order),
            set(visible_ids()),
        )

    def refresh_labels() -> None:
        labels_layer.data = displayed_labels()
        labels_layer.scale = displayed_scale()
        status.setText(f"{len(visible_ids())} JRC2018Unisex ROIs visible")

    def apply_rotation_transform() -> None:
        affine = affine_for_rotation(
            template_layer.data.shape,
            rotation_degrees,
            mirror_vertical,
            mirror_horizontal,
        )
        template_layer.affine = affine
        labels_layer.affine = affine

    def refresh_view() -> None:
        template_layer.data = template.transpose(current_axis_order)
        template_layer.scale = displayed_scale()
        refresh_labels()
        apply_rotation_transform()

    def on_roi_changed(name: str, checked: bool) -> None:
        if checked:
            visible.add(name)
        else:
            visible.discard(name)
        refresh_labels()

    def set_all(checked: bool) -> None:
        if checked:
            visible.update(str(label) for label in rois["label"])
        else:
            visible.clear()
        table.blockSignals(True)
        for row in range(table.rowCount()):
            table.item(row, 0).setCheckState(Qt.Checked if checked else Qt.Unchecked)
        table.blockSignals(False)
        refresh_labels()

    def open_selected() -> None:
        row = table.currentRow()
        if row < 0:
            return
        vfb_id = table.item(row, 1).text()
        webbrowser.open(f"https://www.virtualflybrain.org/reports/{vfb_id}")

    axis_combo = QComboBox()
    for name in axis_orders:
        axis_combo.addItem(name)

    def on_axis_changed(index: int) -> None:
        nonlocal current_axis_order
        current_axis_order = axis_orders[axis_combo.itemText(index)]
        refresh_view()

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

    axis_combo.currentIndexChanged.connect(on_axis_changed)

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

    features = pd.DataFrame(
        {
            "label_id": sorted(names),
            "name": [names[label_id] for label_id in sorted(names)],
        }
    )
    labels_layer = viewer.add_labels(
        displayed_labels(),
        name="JRC2018Unisex ROI labels",
        opacity=0.48,
        scale=displayed_scale(),
        features=features,
    )
    labels_layer.color = colors

    show_all = QPushButton("Show all")
    show_none = QPushButton("Show none")
    open_button = QPushButton("Open VFB")
    show_all.clicked.connect(lambda _checked=False: set_all(True))
    show_none.clicked.connect(lambda _checked=False: set_all(False))
    open_button.clicked.connect(open_selected)

    table = make_roi_table(rois, visible, on_roi_changed)

    buttons = QHBoxLayout()
    buttons.addWidget(show_all)
    buttons.addWidget(show_none)
    buttons.addWidget(open_button)

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
    mirror_vertical_checkbox = QCheckBox("Mirror vertical")
    mirror_horizontal_checkbox = QCheckBox("Mirror horizontal")
    mirror_vertical_checkbox.toggled.connect(
        lambda checked: on_mirror_changed("vertical", checked)
    )
    mirror_horizontal_checkbox.toggled.connect(
        lambda checked: on_mirror_changed("horizontal", checked)
    )
    layout.addWidget(mirror_vertical_checkbox)
    layout.addWidget(mirror_horizontal_checkbox)
    layout.addLayout(buttons)
    layout.addWidget(table)
    layout.addWidget(status)
    panel.setLayout(layout)
    apply_rotation_transform()
    return panel


def main() -> None:
    viewer = napari.Viewer(title="lobemap - JRC2018Unisex", ndisplay=2)
    panel = load_atlas(viewer)
    viewer.window.add_dock_widget(panel, area="right", name="JRC2018Unisex")
    napari.run()


if __name__ == "__main__":
    main()
