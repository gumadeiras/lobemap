#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

import napari
from qtpy.QtWidgets import (
    QComboBox,
    QLabel,
    QVBoxLayout,
    QWidget,
)


ROOT = Path(__file__).resolve().parent
ATLASES = {
    "grabe-2016": {
        "label": "Grabe 2016",
        "module": ROOT / "grabe-2016/al_atlas_napari.py",
    },
    "bates-schlegel-2020": {
        "label": "Bates Schlegel 2020",
        "module": ROOT / "bates-schlegel-2020/bates_schlegel_napari.py",
    },
    "hemibrain": {
        "label": "Hemibrain",
        "module": ROOT / "hemibrain/hemibrain_napari.py",
    },
    "flywire": {
        "label": "FlyWire",
        "module": ROOT / "flywire/flywire_napari.py",
    },
    "door": {
        "label": "DoOR 2D",
        "module": ROOT / "door/door_napari.py",
    },
    "potter-task-2022": {
        "label": "Potter Task 2022",
        "module": ROOT / "potter-task-2022/potter_task_napari.py",
    },
}


def import_loader(module_path: Path):
    spec = importlib.util.spec_from_file_location(module_path.stem, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot import atlas module: {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.load_atlas


def clear_layout(layout: QVBoxLayout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.setParent(None)
            widget.deleteLater()


def main() -> None:
    parser = argparse.ArgumentParser(prog="lobemap", description="Open lobemap in napari.")
    parser.add_argument("--atlas", choices=sorted(ATLASES), default="grabe-2016")
    args = parser.parse_args()

    viewer = napari.Viewer(title="lobemap", ndisplay=2)
    atlas_controls = QVBoxLayout()
    active_slug: str | None = None

    selector = QComboBox()
    for slug, config in ATLASES.items():
        selector.addItem(config["label"], slug)
    selector.setCurrentIndex(list(ATLASES).index(args.atlas))

    panel = QWidget()
    layout = QVBoxLayout()
    layout.addWidget(QLabel("Atlas"))
    layout.addWidget(selector)
    layout.addLayout(atlas_controls)
    panel.setLayout(layout)
    viewer.window.add_dock_widget(panel, area="right", name="Atlas")

    def load_selected() -> None:
        nonlocal active_slug
        slug = selector.currentData()
        if slug == active_slug:
            return
        viewer.layers.clear()
        clear_layout(atlas_controls)
        load_atlas = import_loader(ATLASES[slug]["module"])
        atlas_panel = load_atlas(viewer, **ATLASES[slug].get("kwargs", {}))
        atlas_controls.addWidget(atlas_panel)
        active_slug = slug

    selector.currentIndexChanged.connect(lambda _index: load_selected())

    load_selected()
    napari.run()


if __name__ == "__main__":
    main()
