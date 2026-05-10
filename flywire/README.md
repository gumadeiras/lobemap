# FlyWire

FlyWire antennal-lobe glomerulus surfaces. lobemap keeps the annotated reference
glomerulus mesh only.

The viewer also includes source `AL_L` and `AL_R` neuropil meshes from `fafbseg`
so the reference glomeruli can be seen in the FlyWire coordinate space.

Run:

```bash
./lobemap --atlas flywire
```

Source data used by the viewer lives in `data/source/` and should be tracked in
git. Fast cache files are written to `data/derived/` and tracked so the viewer
works from a fresh checkout.

Coordinate validation lives in `data/validation/`. The viewer uses source
columns `Y, Z, X` as Dorsal-Ventral, Anterior-Posterior, and Lateral-Medial
axes, matching the FlyWire Codex coordinate description. `label_extents.csv`
records the rendered voxel span for each glomerulus.

The tracked glomerulus mesh files include the FlyWire reference glomerulus
surfaces. The mirror controls are display-only transforms.

Refresh the tracked reference glomerulus source meshes:

```bash
uv run python flywire/scripts/prepare_flywire_glomeruli.py
```

Refresh the tracked `AL_L` and `AL_R` source meshes:

```bash
uv run --with fafbseg python flywire/scripts/export_flywire_neuropils.py
```

Rebuild cache files from the repo root:

```bash
uv run python scripts/regenerate_visual_data.py
```

Primary sources:

- `hemibrainr`, for receptor, odor-scene, and valence summary tables used as
  metadata.
- FlyWire glomerulus mesh, for the reference glomerulus surfaces.
- `fafbseg`, for FlyWire neuropil meshes.
