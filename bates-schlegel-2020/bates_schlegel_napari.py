#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import napari
import numpy as np
import pandas as pd
from matplotlib.path import Path as PolygonPath
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
SOURCE_HTML = WORK_DIR / "data/source/glomeruli_atlas_interactive.html"
DERIVED_DIR = WORK_DIR / "data/derived"
VOLUME_RESOLUTION = 256
VOLUME_CACHE = DERIVED_DIR / (
    f"bates_schlegel_label_volume_{VOLUME_RESOLUTION}_glomerulus_bounds_with_neuropil.npz"
)
BATES_TO_GRABE_FLIPS = (False, True, False)
NEUROPIL_NAME = "neuropil"
RGBA_PATTERN = re.compile(
    r"rgba\(\s*([0-9.]+),\s*([0-9.]+),\s*([0-9.]+),\s*([0-9.]+)\s*\)"
)


@dataclass(frozen=True)
class Mesh:
    label_id: int
    name: str
    vertices: np.ndarray
    faces: np.ndarray
    triangles: np.ndarray
    color: tuple[float, float, float, float]


@dataclass(frozen=True)
class AtlasVolume:
    labels: np.ndarray
    names: dict[int, str]
    colors: dict[int, tuple[float, float, float, float]]


def extract_plotly_data(html_path: Path) -> list[dict]:
    text = html_path.read_text()
    start = text.index("Plotly.newPlot(")
    data_start = text.index("[", start)

    depth = 0
    in_string = False
    escaped = False
    for pos in range(data_start, len(text)):
        ch = text[pos]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return json.loads(text[data_start : pos + 1])

    raise ValueError(f"Could not find Plotly data array in {html_path}")


def parse_color(value: str | None) -> tuple[float, float, float, float]:
    if value is None:
        return (0.7, 0.7, 0.7, 0.75)
    match = RGBA_PATTERN.fullmatch(value)
    if match is None:
        return (0.7, 0.7, 0.7, 0.75)
    r, g, b, a = (float(v) for v in match.groups())
    return (r / 255.0, g / 255.0, b / 255.0, min(a, 0.85))


def load_meshes(html_path: Path = SOURCE_HTML) -> list[Mesh]:
    meshes = []
    label_id = 1
    for trace in extract_plotly_data(html_path):
        if trace.get("type") != "mesh3d":
            continue
        vertices = np.column_stack(
            [
                np.asarray(trace["z"], dtype=float),
                np.asarray(trace["y"], dtype=float),
                np.asarray(trace["x"], dtype=float),
            ]
        )
        faces = np.column_stack(
            [
                np.asarray(trace["i"], dtype=int),
                np.asarray(trace["j"], dtype=int),
                np.asarray(trace["k"], dtype=int),
            ]
        )
        meshes.append(
            Mesh(
                label_id=label_id,
                name=str(trace["name"]),
                vertices=vertices,
                faces=faces,
                triangles=vertices[faces],
                color=(
                    (0.72, 0.72, 0.72, 0.28)
                    if trace.get("name") == NEUROPIL_NAME
                    else parse_color(trace.get("color"))
                ),
            )
        )
        label_id += 1
    return meshes


def mesh_bounds(meshes: list[Mesh]) -> tuple[np.ndarray, np.ndarray]:
    bounds_meshes = [mesh for mesh in meshes if mesh.name != NEUROPIL_NAME]
    vertices = np.vstack([mesh.vertices for mesh in bounds_meshes])
    lo = np.nanmin(vertices, axis=0)
    hi = np.nanmax(vertices, axis=0)
    pad = (hi - lo) * 0.02
    return lo - pad, hi + pad


def edge_intersection(
    p0: np.ndarray, p1: np.ndarray, v0: float, v1: float, eps: float
) -> np.ndarray | None:
    if abs(v0) <= eps and abs(v1) <= eps:
        return None
    if abs(v0) <= eps:
        return p0
    if abs(v1) <= eps:
        return p1
    if (v0 < 0 and v1 > 0) or (v0 > 0 and v1 < 0):
        t = v0 / (v0 - v1)
        return p0 + t * (p1 - p0)
    return None


def triangle_segments(
    mesh: Mesh, level: float, cut_axis: int, eps: float = 1e-6
) -> list[tuple[np.ndarray, np.ndarray]]:
    segs = []
    seen = set()
    project_axes = [axis for axis in range(3) if axis != cut_axis]
    vals_by_triangle = mesh.triangles[:, :, cut_axis] - level
    keep = ~(
        np.all(vals_by_triangle > eps, axis=1)
        | np.all(vals_by_triangle < -eps, axis=1)
    )

    for tri, vals in zip(mesh.triangles[keep], vals_by_triangle[keep]):
        intersections = []
        for u, v in ((0, 1), (1, 2), (2, 0)):
            point = edge_intersection(tri[u], tri[v], vals[u], vals[v], eps)
            if point is not None:
                intersections.append(point[project_axes])

        uniq = []
        keys = set()
        for point in intersections:
            key = tuple(np.round(point, 6))
            if key not in keys:
                keys.add(key)
                uniq.append(point)

        if len(uniq) != 2:
            continue

        akey = tuple(np.round(uniq[0], 6))
        bkey = tuple(np.round(uniq[1], 6))
        edge_key = tuple(sorted((akey, bkey)))
        if akey == bkey or edge_key in seen:
            continue
        seen.add(edge_key)
        segs.append((np.asarray(uniq[0]), np.asarray(uniq[1])))

    return segs


def polygon_area(points: np.ndarray) -> float:
    x = points[:, 0]
    y = points[:, 1]
    return abs(0.5 * np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))


def segments_to_loops(
    segments: list[tuple[np.ndarray, np.ndarray]], quant: float = 1e-3
) -> list[np.ndarray]:
    def key(point: np.ndarray) -> tuple[int, int]:
        return tuple(np.round(point / quant).astype(int))

    points = {}
    edges = set()
    adj = defaultdict(set)
    for a, b in segments:
        ka = key(a)
        kb = key(b)
        if ka == kb:
            continue
        points.setdefault(ka, np.asarray(a, dtype=float))
        points.setdefault(kb, np.asarray(b, dtype=float))
        edge = tuple(sorted((ka, kb)))
        if edge in edges:
            continue
        edges.add(edge)
        adj[ka].add(kb)
        adj[kb].add(ka)

    loops = []
    used = set()
    for edge in list(edges):
        if edge in used:
            continue

        start, nxt = edge
        loop = [start]
        prev = start
        cur = nxt
        used.add(edge)

        while True:
            loop.append(cur)
            candidates = [node for node in adj[cur] if node != prev]
            if not candidates:
                break
            if start in candidates:
                used.add(tuple(sorted((cur, start))))
                loop.append(start)
                break

            unused = [
                node
                for node in candidates
                if tuple(sorted((cur, node))) not in used
            ]
            if not unused:
                break
            nxt = unused[0]
            used.add(tuple(sorted((cur, nxt))))
            prev, cur = cur, nxt

        if len(loop) >= 4 and loop[0] == loop[-1]:
            arr = np.vstack([points[node] for node in loop[:-1]])
            if polygon_area(arr) > 1:
                loops.append(arr)

    return loops


def to_index(values: np.ndarray, lo: float, hi: float) -> np.ndarray:
    return (values - lo) / (hi - lo) * (VOLUME_RESOLUTION - 1)


def rasterize_loop(
    volume_slice: np.ndarray, loop: np.ndarray, label_id: int
) -> None:
    ys = loop[:, 0]
    xs = loop[:, 1]
    y0 = max(int(np.floor(np.nanmin(ys))), 0)
    y1 = min(int(np.ceil(np.nanmax(ys))), volume_slice.shape[0] - 1)
    x0 = max(int(np.floor(np.nanmin(xs))), 0)
    x1 = min(int(np.ceil(np.nanmax(xs))), volume_slice.shape[1] - 1)
    if y1 < y0 or x1 < x0:
        return

    yy, xx = np.mgrid[y0 : y1 + 1, x0 : x1 + 1]
    points = np.column_stack([xx.ravel(), yy.ravel()])
    path = PolygonPath(np.column_stack([xs, ys]))
    mask = path.contains_points(points).reshape(yy.shape)
    volume_slice[yy[mask], xx[mask]] = label_id


def build_label_volume(meshes: list[Mesh]) -> AtlasVolume:
    lo, hi = mesh_bounds(meshes)
    levels = np.linspace(lo[0], hi[0], VOLUME_RESOLUTION)
    raster_meshes = sorted(meshes, key=lambda mesh: mesh.name != NEUROPIL_NAME)
    labels = np.zeros(
        (VOLUME_RESOLUTION, VOLUME_RESOLUTION, VOLUME_RESOLUTION),
        dtype=np.uint16,
    )

    for z_index, level in enumerate(levels):
        volume_slice = labels[z_index]
        for mesh in raster_meshes:
            segments = triangle_segments(mesh, level, cut_axis=0)
            for loop in segments_to_loops(segments):
                indexed = np.column_stack(
                    [
                        to_index(loop[:, 0], lo[1], hi[1]),
                        to_index(loop[:, 1], lo[2], hi[2]),
                    ]
                )
                rasterize_loop(volume_slice, indexed, mesh.label_id)

    return AtlasVolume(
        labels=labels,
        names={mesh.label_id: mesh.name for mesh in meshes},
        colors={mesh.label_id: mesh.color for mesh in meshes},
    )


def save_volume_cache(volume: AtlasVolume) -> None:
    DERIVED_DIR.mkdir(parents=True, exist_ok=True)
    np.savez(
        VOLUME_CACHE,
        labels=volume.labels,
        label_ids=np.asarray(sorted(volume.names), dtype=np.uint16),
        names=np.asarray([volume.names[i] for i in sorted(volume.names)]),
        colors=np.asarray([volume.colors[i] for i in sorted(volume.names)]),
        resolution=np.asarray([VOLUME_RESOLUTION], dtype=np.uint16),
    )


def load_volume_cache() -> AtlasVolume | None:
    if not VOLUME_CACHE.exists():
        return None
    with np.load(VOLUME_CACHE, allow_pickle=False) as data:
        resolution = int(data["resolution"][0])
        if resolution != VOLUME_RESOLUTION:
            return None
        label_ids = data["label_ids"].astype(int).tolist()
        names_array = data["names"].astype(str).tolist()
        colors_array = data["colors"].astype(float)
        return AtlasVolume(
            labels=data["labels"].astype(np.uint16, copy=False),
            names=dict(zip(label_ids, names_array, strict=True)),
            colors={
                label_id: tuple(color)
                for label_id, color in zip(label_ids, colors_array, strict=True)
            },
        )


def load_volume() -> AtlasVolume:
    cached = load_volume_cache()
    if cached is not None:
        return cached
    volume = build_label_volume(load_meshes())
    save_volume_cache(volume)
    return volume


def orient_like_grabe(labels: np.ndarray) -> np.ndarray:
    oriented = labels
    for axis, should_flip in enumerate(BATES_TO_GRABE_FLIPS):
        if should_flip:
            oriented = np.flip(oriented, axis=axis)
    return oriented


def label_name(label_id: int, names: dict[int, str]) -> str:
    if label_id == 0:
        return "background"
    return names.get(label_id, f"unknown {label_id}")


def label_slice_centroids(
    labels: np.ndarray, ids: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    valid_ids = {int(i) for i in ids if i != 0}
    centroids: list[tuple[float, float, float]] = []
    centroid_ids: list[int] = []
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
            if label_id == 0 or label_id not in valid_ids:
                continue
            n = int(count[label_id])
            centroids.append((float(z), y_sum[label_id] / n, x_sum[label_id] / n))
            centroid_ids.append(int(label_id))

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


def load_atlas(viewer: napari.Viewer) -> QWidget:
    viewer.title = "lobemap - Bates Schlegel 2020"
    viewer.dims.ndisplay = 2

    atlas = load_volume()
    source_labels = orient_like_grabe(atlas.labels)
    unique_ids = np.asarray(sorted(i for i in np.unique(source_labels) if i != 0))
    features = pd.DataFrame(
        [
            {
                "label_id": int(i),
                "name": label_name(int(i), atlas.names),
                "short_name": label_name(int(i), atlas.names),
            }
            for i in np.unique(source_labels)
        ]
    )

    visible_names = {
        name for name in atlas.names.values() if name != NEUROPIL_NAME
    }
    axis_orders = {
        "Anterior-Posterior": (0, 1, 2),
        "Dorsal-Ventral": (1, 0, 2),
        "Lateral-Medial": (2, 0, 1),
    }
    current_axis_order = axis_orders["Anterior-Posterior"]
    rotation_degrees = {0: 0.0, 1: 0.0, 2: 0.0}
    centroid_cache: dict[tuple[int, int, int], tuple[np.ndarray, np.ndarray]] = {}

    def visible_ids() -> set[int]:
        return {
            label_id
            for label_id, name in atlas.names.items()
            if name in visible_names
        }

    def filtered_labels(labels: np.ndarray) -> np.ndarray:
        lut = np.zeros(int(source_labels.max()) + 1, dtype=np.uint16)
        for label_id in visible_ids():
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

    def current_scene_data() -> tuple[np.ndarray, np.ndarray, list[int]]:
        labels = source_labels.transpose(current_axis_order)
        points, point_ids = centroids_for_axis(current_axis_order)
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
        features=features,
    )
    try:
        labels_layer.color = atlas.colors
    except Exception:
        pass

    points_layer = viewer.add_points(
        anchor_points,
        name="slice name anchors",
        size=0.0,
        features=pd.DataFrame(
            {
                "label_id": anchor_ids,
                "name": [label_name(i, atlas.names) for i in anchor_ids],
                "short_name": [label_name(i, atlas.names) for i in anchor_ids],
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
    checkbox_by_name: dict[str, QCheckBox] = {}

    def refresh_layers() -> None:
        labels, anchor_points, anchor_ids = current_scene_data()
        labels_layer.data = labels
        points_layer.data = anchor_points
        points_layer.features = pd.DataFrame(
            {
                "label_id": anchor_ids,
                "name": [label_name(i, atlas.names) for i in anchor_ids],
                "short_name": [label_name(i, atlas.names) for i in anchor_ids],
            }
        )
        hover_label.setText(f"{len(visible_names)} glomeruli visible")

    def apply_rotation_transform() -> None:
        affine = affine_for_rotation(labels_layer.data.shape, rotation_degrees)
        labels_layer.affine = affine
        points_layer.affine = affine

    def set_checked_without_signals(checked: bool) -> None:
        for checkbox in checkbox_by_name.values():
            checkbox.blockSignals(True)
            checkbox.setChecked(checked)
            checkbox.blockSignals(False)

    def show_all() -> None:
        visible_names.clear()
        visible_names.update(atlas.names.values())
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

    axis_combo = QComboBox()
    for name in axis_orders:
        axis_combo.addItem(name)

    def on_axis_changed(index: int) -> None:
        nonlocal current_axis_order
        current_axis_order = axis_orders[axis_combo.itemText(index)]
        refresh_layers()
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

    def on_rotation_changed(axis: int, value: float) -> None:
        rotation_degrees[axis] = value
        apply_rotation_transform()

    show_all_button = QPushButton("Show all")
    show_none_button = QPushButton("Show none")
    show_all_button.clicked.connect(show_all)
    show_none_button.clicked.connect(show_none)

    scroll_contents = QWidget()
    scroll_layout = QVBoxLayout()
    scroll_layout.setContentsMargins(0, 0, 0, 0)
    for name in sorted(atlas.names.values()):
        checkbox = QCheckBox(name)
        checkbox.setChecked(name != NEUROPIL_NAME)
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
        name = label_name(label_id, atlas.names)
        viewer.status = f"{label_id}: {name}"
        hover_label.setText(f"{label_id}: {name}")

    refresh_layers()
    apply_rotation_transform()
    return panel


def main() -> None:
    viewer = napari.Viewer(title="lobemap - Bates Schlegel 2020", ndisplay=2)
    panel = load_atlas(viewer)
    viewer.window.add_dock_widget(panel, area="right", name="Bates Schlegel 2020")
    napari.run()


if __name__ == "__main__":
    main()
