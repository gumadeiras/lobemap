from __future__ import annotations

import base64
import sys
import zlib
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

import numpy as np
from matplotlib.path import Path as PolygonPath


WORK_DIR = Path(__file__).resolve().parent
ROOT = WORK_DIR.parent
sys.path.insert(0, str(ROOT / "scripts"))
from ui_helpers import normalize_sensilla  # noqa: E402
from volume_helpers import (  # noqa: E402
    centroid_cache_to_arrays,
    label_slice_centroids,
    load_centroid_cache,
)

DATASET_DIR = WORK_DIR / "data/source/BentonDatasetEV2"
DERIVED_DIR = WORK_DIR / "data/derived"
VTM_PATH = DATASET_DIR / "DatasetEV2.seg.vtm"
COLOR_TABLE_PATH = DATASET_DIR / "DatasetEV2-label_ColorTable.ctbl"
VOLUME_RESOLUTION = 256
VOLUME_CACHE = DERIVED_DIR / f"benton_2025_label_volume_{VOLUME_RESOLUTION}.npz"
CACHE_VERSION = 2
AXIS_ORDERS = {
    "Dorsal-Ventral": (1, 0, 2),
    "Anterior-Posterior": (0, 1, 2),
    "Lateral-Medial": (2, 0, 1),
}
REVERSE_AXIS_ORDERS = {(1, 0, 2)}

VTK_DTYPES = {
    "Float32": np.dtype("<f4"),
    "Float64": np.dtype("<f8"),
    "Int32": np.dtype("<i4"),
    "Int64": np.dtype("<i8"),
    "UInt32": np.dtype("<u4"),
    "UInt64": np.dtype("<u8"),
}


@dataclass(frozen=True)
class Segment:
    label_id: int
    name: str
    glomerulus: str
    receptor: str
    sensillum: str
    color: tuple[float, float, float, float]
    file_path: Path


@dataclass(frozen=True)
class Mesh:
    label_id: int
    name: str
    glomerulus: str
    receptor: str
    sensillum: str
    vertices: np.ndarray
    faces: np.ndarray
    triangles: np.ndarray
    color: tuple[float, float, float, float]


@dataclass(frozen=True)
class AtlasVolume:
    labels: np.ndarray
    names: dict[int, str]
    glomeruli: dict[int, str]
    receptors: dict[int, str]
    sensilla: dict[int, str]
    colors: dict[int, tuple[float, float, float, float]]
    centroids: dict[tuple[tuple[int, int, int], bool], tuple[np.ndarray, np.ndarray]]


def parse_segment_name(raw_name: str) -> tuple[str, str, str]:
    parts = raw_name.split("-")
    if len(parts) < 3:
        return raw_name, "", ""
    glomerulus = parts[0]
    sensillum = parts[-1].replace("_and_", " and ")
    receptor = "-".join(parts[1:-1]).replace("_and_", " and ")
    return glomerulus, receptor, normalize_sensilla(sensillum.replace(",", ";"))


def load_color_table(path: Path = COLOR_TABLE_PATH) -> dict[int, Segment]:
    segments: dict[int, Segment] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 6:
            continue
        label_id = int(parts[0])
        name = parts[1]
        red, green, blue = (int(value) / 255.0 for value in parts[2:5])
        glomerulus, receptor, sensillum = parse_segment_name(name)
        segments[label_id] = Segment(
            label_id=label_id,
            name=name,
            glomerulus=glomerulus,
            receptor=receptor,
            sensillum=sensillum,
            color=(red, green, blue, 0.72),
            file_path=(
                DATASET_DIR
                / "DatasetEV2.seg"
                / f"DatasetEV2.seg_{label_id - 1}.vtp"
            ),
        )
    return segments


def compressed_header_length(encoded: str) -> int:
    first_word = base64.b64decode(encoded[:8])[:4]
    block_count = int(np.frombuffer(first_word, dtype="<u4", count=1)[0])
    header_bytes = 4 * (3 + block_count)
    return ((header_bytes + 2) // 3) * 4


def decode_vtk_data_array(element: ET.Element) -> bytes:
    encoded = "".join((element.text or "").split())
    if not encoded:
        return b""
    header_encoded_len = compressed_header_length(encoded)
    header = base64.b64decode(encoded[:header_encoded_len])
    block_count, _block_size, _last_block_size = np.frombuffer(
        header[:12], dtype="<u4", count=3
    )
    compressed_sizes = np.frombuffer(
        header[12 : 12 + int(block_count) * 4], dtype="<u4", count=int(block_count)
    )
    compressed = base64.b64decode(encoded[header_encoded_len:])
    chunks: list[bytes] = []
    pos = 0
    for size in compressed_sizes:
        end = pos + int(size)
        chunks.append(zlib.decompress(compressed[pos:end]))
        pos = end
    return b"".join(chunks)


def decode_numeric_array(element: ET.Element) -> np.ndarray:
    try:
        dtype = VTK_DTYPES[element.attrib["type"]]
    except KeyError as exc:
        raise ValueError(
            f"Unsupported VTK array type: {element.attrib.get('type')}"
        ) from exc
    return np.frombuffer(decode_vtk_data_array(element), dtype=dtype)


def triangulate_polys(connectivity: np.ndarray, offsets: np.ndarray) -> np.ndarray:
    faces: list[tuple[int, int, int]] = []
    start = 0
    for offset in offsets.astype(int, copy=False):
        polygon = connectivity[start:offset].astype(int, copy=False)
        start = int(offset)
        if len(polygon) < 3:
            continue
        for index in range(1, len(polygon) - 1):
            faces.append(
                (int(polygon[0]), int(polygon[index]), int(polygon[index + 1]))
            )
    return np.asarray(faces, dtype=np.int64)


def data_array(parent: ET.Element, name: str) -> ET.Element:
    for element in parent.findall("DataArray"):
        if element.attrib.get("Name") == name:
            return element
    raise ValueError(f"Missing VTK DataArray: {name}")


def load_vtm_segment_files(path: Path = VTM_PATH) -> list[Path]:
    root = ET.fromstring(path.read_text())
    files = []
    for data_set in root.findall("./vtkMultiBlockDataSet/DataSet"):
        file_attr = data_set.attrib.get("file")
        if file_attr:
            files.append(path.parent / file_attr)
    return files


def load_vtp_mesh(segment: Segment) -> Mesh:
    root = ET.fromstring(segment.file_path.read_text())
    piece = root.find("./PolyData/Piece")
    if piece is None:
        raise ValueError(f"Missing PolyData Piece in {segment.file_path}")
    points_element = piece.find("./Points/DataArray")
    polys_element = piece.find("./Polys")
    if points_element is None or polys_element is None:
        raise ValueError(f"Missing points or polys in {segment.file_path}")

    source_vertices = decode_numeric_array(points_element).reshape((-1, 3))
    vertices = source_vertices[:, [2, 1, 0]]
    connectivity = decode_numeric_array(data_array(polys_element, "connectivity"))
    offsets = decode_numeric_array(data_array(polys_element, "offsets"))
    faces = triangulate_polys(connectivity, offsets)
    return Mesh(
        label_id=segment.label_id,
        name=segment.name,
        glomerulus=segment.glomerulus,
        receptor=segment.receptor,
        sensillum=segment.sensillum,
        vertices=vertices,
        faces=faces,
        triangles=vertices[faces],
        color=segment.color,
    )


def load_meshes() -> list[Mesh]:
    segments = load_color_table()
    vtm_files = set(load_vtm_segment_files())
    meshes = []
    for segment in segments.values():
        if segment.file_path not in vtm_files:
            raise ValueError(f"Segment file missing from VTM: {segment.file_path}")
        mesh = load_vtp_mesh(segment)
        if len(mesh.vertices) and len(mesh.faces):
            meshes.append(mesh)
    return meshes


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


def build_label_volume(meshes: list[Mesh]) -> AtlasVolume:
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
        labels_for_axis = labels.transpose(axis_order)
        centroids[(axis_order, False)] = label_slice_centroids(labels_for_axis, label_ids)
        if axis_order in REVERSE_AXIS_ORDERS:
            centroids[(axis_order, True)] = label_slice_centroids(
                np.flip(labels_for_axis, axis=0),
                label_ids,
            )

    return AtlasVolume(
        labels=labels,
        names={mesh.label_id: mesh.name for mesh in meshes},
        glomeruli={mesh.label_id: mesh.glomerulus for mesh in meshes},
        receptors={mesh.label_id: mesh.receptor for mesh in meshes},
        sensilla={mesh.label_id: mesh.sensillum for mesh in meshes},
        colors={mesh.label_id: mesh.color for mesh in meshes},
        centroids=centroids,
    )


def save_volume_cache(volume: AtlasVolume) -> None:
    DERIVED_DIR.mkdir(parents=True, exist_ok=True)
    label_ids = np.asarray(sorted(volume.names), dtype=np.uint16)
    np.savez_compressed(
        VOLUME_CACHE,
        labels=volume.labels,
        label_ids=label_ids,
        names=np.asarray([volume.names[int(i)] for i in label_ids]),
        glomeruli=np.asarray([volume.glomeruli[int(i)] for i in label_ids]),
        receptors=np.asarray([volume.receptors[int(i)] for i in label_ids]),
        sensilla=np.asarray([volume.sensilla[int(i)] for i in label_ids]),
        colors=np.asarray([volume.colors[int(i)] for i in label_ids]),
        resolution=np.asarray([VOLUME_RESOLUTION], dtype=np.uint16),
        cache_version=np.asarray([CACHE_VERSION], dtype=np.uint16),
        **centroid_cache_to_arrays(volume.centroids),
    )


def load_volume_cache() -> AtlasVolume | None:
    if not VOLUME_CACHE.exists():
        return None
    with np.load(VOLUME_CACHE, allow_pickle=False) as data:
        if int(data["resolution"][0]) != VOLUME_RESOLUTION:
            return None
        if "cache_version" not in data.files:
            return None
        if int(data["cache_version"][0]) != CACHE_VERSION:
            return None
        label_ids = data["label_ids"].astype(int).tolist()
        names = data["names"].astype(str).tolist()
        glomeruli = data["glomeruli"].astype(str).tolist()
        receptors = data["receptors"].astype(str).tolist()
        sensilla = data["sensilla"].astype(str).tolist()
        colors = data["colors"].astype(float)
        return AtlasVolume(
            labels=data["labels"].astype(np.uint16, copy=False),
            names=dict(zip(label_ids, names, strict=True)),
            glomeruli=dict(zip(label_ids, glomeruli, strict=True)),
            receptors=dict(zip(label_ids, receptors, strict=True)),
            sensilla=dict(zip(label_ids, sensilla, strict=True)),
            colors={
                label_id: tuple(color)
                for label_id, color in zip(label_ids, colors, strict=True)
            },
            centroids=load_centroid_cache(
                data,
                list(AXIS_ORDERS.values()),
                reverse_axes=REVERSE_AXIS_ORDERS,
            ),
        )


def load_volume() -> AtlasVolume:
    cached = load_volume_cache()
    if cached is not None:
        return cached
    volume = build_label_volume(load_meshes())
    save_volume_cache(volume)
    return volume


def label_name(label_id: int, atlas: AtlasVolume) -> str:
    if label_id == 0:
        return "background"
    return atlas.names.get(label_id, f"unknown {label_id}")


def label_short_name(label_id: int, atlas: AtlasVolume) -> str:
    if label_id == 0:
        return "background"
    return atlas.glomeruli.get(label_id, f"?{label_id}")


def load_metadata(atlas: AtlasVolume) -> dict[str, dict[str, str]]:
    return {
        glomerulus: {
            "receptor": atlas.receptors.get(label_id, ""),
            "sensillum": atlas.sensilla.get(label_id, ""),
        }
        for label_id, glomerulus in atlas.glomeruli.items()
    }
