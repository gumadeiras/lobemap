#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

import pandas as pd
from fafbseg import flywire


WORK_DIR = Path(__file__).resolve().parents[1]
SOURCE_DIR = WORK_DIR / "data/source"
SOURCE_DIR.mkdir(parents=True, exist_ok=True)

NEUROPILS = {
    "AL_L": "#8DD3C7",
    "AL_R": "#80B1D3",
}


def main() -> None:
    volumes = flywire.get_neuropil_volumes(list(NEUROPILS))
    materials = []
    vertices = []
    faces = []
    point_offset = 0

    for label_id, volume in enumerate(volumes, start=1001):
        name = str(volume.name)
        points = pd.DataFrame(volume.vertices, columns=["X", "Y", "Z"])
        point_numbers = range(point_offset + 1, point_offset + len(points) + 1)
        points.insert(0, "PointNo", list(point_numbers))
        vertices.append(points)

        face_rows = pd.DataFrame(volume.faces, columns=["v1", "v2", "v3"]) + point_offset + 1
        face_rows.insert(0, "name", name)
        face_rows.insert(0, "id", label_id)
        faces.append(face_rows)

        materials.append({"id": label_id, "name": name, "col": NEUROPILS[name]})
        point_offset += len(points)

    pd.DataFrame(materials).to_csv(
        SOURCE_DIR / "flywire_al_neuropils_materials.csv",
        index=False,
    )
    pd.concat(vertices, ignore_index=True).to_csv(
        SOURCE_DIR / "flywire_al_neuropils_vertices.csv.gz",
        index=False,
    )
    pd.concat(faces, ignore_index=True).to_csv(
        SOURCE_DIR / "flywire_al_neuropils_faces.csv.gz",
        index=False,
    )


if __name__ == "__main__":
    main()
