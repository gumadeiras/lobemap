# Bates Schlegel 2020 Atlas

Interactive glomerulus atlas resources associated with:

Alexander S. Bates, Philipp Schlegel, et al. (2020). Complete Connectomic
Reconstruction of Olfactory Projection Neurons in the Fly Brain. Current
Biology 30(16), 3183-3199.e6. DOI: `10.1016/j.cub.2020.06.042`.

## Layout

- `data/source/`: self-contained Plotly HTML. Static PDF copies are local-only
  and ignored by git.
- `data/derived/`: generated cache files used for fast napari slicing. These
  files are tracked so the viewer works from a fresh checkout, and can be
  rebuilt from source data.
- `slices/`: optional PDF slices generated from the Plotly mesh. These are
  ignored by git.
- `bates_schlegel_napari.py`: napari label-volume viewer used by the main lobemap
  entry point.
- `scripts/slice_glomeruli_atlas.py`: script for regenerating the slices from
  `data/source/glomeruli_atlas_interactive.html`.

## Napari Viewer

```bash
./lobemap --atlas bates-schlegel-2020
```

The viewer uses a generated cache for fast slicing. It displays one label layer,
one per-plane name-anchor layer, and a scrollable checklist. Neuropil is
available as a context label and starts hidden. The cache is tracked in git and
is rebuilt automatically if it is missing.

Views are named by anatomical slice direction:

- Anterior-Posterior
- Dorsal-Ventral
- Lateral-Medial

## Regenerate Slices

Requires Python with `numpy` and `matplotlib`.

```bash
python scripts/slice_glomeruli_atlas.py
```

The script defaults to writing into `slices/`. Use `--out <dir>` for a scratch
output folder.
