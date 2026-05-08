#!/usr/bin/env python3
from __future__ import annotations

import csv
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DATASETS = {
    "hemibrain": {
        "stem": "hemibrain_al_microns",
        "units": "microns",
        "axes": [
            ("X", "Lateral-Medial", "inferred from hemibrain mesh convention", ""),
            (
                "Y",
                "Anterior-Posterior",
                "documented by hemibrainr",
                "https://rdrr.io/github/flyconnectome/hemibrainr/man/hemibrain_al.surf.html",
            ),
            ("Z", "Dorsal-Ventral", "inferred from hemibrain mesh convention", ""),
        ],
        "viewer_axis_columns": ("Z", "Y", "X"),
    },
    "flywire": {
        "stem": "flywire_al",
        "units": "nanometers",
        "axes": [
            (
                "X",
                "Lateral-Medial",
                "documented by FlyWire Codex",
                "https://codex.flywire.ai/faq?dataset=fafb",
            ),
            (
                "Y",
                "Dorsal-Ventral",
                "documented by FlyWire Codex",
                "https://codex.flywire.ai/faq?dataset=fafb",
            ),
            (
                "Z",
                "Anterior-Posterior",
                "documented by FlyWire Codex",
                "https://codex.flywire.ai/faq?dataset=fafb",
            ),
        ],
        "viewer_axis_columns": ("Y", "Z", "X"),
    },
}
VIEWER_AXIS_NAMES = ("Dorsal-Ventral", "Anterior-Posterior", "Lateral-Medial")


def write_dataset_validation(dataset: str, config: dict[str, object]) -> None:
    source_dir = ROOT / dataset / "data/source"
    out_dir = ROOT / dataset / "data/validation"
    out_dir.mkdir(parents=True, exist_ok=True)

    stem = str(config["stem"])
    vertices = pd.read_csv(source_dir / f"{stem}_vertices.csv.gz")
    viewer_axis_columns = tuple(config["viewer_axis_columns"])
    viewer_axis_by_column = {
        column: (axis_index, VIEWER_AXIS_NAMES[axis_index])
        for axis_index, column in enumerate(viewer_axis_columns)
    }

    rows = []
    for source_column, anatomical_axis, evidence, evidence_url in config["axes"]:
        values = vertices[source_column]
        viewer_axis_index, viewer_axis_name = viewer_axis_by_column[source_column]
        rows.append(
            {
                "source_column": source_column,
                "anatomical_axis": anatomical_axis,
                "viewer_axis_index": viewer_axis_index,
                "viewer_axis_name": viewer_axis_name,
                "min": f"{values.min():.6f}",
                "max": f"{values.max():.6f}",
                "mean": f"{values.mean():.6f}",
                "units": config["units"],
                "evidence": evidence,
                "evidence_url": evidence_url,
            }
        )

    with (out_dir / "coordinate_axes.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    for dataset, config in DATASETS.items():
        write_dataset_validation(dataset, config)


if __name__ == "__main__":
    main()
