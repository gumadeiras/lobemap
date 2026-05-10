# Benton 2025

Review resource for the Drosophila olfactory system.

Open Dataset EV2 in lobemap:

```bash
./lobemap --atlas benton-2025
```

Viewer source data:

- Dataset EV2 uses and updates the antennal-lobe meshes from Bates Schlegel
  2020. lobemap keeps it as a separate Benton 2025 viewer because its paper
  slices use a slightly different orientation from the Bates atlas views.
- `data/source/BentonDatasetEV2/DatasetEV2.seg.vtm` is the 3D Slicer
  segmentation index.
- `data/source/BentonDatasetEV2/DatasetEV2.seg/*.vtp` holds the per-glomerulus
  meshes referenced by the segmentation index.
- `data/source/BentonDatasetEV2/DatasetEV2-label_ColorTable.ctbl` provides the
  source labels and colors.
- `data/source/dorsal-ventral.jpg.webp` and
  `data/source/anterior-posterior.png.webp` are paper-view references used to
  check viewer orientation.

Viewer orientation:

- The default view is `Dorsal-Ventral`.
- The Dorsal-Ventral stack is reversed so slice order runs dorsal to ventral,
  matching the paper panels.
- The default Dorsal-Ventral display uses vertical and horizontal mirroring with
  no rotation.
- These settings match the Benton 2025 paper views and should not be assumed to
  be the same orientation as Bates Schlegel 2020.

Derived cache:

- `data/derived/benton_2025_label_volume_256.npz` is generated from the source
  meshes and ignored by git.
- Rebuild derived viewer data with:

```bash
uv run python scripts/regenerate_visual_data.py
```

Local-only source:

- `data/source/benton_2025_drosophila_olfactory_system.pdf` is ignored by git.
- `data/source/44319_2025_476_MOESM2_ESM.xlsx` is Dataset EV1 and feeds the
  reference table.
- Source link is tracked in `../paper_pdf_sources.csv`.

Primary citation:

Benton R, et al. An integrated anatomical, functional and evolutionary view of
the Drosophila olfactory system. 2025.
