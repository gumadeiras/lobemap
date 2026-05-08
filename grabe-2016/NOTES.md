# Grabe Atlas Data Notes

This folder contains atlas resources associated with:

Grabe V, Baschwitz A, Dweck HKM, Lavista-Llanos S, Hansson BS, Sachse S.
Elucidating the Neuronal Architecture of Olfactory Glomeruli in the Drosophila
Antennal Lobe. Cell Reports. 2016;16(12):3401-3413.
doi:10.1016/j.celrep.2016.08.063.

## Source Data

- `invivoALatlas.pdf`
- `invivoALstack.tif`
- `Merged_2-101221a-labels_only_sure_ones_Sensillarcolors.tif`
- `Merged_2-101221a-labels_only_sure_ones_Sensillarcolors.am`
- `220118-glomerular-OBJs.7z`

Paper PDFs are local-only and ignored by git. Source links are tracked in
`../paper_pdf_sources.csv`.

## Label Mapping

- The viewer does not use the PDF directly. It uses the TIFF label volume plus
  the Amira material table for names.
- The TIFF voxel values are zero-based relative to Amira material IDs:
  `voxel_value = amira_id - 1`.
