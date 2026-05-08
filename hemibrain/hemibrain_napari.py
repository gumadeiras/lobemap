#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import napari


WORK_DIR = Path(__file__).resolve().parent
ROOT = WORK_DIR.parent
COMMON = ROOT / "scripts/natverse_al_napari.py"


def import_common():
    spec = importlib.util.spec_from_file_location("natverse_al_napari", COMMON)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot import {COMMON}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_atlas(viewer: napari.Viewer):
    common = import_common()
    return common.load_atlas(
        viewer,
        WORK_DIR,
        "hemibrain_al_microns",
        "Hemibrain",
        default_mirror_vertical=True,
    )


def main() -> None:
    viewer = napari.Viewer(title="lobemap - Hemibrain", ndisplay=2)
    panel = load_atlas(viewer)
    viewer.window.add_dock_widget(panel, area="right", name="Hemibrain")
    napari.run()


if __name__ == "__main__":
    main()
