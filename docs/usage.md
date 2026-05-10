# How To Use lobemap

## Requirements

- `uv`
- A desktop environment that can open napari / Qt windows

Python and package dependencies are managed by `uv` from `pyproject.toml`.

## First Run

Install dependencies and start the viewer:

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
- The glomerulus table: check rows to show or hide glomeruli.

Benton 2025 opens to the paper-matched `Dorsal-Ventral` view. Its stack runs
dorsal to ventral by default, and the initial display uses vertical and
horizontal mirroring with no rotation. The first load builds a derived
label-volume cache from the source segmentation meshes; later loads use the
cache.

The table has three columns:

- `glomerulus`
- `receptor`
- `sensilla`

Labels appear on slices where a glomerulus is present. In FlyWire, labels are
placed on the reference antennal lobe.

JRC2018Unisex opens as a whole-brain template with VFB ROI masks.

Generated cache files live in `data/derived/` folders. They are not tracked in
git. Rebuild them with:

```bash
uv run python scripts/regenerate_visual_data.py
```
