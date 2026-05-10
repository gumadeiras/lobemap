# AL atlas napari viewer

Run:

```bash
./lobemap --atlas grabe-2015
```

What it opens:

- `data/source/invivoALstack.tif` as the grayscale image stack.
- `data/source/Merged_2-101221a-labels_only_sure_ones_Sensillarcolors.tif` as
  the label volume.
- Amira material names parsed from `data/source/`.
- A control panel with orientation controls and a scrollable
  checklist grouped by glomerulus name. Left/right hemisphere entries with the
  same short name share one checkbox.
- A `slice name anchors` points layer with text labels at each glomerulus'
  centroid on every z-slice where that glomerulus is present.

Use:

- Move the slider to slice through the atlas.
- Use `View` to switch between Dorsal-Ventral, Anterior-Posterior, and
  Lateral-Medial views. The original source stack previously labeled
  Anterior-Posterior in this viewer is the Dorsal-Ventral view.
- Use the three rotation spinboxes to rotate around the displayed Z/slice,
  Y/vertical, and X/horizontal axes.
- Toggle `slice name anchors` in the layer list to show/hide on-slice names.
- Check/uncheck glomerulus groups to show/hide them. `Show all` and `Show none`
  set the full list at once.
- Select `glomerulus labels`, then hover a region to see its label ID and name in
  the napari status bar and right-side panel.
- Press napari's 2D/3D button to switch between slice view and 3D rendering.

Notes:

- This uses the label-volume TIF and Amira material names, not the PDF viewer.
- Rotation uses napari layer transforms, so it does not rewrite/resample the
  full volume on every spinbox change.
- The TIF voxel values are zero-based relative to Amira material IDs:
  `voxel_value = amira_id - 1`. For example, voxel `4` is `DA1_left_Or67d`.
- Source data used by the viewer lives in `data/source/`.
- Paper PDFs are local-only and ignored by git. Source links are tracked in
  `../paper_pdf_sources.csv`.

## Source data

The Grabe atlas files are:

- `data/source/invivoALatlas.pdf`: original interactive 3D PDF, local-only and
  tracked as atlas source data.
- `data/source/invivoALstack.tif`: grayscale in vivo AL image stack.
- `data/source/Merged_2-101221a-labels_only_sure_ones_Sensillarcolors.tif`:
  label volume.
- `data/source/Merged_2-101221a-labels_only_sure_ones_Sensillarcolors.am`:
  Amira material table used for label names and colors.
- `data/source/220118-glomerular-OBJs.7z`: author-provided OBJ exports.
- `data/source/grabe_2015_sensory_line_expression.csv`: extracted Table 1
  Orco-GAL4 innervation calls for the reference table.

Primary atlas citation:

Grabe V, Strutz A, Baschwitz A, Hansson BS, Sachse S.
A digital in vivo 3D atlas of the antennal lobe of Drosophila melanogaster.
Journal of Comparative Neurology. 2015;523(3):530-544.
doi:10.1002/cne.23697.

Related citation:

Grabe V, Baschwitz A, Dweck HKM, Lavista-Llanos S, Hansson BS, Sachse S.
Elucidating the Neuronal Architecture of Olfactory Glomeruli in the Drosophila
Antennal Lobe. Cell Reports. 2016;16(12):3401-3413.
doi:10.1016/j.celrep.2016.08.063.
