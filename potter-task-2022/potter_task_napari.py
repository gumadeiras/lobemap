#!/usr/bin/env python3
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import matplotlib.image as mpimg
import napari
from qtpy.QtWidgets import QLabel, QVBoxLayout, QWidget


WORK_DIR = Path(__file__).resolve().parent
SOURCE_DIR = WORK_DIR / "data/source"
DERIVED_DIR = WORK_DIR / "data/derived"
SOURCE_PDF = SOURCE_DIR / "Task-Potter-eLife-Drosophila-Antennal-Lobe-Map-2022.pdf"
PREVIEW_PNG = DERIVED_DIR / "potter_task_2022_map.png"


def render_preview() -> Path:
    if PREVIEW_PNG.exists():
        return PREVIEW_PNG

    pdftoppm = shutil.which("pdftoppm")
    if pdftoppm is None:
        raise RuntimeError("pdftoppm is needed to render the Potter PDF preview")

    DERIVED_DIR.mkdir(parents=True, exist_ok=True)
    output_prefix = PREVIEW_PNG.with_suffix("")
    subprocess.run(
        [
            pdftoppm,
            "-png",
            "-r",
            "300",
            "-singlefile",
            str(SOURCE_PDF),
            str(output_prefix),
        ],
        check=True,
    )
    return PREVIEW_PNG


def load_atlas(viewer: napari.Viewer) -> QWidget:
    viewer.title = "lobemap - Potter Task 2022"
    image = mpimg.imread(render_preview())
    viewer.add_image(image, name="Potter Task 2022 AL map", rgb=image.ndim == 3)
    viewer.dims.ndisplay = 2
    viewer.camera.angles = (0, 0, 0)

    panel = QWidget()
    layout = QVBoxLayout()
    layout.addWidget(QLabel("2D reference map"))
    layout.addWidget(QLabel(SOURCE_PDF.name))
    panel.setLayout(layout)
    return panel


def main() -> None:
    viewer = napari.Viewer(title="lobemap - Potter Task 2022", ndisplay=2)
    panel = load_atlas(viewer)
    viewer.window.add_dock_widget(panel, area="right", name="Potter Task 2022")
    napari.run()


if __name__ == "__main__":
    main()
