# Reference Tables

Cross-dataset tables for glomerulus names and receptor metadata.

Files:

- `glomerulus_ground_truth.csv`: one row per canonical glomerulus with
  receptors, sensilla, odor scenes, valence, line labels, VFB IDs, and dataset
  presence flags.
- `glomerulus_name_reconciliation.csv`: source names mapped to canonical
  glomerulus names, including combined or legacy labels.

Rebuild from source files:

```bash
uv run python reference-tables/scripts/build_glomerulus_ground_truth.py
```

Notes:

- Sensory line columns come from the Potter/Task 2022 summary table.
- Valence and odor-scene columns come from the Bates/Schlegel source table.
- VFB identifiers come from the local VFB export.
- PN line labels are included as broad reference labels, not per-glomerulus
  coverage calls.
