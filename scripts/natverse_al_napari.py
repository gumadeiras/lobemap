#!/usr/bin/env python3
from __future__ import annotations

import warnings
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
import sys

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
    QVBoxLayout,
    QWidget,
)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ui_helpers import make_glomerulus_table, normalize_sensilla, set_table_checked  # noqa: E402
from volume_helpers import (  # noqa: E402
    LabelVisibilityFilter,
    centroid_cache_to_arrays,
    label_slice_centroids,
    load_centroid_cache,
)


WORK_DIR = Path(__file__).resolve().parent
DATA_DIR = WORK_DIR / "data"
SOURCE_DIR = DATA_DIR / "source"
DERIVED_DIR = DATA_DIR / "derived"
VOLUME_RESOLUTION = 256
VOLUME_AXIS_NAMES = ("Dorsal-Ventral", "Anterior-Posterior", "Lateral-Medial")
AXIS_ORDERS = {
    "Dorsal-Ventral": (0, 1, 2),
    "Anterior-Posterior": (1, 0, 2),
    "Lateral-Medial": (2, 0, 1),
}
SOURCE_AXIS_COLUMNS = {
    "hemibrain_al_microns": ("Z", "Y", "X"),
    "flywire_al": ("Y", "Z", "X"),
    "flywire_al_neuropils": ("Y", "Z", "X"),
}

warnings.filterwarnings(
    "ignore",
    message="Non-orthogonal slicing is being requested, but is not fully supported.*",
    category=UserWarning,
    module=r"napari\.layers\.utils\._slice_input",
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
    source_axis_columns: tuple[str, str, str]
    centroids: dict[tuple[tuple[int, int, int], bool], tuple[np.ndarray, np.ndarray]]


def parse_hex_color(value: str) -> tuple[float, float, float, float]:
    value = value.strip().lstrip("#")
    if len(value) != 6:
        return (0.7, 0.7, 0.7, 0.75)
    return (
        int(value[0:2], 16) / 255.0,
        int(value[2:4], 16) / 255.0,
        int(value[4:6], 16) / 255.0,
        0.72,
    )


def source_axis_columns(stem: str) -> tuple[str, str, str]:
    try:
        return SOURCE_AXIS_COLUMNS[stem]
    except KeyError as exc:
        raise ValueError(f"No coordinate axis mapping defined for {stem}") from exc


def load_meshes(stem: str) -> list[Mesh]:
    materials = pd.read_csv(SOURCE_DIR / f"{stem}_materials.csv")
    vertices_df = pd.read_csv(SOURCE_DIR / f"{stem}_vertices.csv.gz")
    vertices_df = vertices_df.sort_values("PointNo")
    vertices = vertices_df[list(source_axis_columns(stem))].to_numpy(dtype=float)

    faces_df = pd.read_csv(SOURCE_DIR / f"{stem}_faces.csv.gz")
    meshes: list[Mesh] = []
    for material in materials.itertuples(index=False):
        face_rows = faces_df[faces_df["id"] == int(material.id)]
        faces = face_rows[["v1", "v2", "v3"]].to_numpy(dtype=int) - 1
        meshes.append(
            Mesh(
                label_id=int(material.id),
                name=str(material.name),
                vertices=vertices,
                faces=faces,
                triangles=vertices[faces],
                color=parse_hex_color(str(material.col)),
            )
        )
    if stem == "flywire_al":
        meshes = load_optional_meshes("flywire_al_neuropils") + meshes
    return meshes


def load_optional_meshes(stem: str) -> list[Mesh]:
    if not (SOURCE_DIR / f"{stem}_materials.csv").exists():
        return []
    return load_meshes(stem)


def mesh_bounds(meshes: list[Mesh]) -> tuple[np.ndarray, np.ndarray]:
    vertices = np.vstack([mesh.triangles.reshape(-1, 3) for mesh in meshes])
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


def rasterize_loop(volume_slice: np.ndarray, loop: np.ndarray, label_id: int) -> None:
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


def build_label_volume(meshes: list[Mesh], stem: str) -> AtlasVolume:
    lo, hi = mesh_bounds(meshes)
    levels = np.linspace(lo[0], hi[0], VOLUME_RESOLUTION)
    labels = np.zeros(
        (VOLUME_RESOLUTION, VOLUME_RESOLUTION, VOLUME_RESOLUTION),
        dtype=np.uint16,
    )

    for z_index, level in enumerate(levels):
        volume_slice = labels[z_index]
        for mesh in meshes:
            segments = triangle_segments(mesh, level, cut_axis=0)
            for loop in segments_to_loops(segments):
                indexed = np.column_stack(
                    [
                        to_index(loop[:, 0], lo[1], hi[1]),
                        to_index(loop[:, 1], lo[2], hi[2]),
                    ]
                )
                rasterize_loop(volume_slice, indexed, mesh.label_id)

    label_ids = np.asarray(sorted(mesh.label_id for mesh in meshes), dtype=np.uint16)
    centroids = {}
    for axis_order in AXIS_ORDERS.values():
        lateral_axis = axis_order.index(2) if stem == "flywire_al" else None
        hemisphere_axis = lateral_axis if lateral_axis in (1, 2) else None
        centroids[(axis_order, False)] = label_slice_centroids(
            labels.transpose(axis_order),
            label_ids,
            hemisphere_axis=hemisphere_axis,
        )

    return AtlasVolume(
        labels=labels,
        names={mesh.label_id: mesh.name for mesh in meshes},
        colors={mesh.label_id: mesh.color for mesh in meshes},
        source_axis_columns=source_axis_columns(stem),
        centroids=centroids,
    )


def volume_cache(stem: str) -> Path:
    if stem == "flywire_al" and (SOURCE_DIR / "flywire_al_neuropils_materials.csv").exists():
        return DERIVED_DIR / f"{stem}_label_volume_{VOLUME_RESOLUTION}_with_neuropils.npz"
    return DERIVED_DIR / f"{stem}_label_volume_{VOLUME_RESOLUTION}.npz"


def save_volume_cache(stem: str, volume: AtlasVolume) -> None:
    DERIVED_DIR.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        volume_cache(stem),
        labels=volume.labels,
        label_ids=np.asarray(sorted(volume.names), dtype=np.uint16),
        names=np.asarray([volume.names[i] for i in sorted(volume.names)]),
        colors=np.asarray([volume.colors[i] for i in sorted(volume.names)]),
        resolution=np.asarray([VOLUME_RESOLUTION], dtype=np.uint16),
        cache_version=np.asarray([4 if stem == "flywire_al" else 2], dtype=np.uint16),
        source_axis_columns=np.asarray(volume.source_axis_columns),
        volume_axis_names=np.asarray(VOLUME_AXIS_NAMES),
        **centroid_cache_to_arrays(volume.centroids),
    )


def load_volume_cache(stem: str) -> AtlasVolume | None:
    cache = volume_cache(stem)
    if not cache.exists():
        return None
    with np.load(cache, allow_pickle=False) as data:
        resolution = int(data["resolution"][0])
        if resolution != VOLUME_RESOLUTION:
            return None
        if stem == "flywire_al" and (
            "cache_version" not in data.files or int(data["cache_version"][0]) < 3
        ):
            return None
        if "source_axis_columns" not in data.files:
            return None
        cached_axis_columns = tuple(data["source_axis_columns"].astype(str))
        if cached_axis_columns != source_axis_columns(stem):
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
            source_axis_columns=cached_axis_columns,
            centroids=load_centroid_cache(data, list(AXIS_ORDERS.values())),
        )


def load_volume(stem: str) -> AtlasVolume:
    cached = load_volume_cache(stem)
    if cached is not None:
        return cached
    volume = build_label_volume(load_meshes(stem), stem)
    save_volume_cache(stem, volume)
    return volume


def label_name(label_id: int, names: dict[int, str]) -> str:
    if label_id == 0:
        return "background"
    return names.get(label_id, f"unknown {label_id}")


def load_metadata() -> dict[str, dict[str, str]]:
    metadata: dict[str, dict[str, str]] = {}
    door_mappings_path = WORK_DIR.parent / "door/data/source/door_mappings.csv"
    if door_mappings_path.exists():
        mappings = pd.read_csv(door_mappings_path).fillna("")
        for row in mappings.to_dict("records"):
            glomerulus = str(row.get("glomerulus", ""))
            if not glomerulus:
                continue
            metadata.setdefault(glomerulus, {}).update(
                {
                    "door_receptor": str(row.get("receptor", "")),
                    "sensillum": normalize_sensilla(row.get("sensillum", "")),
                    "osn": str(row.get("OSN", "")),
                    "co_receptor": str(row.get("co.receptor", "")),
                }
            )

    summary_path = SOURCE_DIR / "hemibrain_glomeruli_summary.csv"
    if summary_path.exists():
        summary = pd.read_csv(summary_path).fillna("")
        for row in summary.to_dict("records"):
            metadata.setdefault(str(row["glomerulus"]), {}).update(
                {
                    "receptor": str(row.get("receptor", "")),
                    "odour_scenes": str(row.get("odour_scenes", "")),
                    "key_ligand": str(row.get("key_ligand", "")),
                    "valence": str(row.get("valence", "")),
                }
            )

    vfb_path = SOURCE_DIR / "vfb_glomerulus_terms.csv"
    if vfb_path.exists():
        terms = pd.read_csv(vfb_path).fillna("")
        for row in terms.to_dict("records"):
            glomerulus = str(row["glomerulus"])
            metadata.setdefault(glomerulus, {}).update(
                {
                    "fbbt_id": str(row.get("fbbt_id", "")),
                    "vfb_url": str(row.get("vfb_url", "")),
                }
            )
    return metadata


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


def load_atlas(
    viewer: napari.Viewer,
    work_dir: Path,
    stem: str,
    title: str,
    default_mirror_vertical: bool = False,
) -> QWidget:
    global WORK_DIR, DATA_DIR, SOURCE_DIR, DERIVED_DIR
    WORK_DIR = Path(work_dir)
    DATA_DIR = WORK_DIR / "data"
    SOURCE_DIR = DATA_DIR / "source"
    DERIVED_DIR = DATA_DIR / "derived"

    atlas = load_volume(stem)
    source_labels = atlas.labels
    unique_ids = np.asarray(sorted(i for i in np.unique(source_labels) if i != 0))
    all_label_ids = unique_ids.copy()
    metadata = load_metadata()
    features = pd.DataFrame(
        [
            {
                "label_id": int(i),
                "name": label_name(int(i), atlas.names),
                "short_name": label_name(int(i), atlas.names),
                **metadata.get(label_name(int(i), atlas.names), {}),
            }
            for i in np.unique(source_labels)
        ]
    )

    visible_names = set(atlas.names.values())
    fixed_ids = {
        label_id
        for label_id, name in atlas.names.items()
        if name.startswith("AL_")
    }
    visible_names.difference_update(atlas.names[label_id] for label_id in fixed_ids)
    label_ids = [label_id for label_id in unique_ids if int(label_id) not in fixed_ids]
    unique_ids = np.asarray(label_ids, dtype=unique_ids.dtype)
    axis_orders = AXIS_ORDERS
    current_axis_order = axis_orders["Dorsal-Ventral"]
    rotation_degrees = {0: 0.0, 1: 0.0, 2: 0.0}
    mirror_vertical = default_mirror_vertical
    mirror_horizontal = False
    centroid_cache = dict(atlas.centroids)
    label_filter = LabelVisibilityFilter(all_label_ids)

    def visible_ids() -> set[int]:
        return {
            label_id
            for label_id, name in atlas.names.items()
            if name in visible_names
        } | fixed_ids

    def centroids_for_axis(
        axis_order: tuple[int, int, int],
    ) -> tuple[np.ndarray, np.ndarray]:
        cache_key = (axis_order, False)
        cached = centroid_cache.get(cache_key)
        if cached is None:
            lateral_axis = axis_order.index(2) if stem == "flywire_al" else None
            hemisphere_axis = lateral_axis if lateral_axis in (1, 2) else None
            cached = label_slice_centroids(
                source_labels.transpose(axis_order),
                unique_ids,
                hemisphere_axis=hemisphere_axis,
            )
            centroid_cache[cache_key] = cached
        return cached

    def current_scene_data() -> tuple[np.ndarray, np.ndarray, list[int]]:
        labels = source_labels.transpose(current_axis_order)
        points, point_ids = centroids_for_axis(current_axis_order)
        visible_mask = np.isin(point_ids, list(visible_ids()))
        return (
            label_filter.apply(labels, visible_ids(), always_visible_ids=fixed_ids),
            points[visible_mask],
            point_ids[visible_mask].astype(int).tolist(),
        )

    viewer.title = f"lobemap - {title}"
    viewer.dims.ndisplay = 2
    labels, anchor_points, anchor_ids = current_scene_data()
    labels_layer = viewer.add_labels(
        labels,
        name="glomerulus labels",
        opacity=0.62,
        features=features,
    )
    labels_layer.color = atlas.colors

    points_layer = viewer.add_points(
        anchor_points,
        name="slice name anchors",
        size=0.0,
        features=pd.DataFrame(
            {
                "label_id": anchor_ids,
                "name": [label_name(i, atlas.names) for i in anchor_ids],
                "short_name": [label_name(i, atlas.names) for i in anchor_ids],
                "receptor": [
                    metadata.get(label_name(i, atlas.names), {}).get("receptor", "")
                    for i in anchor_ids
                ],
                "odour_scenes": [
                    metadata.get(label_name(i, atlas.names), {}).get("odour_scenes", "")
                    for i in anchor_ids
                ],
                "fbbt_id": [
                    metadata.get(label_name(i, atlas.names), {}).get("fbbt_id", "")
                    for i in anchor_ids
                ],
                "sensillum": [
                    normalize_sensilla(
                        metadata.get(label_name(i, atlas.names), {}).get("sensillum", "")
                    )
                    for i in anchor_ids
                ],
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
    table = None

    def refresh_layers() -> None:
        labels, anchor_points, anchor_ids = current_scene_data()
        labels_layer.data = labels
        points_layer.data = anchor_points
        points_layer.features = pd.DataFrame(
            {
                "label_id": anchor_ids,
                "name": [label_name(i, atlas.names) for i in anchor_ids],
                "short_name": [label_name(i, atlas.names) for i in anchor_ids],
                "receptor": [
                    metadata.get(label_name(i, atlas.names), {}).get("receptor", "")
                    for i in anchor_ids
                ],
                "odour_scenes": [
                    metadata.get(label_name(i, atlas.names), {}).get("odour_scenes", "")
                    for i in anchor_ids
                ],
                "fbbt_id": [
                    metadata.get(label_name(i, atlas.names), {}).get("fbbt_id", "")
                    for i in anchor_ids
                ],
                "sensillum": [
                    normalize_sensilla(
                        metadata.get(label_name(i, atlas.names), {}).get("sensillum", "")
                    )
                    for i in anchor_ids
                ],
            }
        )
        hover_label.setText(f"{len(visible_names)} glomeruli visible")

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
        visible_names.clear()
        visible_names.update(
            name for label_id, name in atlas.names.items() if label_id not in fixed_ids
        )
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

    show_all_button = QPushButton("Show all")
    show_none_button = QPushButton("Show none")
    show_all_button.clicked.connect(show_all)
    show_none_button.clicked.connect(show_none)

    table_names = sorted(set(visible_names))
    table = make_glomerulus_table(table_names, visible_names, metadata, on_glomerulus_toggled)

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
    mirror_vertical_checkbox.setChecked(mirror_vertical)
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
        name = label_name(label_id, atlas.names)
        if label_id not in visible_ids():
            return
        meta = metadata.get(name, {})
        parts = [f"{label_id}: {name}"]
        if meta.get("receptor"):
            parts.append(meta["receptor"])
        elif meta.get("door_receptor"):
            parts.append(meta["door_receptor"])
        if meta.get("sensillum"):
            parts.append(meta["sensillum"])
        if meta.get("odour_scenes"):
            parts.append(meta["odour_scenes"])
        if meta.get("fbbt_id"):
            parts.append(meta["fbbt_id"])
        text = " | ".join(parts)
        viewer.status = text
        hover_label.setText(text)

    refresh_layers()
    apply_rotation_transform()
    return panel


def main() -> None:
    viewer = napari.Viewer(title="lobemap - Hemibrain", ndisplay=2)
    panel = load_atlas(
        viewer,
        Path(__file__).resolve().parents[1] / "hemibrain",
        "hemibrain_al_microns",
        "Hemibrain",
        default_mirror_vertical=True,
    )
    viewer.window.add_dock_widget(panel, area="right", name="Hemibrain")
    napari.run()


if __name__ == "__main__":
    main()
