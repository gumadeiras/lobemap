#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from fafbseg import flywire
from scipy import ndimage
from skimage import measure


WORK_DIR = Path(__file__).resolve().parents[1]
SOURCE_DIR = WORK_DIR / "data/source"
ANNOTATION_URL = (
    "https://raw.githubusercontent.com/flyconnectome/flywire_annotations/main/"
    "supplemental_files/Supplemental_file1_neuron_annotations.tsv"
)

VOXEL_SIZE_NM = 1800.0
MESH_PADDING_NM = 2500.0
MAX_GRID_SIZE = 88
MIN_POINTS = 60
MAX_WORKERS = 8
DENSITY_PERCENTILE = 70.0
DENSITY_MAX_FRACTION = 0.16
CONSENSUS_DILATION = 4
LOCAL_DILATION = 5
LOCAL_MAX_POINTS_PER_NEURON = 2500
LOCAL_NEURON_CLASSES = {"ALLN", "ALIN", "ALON"}


@dataclass(frozen=True)
class NeuropilBounds:
    name: str
    lo: np.ndarray
    hi: np.ndarray


def load_neuropil_bounds() -> list[NeuropilBounds]:
    materials = pd.read_csv(SOURCE_DIR / "flywire_al_neuropils_materials.csv")
    vertices = pd.read_csv(SOURCE_DIR / "flywire_al_neuropils_vertices.csv.gz")
    faces = pd.read_csv(SOURCE_DIR / "flywire_al_neuropils_faces.csv.gz")
    bounds = []
    for material in materials.itertuples(index=False):
        face_rows = faces[faces["id"] == int(material.id)][["v1", "v2", "v3"]].to_numpy() - 1
        points = vertices.iloc[face_rows.reshape(-1)][["X", "Y", "Z"]].to_numpy(float)
        span = points.max(axis=0) - points.min(axis=0)
        pad = np.maximum(span * 0.04, MESH_PADDING_NM)
        bounds.append(
            NeuropilBounds(
                name=str(material.name),
                lo=points.min(axis=0) - pad,
                hi=points.max(axis=0) + pad,
            )
        )
    return bounds


def material_table() -> pd.DataFrame:
    return pd.read_csv(SOURCE_DIR / "flywire_al_materials.csv")


def normalize_glomerulus(cell_type: str) -> str:
    if cell_type.startswith("ORN_"):
        value = cell_type.removeprefix("ORN_")
        if value.startswith("VM6"):
            return "VM6"
        return value
    if cell_type.startswith("HRN_"):
        return cell_type.removeprefix("HRN_")
    if cell_type.startswith("TRN_"):
        value = cell_type.removeprefix("TRN_")
        if value.startswith("VP3"):
            return "VP3"
        return value
    value = cell_type.split("_", 1)[0]
    return value.rstrip("+")


def expand_multiglomerular_projection_rows(
    rows: pd.DataFrame, glomeruli: set[str]
) -> pd.DataFrame:
    extra_rows = []
    target_glomeruli = {"VP3", "VP5"}
    for row in rows.to_dict("records"):
        cell_type = str(row.get("cell_type", ""))
        for glomerulus in sorted(target_glomeruli & glomeruli):
            if glomerulus in cell_type:
                expanded = dict(row)
                expanded["glomerulus"] = glomerulus
                extra_rows.append(expanded)
    if not extra_rows:
        return pd.DataFrame(columns=list(rows.columns) + ["glomerulus"])
    return pd.DataFrame(extra_rows)


def selected_neurons(annotations: pd.DataFrame, glomeruli: set[str]) -> pd.DataFrame:
    rows = []
    uniglomerular_alpn = annotations[
        (annotations["cell_class"] == "ALPN")
        & (annotations["cell_sub_class"] == "uniglomerular")
    ].copy()
    uniglomerular_alpn["glomerulus"] = uniglomerular_alpn["cell_type"].map(
        normalize_glomerulus
    )
    uniglomerular_alpn["source_type"] = "projection"
    rows.append(uniglomerular_alpn[uniglomerular_alpn["glomerulus"].isin(glomeruli)])

    multiglomerular_alpn = annotations[
        (annotations["cell_class"] == "ALPN")
        & (annotations["cell_sub_class"] == "multiglomerular")
    ].copy()
    multiglomerular_alpn["source_type"] = "projection"
    rows.append(expand_multiglomerular_projection_rows(multiglomerular_alpn, glomeruli))

    sensory = annotations[
        (annotations["flow"] == "afferent")
        & (annotations["super_class"] == "sensory")
        & annotations["cell_type"].fillna("").str.match(r"^(ORN|HRN|TRN)_")
    ].copy()
    sensory["glomerulus"] = sensory["cell_type"].map(normalize_glomerulus)
    sensory["source_type"] = "sensory"
    rows.append(sensory[sensory["glomerulus"].isin(glomeruli)])

    selected = pd.concat(rows, ignore_index=True)
    selected = selected[
        [
            "root_id",
            "supervoxel_id",
            "glomerulus",
            "cell_type",
            "hemibrain_type",
            "side",
            "flow",
            "super_class",
            "cell_class",
            "cell_sub_class",
            "fbbt_id",
            "source_type",
        ]
    ].drop_duplicates()
    return selected.sort_values(["glomerulus", "side", "cell_type", "root_id"])


def selected_local_neurons(annotations: pd.DataFrame) -> pd.DataFrame:
    selected = annotations[
        (annotations["side"] == "right")
        & (annotations["flow"] == "intrinsic")
        & (annotations["super_class"] == "central")
        & annotations["cell_class"].isin(LOCAL_NEURON_CLASSES)
    ].copy()
    selected["source_type"] = "local"
    return selected[
        [
            "root_id",
            "supervoxel_id",
            "cell_type",
            "hemibrain_type",
            "side",
            "flow",
            "super_class",
            "cell_class",
            "cell_sub_class",
            "fbbt_id",
            "source_type",
        ]
    ].drop_duplicates().sort_values(["cell_class", "cell_type", "root_id"])


def stable_sample(points: np.ndarray, max_points: int) -> np.ndarray:
    if len(points) <= max_points:
        return points
    key = np.lexsort((points[:, 2], points[:, 1], points[:, 0]))
    step = int(np.ceil(len(points) / max_points))
    return points[key][::step][:max_points]


def crop_by_neuropil(vertices: np.ndarray, bounds: NeuropilBounds) -> np.ndarray:
    keep = np.all((vertices >= bounds.lo) & (vertices <= bounds.hi), axis=1)
    return vertices[keep]


def fetch_neuron_points(
    row: dict[str, str],
    bounds: NeuropilBounds,
) -> tuple[str, str, str, np.ndarray | None, tuple[int, str, str, str, str] | None]:
    root_id = int(row["root_id"])
    glomerulus = row.get("glomerulus", "__local__")
    try:
        neuron = flywire.get_mesh_neuron(root_id)
    except Exception as exc:  # noqa: BLE001
        return (
            glomerulus,
            row["side"],
            row["source_type"],
            None,
            (root_id, glomerulus, row["cell_type"], type(exc).__name__, str(exc)),
        )

    vertices = np.asarray(neuron.vertices, dtype=float)
    cropped = crop_by_neuropil(vertices, bounds)
    if len(cropped) < MIN_POINTS:
        cropped = None
    return glomerulus, row["side"], row["source_type"], cropped, None


def density_mask(
    points: np.ndarray, lo: np.ndarray, spacing: float, shape: np.ndarray
) -> np.ndarray:
    indices = np.floor((points - lo) / spacing).astype(int) + 1
    indices = np.clip(indices, 0, shape - 1)
    counts = np.zeros(tuple(shape), dtype=np.float32)
    np.add.at(counts, (indices[:, 0], indices[:, 1], indices[:, 2]), 1.0)

    density = ndimage.gaussian_filter(counts, sigma=1.0)
    occupied = density[density > 0]
    if len(occupied) == 0:
        return np.zeros(tuple(shape), dtype=bool)

    threshold = max(
        float(np.percentile(occupied, DENSITY_PERCENTILE)),
        float(occupied.max() * DENSITY_MAX_FRACTION),
    )
    mask = density >= threshold
    labels, count = ndimage.label(mask)
    if count == 0:
        return mask

    component_scores = ndimage.sum(density, labels, index=np.arange(1, count + 1))
    keep_label = int(np.argmax(component_scores)) + 1
    mask = labels == keep_label
    return mask


def consensus_surface_from_points(
    sensory_points: np.ndarray,
    projection_points: np.ndarray,
    local_points: np.ndarray | None,
) -> tuple[np.ndarray, np.ndarray] | None:
    if len(sensory_points) < MIN_POINTS or len(projection_points) < MIN_POINTS:
        return None
    sensory_points = stable_sample(sensory_points, 180_000)
    projection_points = stable_sample(projection_points, 180_000)
    points = np.vstack([sensory_points, projection_points])
    lo = points.min(axis=0) - MESH_PADDING_NM
    hi = points.max(axis=0) + MESH_PADDING_NM
    shape = np.ceil((hi - lo) / VOXEL_SIZE_NM).astype(int) + 3
    if np.any(shape < 4):
        return None
    scale = min(1.0, MAX_GRID_SIZE / float(shape.max()))
    spacing = VOXEL_SIZE_NM / scale
    shape = np.ceil((hi - lo) / spacing).astype(int) + 3

    sensory_mask = density_mask(sensory_points, lo, spacing, shape)
    projection_mask = density_mask(projection_points, lo, spacing, shape)
    sensory_mask = ndimage.binary_dilation(sensory_mask, iterations=CONSENSUS_DILATION)
    projection_mask = ndimage.binary_dilation(
        projection_mask, iterations=CONSENSUS_DILATION
    )
    volume = sensory_mask & projection_mask
    if local_points is not None and len(local_points) >= MIN_POINTS:
        keep = np.all((local_points >= lo) & (local_points <= hi), axis=1)
        local_crop = local_points[keep]
        if len(local_crop) >= MIN_POINTS:
            local_mask = density_mask(local_crop, lo, spacing, shape)
            local_mask = ndimage.binary_dilation(local_mask, iterations=LOCAL_DILATION)
            local_volume = volume & local_mask
            if local_volume.sum() >= MIN_POINTS:
                volume = local_volume
    labels, count = ndimage.label(volume)
    if count > 0:
        component_sizes = ndimage.sum(volume, labels, index=np.arange(1, count + 1))
        keep_label = int(np.argmax(component_sizes)) + 1
        volume = labels == keep_label
    volume = ndimage.binary_closing(volume, iterations=1)
    volume = ndimage.binary_fill_holes(volume)
    if volume.sum() < MIN_POINTS:
        return None

    vertices, faces, _, _ = measure.marching_cubes(volume.astype(np.uint8), level=0.5)
    vertices = lo + (vertices - 1.0) * spacing
    return vertices, faces.astype(np.int64)


def write_meshes(
    materials: pd.DataFrame,
    right_surfaces: dict[str, tuple[np.ndarray, np.ndarray]],
) -> None:
    annotated_vertices = pd.read_csv(SOURCE_DIR / "flywire_al_annotated_vertices.csv.gz")
    annotated_faces = pd.read_csv(SOURCE_DIR / "flywire_al_annotated_faces.csv.gz")
    all_vertices = [annotated_vertices]
    face_rows = [annotated_faces]
    point_offset = int(annotated_vertices["PointNo"].max())

    for material in materials.itertuples(index=False):
        glomerulus = str(material.name)
        vertices, faces = right_surfaces[glomerulus]
        point_numbers = np.arange(point_offset + 1, point_offset + len(vertices) + 1)
        all_vertices.append(
            pd.DataFrame(
                {
                    "PointNo": point_numbers,
                    "X": vertices[:, 0],
                    "Y": vertices[:, 1],
                    "Z": vertices[:, 2],
                }
            )
        )
        shifted = faces + point_offset + 1
        face_rows.append(
            pd.DataFrame(
                {
                    "id": int(material.id),
                    "name": glomerulus,
                    "v1": shifted[:, 0],
                    "v2": shifted[:, 1],
                    "v3": shifted[:, 2],
                }
            )
        )
        point_offset += len(vertices)

    if not all_vertices or not face_rows:
        raise RuntimeError("No FlyWire glomerulus surfaces were generated")

    pd.concat(all_vertices, ignore_index=True).to_csv(
        SOURCE_DIR / "flywire_al_vertices.csv.gz",
        index=False,
    )
    pd.concat(face_rows, ignore_index=True).to_csv(
        SOURCE_DIR / "flywire_al_faces.csv.gz",
        index=False,
        quoting=csv.QUOTE_NONNUMERIC,
    )


def update_export_note(digest: str) -> None:
    path = SOURCE_DIR / "natverse_export_versions.txt"
    line = f"flywire glomerulus neuron meshes {digest}"
    if path.exists():
        lines = [
            existing.rstrip("\n")
            for existing in path.read_text(encoding="utf-8").splitlines()
            if not existing.startswith("flywire glomerulus neuron meshes ")
        ]
    else:
        lines = []
    while lines and lines[-1] == "":
        lines.pop()
    lines.extend(["", line])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    materials = material_table()
    glomeruli = set(materials["name"].astype(str))
    annotations = pd.read_csv(ANNOTATION_URL, sep="\t", dtype=str).fillna("")
    selected = selected_neurons(annotations, glomeruli)
    selected.to_csv(SOURCE_DIR / "flywire_glomerulus_mesh_inputs.csv", index=False)
    local_selected = selected_local_neurons(annotations)
    local_selected.to_csv(SOURCE_DIR / "flywire_local_mesh_inputs.csv", index=False)

    bounds = load_neuropil_bounds()
    right = next(bound for bound in bounds if bound.name == "AL_R")
    point_groups: dict[str, dict[str, list[np.ndarray]]] = {
        name: {"sensory": [], "projection": []} for name in glomeruli
    }
    local_chunks: list[np.ndarray] = []
    failures = []

    records = selected[selected["side"] == "right"].to_dict("records")
    records.extend(local_selected.to_dict("records"))
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(fetch_neuron_points, row, right): row
            for row in records
        }
        for index, future in enumerate(as_completed(futures), start=1):
            row = futures[future]
            root_id = row["root_id"]
            glomerulus = row.get("glomerulus", "__local__")
            print(
                f"[{index}/{len(records)}] {glomerulus} {row['cell_type']} {root_id}",
                file=sys.stderr,
            )
            glomerulus, side, source_type, chunk, failure = future.result()
            if failure is not None:
                failures.append(failure)
                continue
            if chunk is None:
                continue
            if source_type == "local":
                local_chunks.append(stable_sample(chunk, LOCAL_MAX_POINTS_PER_NEURON))
            elif side == "right":
                point_groups[glomerulus][source_type].append(chunk)

    right_surfaces: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    local_points = np.vstack(local_chunks) if local_chunks else None
    for index, glomerulus in enumerate(sorted(point_groups), start=1):
        print(f"[surface {index}/{len(point_groups)}] {glomerulus}", file=sys.stderr)
        source_points = point_groups[glomerulus]
        if not source_points["sensory"] or not source_points["projection"]:
            continue
        surface = consensus_surface_from_points(
            np.vstack(source_points["sensory"]),
            np.vstack(source_points["projection"]),
            local_points,
        )
        if surface is not None:
            right_surfaces[glomerulus] = surface

    missing = sorted(glomeruli - set(right_surfaces))
    if missing:
        raise RuntimeError(f"No consensus right-side surface for: {', '.join(missing)}")

    write_meshes(materials, right_surfaces)

    if failures:
        pd.DataFrame(
            failures,
            columns=["root_id", "glomerulus", "cell_type", "error_type", "error"],
        ).to_csv(SOURCE_DIR / "flywire_glomerulus_mesh_failures.csv", index=False)
    else:
        pd.DataFrame(
            columns=["root_id", "glomerulus", "cell_type", "error_type", "error"],
        ).to_csv(SOURCE_DIR / "flywire_glomerulus_mesh_failures.csv", index=False)

    digest_input = (
        selected.to_csv(index=False)
        + "\n"
        + local_selected.to_csv(index=False)
    )
    digest = hashlib.sha256(digest_input.encode()).hexdigest()
    update_export_note(digest)


if __name__ == "__main__":
    main()
