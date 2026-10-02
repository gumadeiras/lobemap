# Grabe 2015

An in vivo light-microscopy atlas of the antennal lobe:

Grabe V, Strutz A, Baschwitz A, Hansson BS, Sachse S. A digital in vivo 3D atlas
of the antennal lobe of Drosophila melanogaster. *Journal of Comparative
Neurology*, 2015;523(3):530-544. doi:10.1002/cne.23697

Grabe V, et al. Elucidating the Neuronal Architecture of Olfactory Glomeruli in
the Drosophila Antennal Lobe. *Cell Reports*, 2016.
doi:10.1016/j.celrep.2016.08.063

Builds all three GRABE assets: `grabe2015_glomeruli`, `grabe2015_labels` and
`grabe2015_stack`.

## What is here

- `Merged_2-101221a-labels_only_sure_ones_Sensillarcolors.tif` — the label
  volume. The glomerulus meshes are surfaced from this rather than from the
  OBJ export; `registry/assets.toml` says why.
- `Merged_2-101221a-labels_only_sure_ones_Sensillarcolors.am` — the Amira
  material table, which supplies the names.
- `invivoALstack.tif` — the confocal stack, this space's reference image.
- `220118-glomerular-OBJs.7z` — the published OBJ export. Not used.
- `invivoALatlas.pdf` — the atlas document.
- `grabe_2015_pn_expression.csv`, `grabe_2015_sensory_line_expression.csv` —
  supplemental expression tables.
- `s1.png`, `s1_cont.png`, `s2.png` — extracted supplemental table images.

## Label mapping

TIFF voxel values are zero-based against the Amira material ids:
`voxel_value = amira_id - 1`. Both TIFFs are (119, 514, 513) in z, y, x, so
they share a voxel grid.
