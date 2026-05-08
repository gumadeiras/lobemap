# FlyWire

FlyWire antennal-lobe glomerulus surfaces exported from `hemibrainr`.

Run:

```bash
./lobemap --atlas flywire
```

Source data used by the viewer lives in `data/source/` and should be tracked in
git. Fast cache files are written to `data/derived/` and ignored by git.

Coordinate validation lives in `data/validation/`. The viewer uses source
columns `Y, Z, X` as Dorsal-Ventral, Anterior-Posterior, and Lateral-Medial
axes, matching the FlyWire Codex coordinate description. `label_extents.csv`
records the rendered voxel span for each glomerulus.

The viewer uses the source mesh directly and does not synthesize a second
antennal lobe. Use the mirror controls only as display transforms.

Rebuild cache files from the repo root:

```bash
uv run python scripts/regenerate_visual_data.py
```

Primary source:

Schlegel P, et al. `hemibrainr`: code for working with FlyWire and hemibrain
data.
