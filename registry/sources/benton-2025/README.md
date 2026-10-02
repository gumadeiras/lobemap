# Benton 2025

Glomerular segmentation of FAFB, published as Dataset EV2 with:

Benton R, et al. An integrated anatomical, functional and evolutionary view of
the Drosophila olfactory system. *EMBO Reports*, 2025.
doi:10.1038/s44319-025-00476-8

Builds `benton2025_glomeruli`, the FAFB14 atlas.

## What is here

- `BentonDatasetEV2/DatasetEV2.seg.vtm` — the 3D Slicer segmentation index,
  and the file the recipe reads.
- `BentonDatasetEV2/DatasetEV2.seg/*.vtp` — the per-glomerulus meshes it
  references.
- `BentonDatasetEV2/DatasetEV2-label_ColorTable.ctbl` — source labels and
  colours.
- `BentonDatasetEV2/DatasetEV2-label.nrrd` — the label volume. Not used: the
  atlas is surfaced from the meshes above.
- `44319_2025_476_MOESM2_ESM.xlsx` — Dataset EV1.
- `44319_2025_476_MOESM3_ESM.zip` — Dataset EV3.
- `*.webp`, `*.jpg.webp` — figure panels, kept as an orientation reference.

Dataset EV2 revises the antennal-lobe meshes of Bates & Schlegel 2020, which is
why that atlas was removed from the viewer rather than shown alongside.
