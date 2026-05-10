# Hemibrain

Hemibrain antennal-lobe glomerulus surfaces exported from `hemibrainr`.

Run:

```bash
./lobemap --atlas hemibrain
```

Source data used by the viewer lives in `data/source/` and should be tracked in
git. Fast cache files are written to `data/derived/` and tracked so the viewer
works from a fresh checkout.

Coordinate validation lives in `data/validation/`. The viewer uses source
columns `Z, Y, X` as Dorsal-Ventral, Anterior-Posterior, and Lateral-Medial
axes. The anterior-posterior `Y` axis is documented by `hemibrainr`; the other
two axes follow the hemibrain mesh convention used by the source surface.
`label_extents.csv` records the rendered voxel span for each glomerulus.

Rebuild cache files from the repo root:

```bash
uv run python scripts/regenerate_visual_data.py
```

Primary source:

Schlegel P, et al. `hemibrainr`: code for working with Janelia FlyEM hemibrain
data.
