#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import shutil
from pathlib import Path


WORK_DIR = Path(__file__).resolve().parents[1]
SOURCE_DIR = WORK_DIR / "data/source"


def file_digest(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def update_export_note(digest: str) -> None:
    path = SOURCE_DIR / "natverse_export_versions.txt"
    if path.exists():
        lines = [
            line.rstrip("\n")
            for line in path.read_text(encoding="utf-8").splitlines()
            if not line.startswith("flywire glomerulus ")
        ]
    else:
        lines = []
    while lines and lines[-1] == "":
        lines.pop()
    lines.extend(["", f"flywire glomerulus reference meshes {digest}"])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    vertices = SOURCE_DIR / "flywire_al_annotated_vertices.csv.gz"
    faces = SOURCE_DIR / "flywire_al_annotated_faces.csv.gz"
    if not vertices.exists() or not faces.exists():
        raise FileNotFoundError("Missing FlyWire annotated glomerulus mesh files")

    shutil.copyfile(vertices, SOURCE_DIR / "flywire_al_vertices.csv.gz")
    shutil.copyfile(faces, SOURCE_DIR / "flywire_al_faces.csv.gz")
    update_export_note(file_digest([vertices, faces]))
    print("prepared FlyWire reference glomerulus meshes")


if __name__ == "__main__":
    main()
