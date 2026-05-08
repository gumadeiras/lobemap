# Grabe Atlas Data Notes

This folder contains atlas resources associated with:

Grabe V, Strutz A, Baschwitz A, Hansson BS, Sachse S.
A digital in vivo 3D atlas of the antennal lobe of Drosophila melanogaster.
Journal of Comparative Neurology. 2015;523(3):530-544.
doi:10.1002/cne.23697.

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
