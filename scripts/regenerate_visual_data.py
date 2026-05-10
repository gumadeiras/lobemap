#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def import_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def regenerate_grabe_materials() -> None:
    grabe = import_module("grabe_regenerate", ROOT / "grabe-2015/al_atlas_napari.py")
    grabe.write_materials_csv(grabe.parse_amira_materials(grabe.AMIRA_LABELS))


def regenerate_bates_cache() -> None:
    bates = import_module(
        "bates_regenerate",
        ROOT / "bates-schlegel-2020/bates_schlegel_napari.py",
    )
    volume = bates.build_label_volume(bates.load_meshes())
    bates.save_volume_cache(volume)


def regenerate_hemibrain_flywire_caches() -> None:
    flywire_prepare = import_module(
        "flywire_prepare",
        ROOT / "flywire/scripts/prepare_flywire_glomeruli.py",
    )
    flywire_prepare.main()

    atlas = import_module(
        "hemibrain_flywire_regenerate",
        ROOT / "scripts/natverse_al_napari.py",
    )
    atlas.WORK_DIR = ROOT / "hemibrain"
    atlas.DATA_DIR = atlas.WORK_DIR / "data"
    atlas.SOURCE_DIR = atlas.DATA_DIR / "source"
    atlas.DERIVED_DIR = atlas.DATA_DIR / "derived"
    hemibrain_volume = atlas.build_label_volume(
        atlas.load_meshes("hemibrain_al_microns"), "hemibrain_al_microns"
    )
    atlas.save_volume_cache("hemibrain_al_microns", hemibrain_volume)

    atlas = import_module(
        "flywire_regenerate",
        ROOT / "scripts/natverse_al_napari.py",
    )
    atlas.WORK_DIR = ROOT / "flywire"
    atlas.DATA_DIR = atlas.WORK_DIR / "data"
    atlas.SOURCE_DIR = atlas.DATA_DIR / "source"
    atlas.DERIVED_DIR = atlas.DATA_DIR / "derived"
    flywire_volume = atlas.build_label_volume(
        atlas.load_meshes("flywire_al"), "flywire_al"
    )
    atlas.save_volume_cache("flywire_al", flywire_volume)


def regenerate_coordinate_validation() -> None:
    validation = import_module(
        "coordinate_validation",
        ROOT / "scripts/write_coordinate_validation.py",
    )
    validation.main()


def regenerate_benton_cache() -> None:
    benton = import_module(
        "benton_regenerate",
        ROOT / "benton-2025/benton_2025_data.py",
    )
    benton.save_volume_cache(benton.build_label_volume(benton.load_meshes()))


def regenerate_potter_preview() -> None:
    source_pdf = (
        ROOT
        / "potter-task-2022/data/source/Task-Potter-eLife-Drosophila-Antennal-Lobe-Map-2022.pdf"
    )
    output_png = ROOT / "potter-task-2022/data/derived/potter_task_2022_map.png"
    pdftoppm = shutil.which("pdftoppm")
    if pdftoppm is None:
        raise RuntimeError("pdftoppm is needed to render the Potter PDF preview")

    output_png.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            pdftoppm,
            "-png",
            "-r",
            "300",
            "-singlefile",
            str(source_pdf),
            str(output_png.with_suffix("")),
        ],
        check=True,
    )


def main() -> None:
    regenerate_grabe_materials()
    regenerate_bates_cache()
    regenerate_hemibrain_flywire_caches()
    regenerate_coordinate_validation()
    regenerate_benton_cache()
    regenerate_potter_preview()
    print("visual data regenerated")


if __name__ == "__main__":
    main()
