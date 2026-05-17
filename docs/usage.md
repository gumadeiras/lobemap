# How To Use lobemap

## Requirements

- `uv`
- A desktop environment that can open napari / Qt windows

Python and package dependencies are managed by `uv` from `pyproject.toml`.

## First Run

Install from PyPI and start the viewer:

```bash
pip install lobemap
lobemap
```

Or install dependencies from a source checkout and start the viewer:

```bash
uv sync
./lobemap
```

Open one atlas directly:

```bash
./lobemap --atlas benton-2025
```

## Controls

The right panel has the main controls.

- `Atlas`: choose the dataset.
- `View`: choose the slice direction.
- `Rotation`: rotate the current view.
- `Mirror vertical` and `Mirror horizontal`: flip the display.
- `Line preset`: show the glomeruli marked for a driver line in the reference table, such as `Orco-GAL4` or `GH146-GAL4`.
- The glomerulus table: check rows to show or hide glomeruli.

Benton 2025 opens to the paper-matched `Dorsal-Ventral` view. Its stack runs dorsal to ventral by default, and the initial display uses vertical and horizontal mirroring with no rotation.

The table has three columns:

- `glomerulus`
- `receptor`
- `sensilla`

Labels appear on slices where a glomerulus is present. In FlyWire, labels are placed on the reference antennal lobe.

JRC2018Unisex opens as a whole-brain template with VFB ROI masks.

## Generated Data

Generated cache files live in `data/derived/` folders. They are tracked so the viewer works from a fresh checkout or PyPI install without rebuilding caches. The package includes runtime source tables/volumes plus tracked `data/derived/` and `data/validation/` caches needed by the installed viewer. Some viewers can rebuild their cache on first load if a file is missing; rebuild all generated visual data after source-data changes with:

```bash
uv run python scripts/regenerate_visual_data.py
```

This regenerates Grabe material labels, Bates Schlegel 2020, hemibrain, FlyWire, and Benton 2025 label-volume caches, FlyWire coordinate validation, and the Potter Task 2022 map preview. The Potter preview step needs `pdftoppm`.
