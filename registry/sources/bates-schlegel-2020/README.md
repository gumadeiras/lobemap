# Bates & Schlegel 2020

Interactive glomerulus atlas published with:

Bates AS, Schlegel P, et al. Complete Connectomic Reconstruction of Olfactory
Projection Neurons in the Fly Brain. *Current Biology*, 2020;30(16):3183-3199.e6.
doi:10.1016/j.cub.2020.06.042

**Nothing in the registry reads this.** The atlas it carried was removed from the
viewer because Benton 2025's Dataset EV2 revises the same antennal-lobe meshes.
It is kept because the interactive figure is the published artefact and may be
wanted again.

## What is here

- `glomeruli_atlas_interactive.html` — a self-contained Plotly figure with the
  glomerulus meshes embedded in it. This is the atlas.
- `glomeruli_atlas_static.pdf` — the static version of the same figure.
- `scripts/slice_glomeruli_atlas.py` — extracts slices from the Plotly meshes.
  Written against the previous viewer's layout, so treat it as a record of how
  the meshes were read rather than something that runs as-is.
