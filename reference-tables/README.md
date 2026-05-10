# Reference Tables

Cross-dataset tables for glomerulus names and receptor metadata.

Files:

- `glomerulus_ground_truth.csv`: one row per canonical glomerulus with
  receptors, sensilla, odor scenes, valence, direct line labels, VFB IDs, and
  dataset presence flags.
- `glomerulus_name_reconciliation.csv`: source names mapped to canonical
  glomerulus names, including combined or legacy labels.

Rebuild from source files:

```bash
uv run python reference-tables/scripts/build_glomerulus_ground_truth.py
```

Notes:

- Sensory line columns come from Grabe 2015 Table 1 and the Potter/Task 2022
  summary table.
- Benton 2025 columns come from Dataset EV1 and are kept as source-specific
  receptor, co-receptor, sensillum, neuron-name, agonist, and sensory-scene
  metadata.
- Sensory-organ columns classify sensilla as `antenna`, `maxillary palp`, or
  `arista` from Benton sensillum prefixes and DoOR sensillum types.
- Projection-neuron line columns use the Grabe 2015 supplemental tables. GH146
  comes from Table S1, and ChAT comes from Table S2.
- Valence and odor-scene columns come from the Bates/Schlegel source table.
- VFB identifiers come from the local VFB export.
- Projection-neuron line columns are left blank unless a source directly maps
  that line to a glomerulus. Broad line labels are not filled into every row.
