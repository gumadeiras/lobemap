# FlyWire

FlyWire antennal-lobe glomerulus surfaces exported from `hemibrainr`.
The viewer also includes `AL_L` and `AL_R` neuropil meshes from `fafbseg` so
both antennal lobes are visible in the FlyWire coordinate space.

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

The viewer uses source meshes directly and does not draw a fake copy. Use the
mirror controls only as display transforms.

Refresh the tracked `AL_L` and `AL_R` source meshes:

```bash
uv run --with fafbseg python flywire/scripts/export_flywire_neuropils.py
```

Rebuild cache files from the repo root:

```bash
uv run python scripts/regenerate_visual_data.py
```

Primary source:

Schlegel P, et al. `hemibrainr`: code for working with FlyWire and hemibrain
data.
