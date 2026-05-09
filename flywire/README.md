# FlyWire

FlyWire antennal-lobe glomerulus surfaces. The annotated-side surfaces are kept
from the FlyWire glomerulus mesh. The other side is rebuilt from FlyWire neuron
meshes by keeping the overlap between sensory-neuron arbors and projection-neuron
arbors, with local neurons used as an antennal-lobe mask.

The viewer also includes source `AL_L` and `AL_R` neuropil meshes from
`fafbseg` so both antennal lobes are visible in the FlyWire coordinate space.

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

The tracked glomerulus mesh files include surfaces for both FlyWire antennal
lobes. Left and right surfaces share the same glomerulus ID so the viewer can
show one table row per glomerulus while still placing labels on each side
separately. The mirror controls are display-only transforms.

Refresh the tracked glomerulus source meshes:

```bash
uv run \
  --with fafbseg \
  --with navis \
  --with pytz \
  --with scipy \
  --with scikit-image \
  python flywire/scripts/export_flywire_glomeruli_from_neurons.py
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
- `fafbseg`, for FlyWire source neuron meshes and neuropil meshes.
- `flywire_annotations`, for neuron class, cell type, glomerulus, and side
  annotations.
