#!/usr/bin/env python3
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import matplotlib.image as mpimg
import napari
import numpy as np
from napari.utils.transforms import Affine
from qtpy.QtWidgets import QCheckBox, QLabel, QVBoxLayout, QWidget


WORK_DIR = Path(__file__).resolve().parent
ROOT = WORK_DIR.parent
sys.path.insert(0, str(ROOT / "scripts"))
from ui_helpers import load_master_metadata, make_glomerulus_table  # noqa: E402

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
    image_layer = viewer.add_image(image, name="Potter Task 2022 AL map", rgb=image.ndim == 3)
    viewer.dims.ndisplay = 2
    viewer.camera.angles = (0, 0, 0)
    metadata = load_master_metadata()

    def set_mirror() -> None:
        ndim = 2
        matrix = np.eye(ndim)
        if vertical_checkbox.isChecked():
            matrix[0, 0] = -1.0
        if horizontal_checkbox.isChecked():
            matrix[1, 1] = -1.0
        shape = image.shape[:2]
        center_2d = (np.asarray(shape, dtype=np.float64) - 1.0) / 2.0
        center = np.zeros(ndim, dtype=np.float64)
        center[:2] = center_2d
        translate = center - matrix @ center
        image_layer.affine = Affine(linear_matrix=matrix, translate=translate, ndim=ndim)

    names = sorted(metadata)
    table = make_glomerulus_table(names, set(names), metadata, lambda _name, _checked: None)
    vertical_checkbox = QCheckBox("Mirror vertical")
    horizontal_checkbox = QCheckBox("Mirror horizontal")
    vertical_checkbox.toggled.connect(lambda _checked: set_mirror())
    horizontal_checkbox.toggled.connect(lambda _checked: set_mirror())

    panel = QWidget()
    layout = QVBoxLayout()
    layout.addWidget(QLabel("2D reference map"))
    layout.addWidget(QLabel(SOURCE_PDF.name))
    layout.addWidget(vertical_checkbox)
    layout.addWidget(horizontal_checkbox)
    layout.addWidget(QLabel("Glomeruli"))
    layout.addWidget(table)
    panel.setLayout(layout)
    return panel


def main() -> None:
    viewer = napari.Viewer(title="lobemap - Potter Task 2022", ndisplay=2)
    panel = load_atlas(viewer)
    viewer.window.add_dock_widget(panel, area="right", name="Potter Task 2022")
    napari.run()


if __name__ == "__main__":
    main()
