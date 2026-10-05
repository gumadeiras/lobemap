# The brains and atlases

This page describes the four brains and six glomerular atlases in lobemap, which atlas fits which comparison, and the known gaps in the published data.

## Terms

- A *glomerulus* (plural *glomeruli*) is one of the small, round compartments of the antennal lobe (AL).
- A *glomerular atlas* is a published parcellation of the AL: a 3D mesh for each glomerulus, with its name.
- A *coordinate space* is one brain volume and its coordinates. Every atlas native to a space was drawn in that volume, so they line up and can be drawn over each other. The viewer calls a space a *brain*. Commands name it by its id, such as `FAFB14`.
- A *neuropil* is a named region of the brain, such as the antennal lobe or the mushroom body calyx.

## What is included

| space | atlas | glomeruli |
|---|---|---|
| FAFB14 | [Benton 2025](https://doi.org/10.1038/s44319-025-00476-8) (Dataset EV2) | 58 |
| JRCFIB2018F (hemibrain) | neuPrint [hemibrain](https://doi.org/10.7554/eLife.57443) | 58 + 19 |
| JRCFIB2018F | [Schlegel 2021](https://doi.org/10.7554/eLife.66018) S11, from receptor neurons | 59 |
| JRCFIB2018F | [Schlegel 2021](https://doi.org/10.7554/eLife.66018) S12, from projection neurons | 58 |
| JRCFIB2022M (male CNS) | neuPrint [male CNS](https://doi.org/10.1016/j.cell.2026.08.015) | 58 + 58 |
| GRABE | [Grabe 2015](https://doi.org/10.1002/cne.23697) | 54 + 54 |

Two numbers are the right lobe and the left lobe. The neuPrint hemibrain has 58 glomeruli on the right and 19 on the left. Benton 2025 covers the left lobe only, and Schlegel 2021 the right lobe only.

The viewer opens one space at a time. A space holds every atlas native to it at once, together with its reference image and, in the three EM spaces, its neuropil geometry. EM is electron microscopy. So the parcellations of one volume can be drawn over each other.

Glomerulus names are scoped to a space. So switching space may change both the list of glomeruli and their colors.

## Which atlas to use

Which one to reach for depends on what you are comparing against.

**GRABE** is the only atlas built from an intact, living brain. It was imaged in vivo rather than dissected and fixed. So its glomerular shapes and the geometry of its reference stack are the closest match to in vivo imaging data. The reference stack is `elav-nSyb::DsRed`, not nc82. It is also the oldest of the six atlases, and it predates revisions to the fine structure of a few glomeruli.

**FAFB14** is the FAFB volume, which FlyWire also reconstructs. It is a complete female brain, dissected and chemically fixed. Benton 2025, [based on Bates 2020](https://doi.org/10.1016/j.cub.2020.06.042), annotates its left AL comprehensively and to current nomenclature. The right AL is unannotated.

**JRCFIB2018F** (the hemibrain) is a dissected, fixed female brain. Three independent annotations cover its right AL, and one of them also covers a subset of the left AL. Even so, the right AL is partially truncated: some of its 58 glomeruli extend past the imaged volume. All of the hemibrain atlases have a few glomeruli with holes or with several separate pieces.

**JRCFIB2022M** (the male CNS) has complete, current annotations for both hemispheres. Its meshes are of variable quality, and several glomeruli have holes or several pieces. The specimen is male rather than female, which may subtly change the shape of a few glomeruli. Like the other EM volumes, it is dissected and fixed.

## Reference images and neuropils

Each space also carries one reference image, and each EM space carries its brain neuropils.

- **GRABE** is light microscopy and has no neuropil meshes. Its reference image is its own confocal stack.
- **The three EM spaces** show a *virtual neuropil stain*. It is the density of predicted presynapses, binned and blurred into an image that reads like an nc82 antibody stain. It is computed natively in each volume, not warped in from light microscopy.

[Data sources](data-sources.md#virtual-neuropil-stains) says how the stains are built.

## Known gaps in the published data

Three gaps in the published data are worth knowing before you compare atlases.

**The neuPrint hemibrain `VM2(R)` is effectively missing.** It is counted in the table above, but it is a 14 µm³ fragment. VM2 is 1,342–3,259 µm³ in every other atlas that has one. Schlegel S12 has a complete VM2 in the same volume. `lobemap check` lists it as a known defect, from [`registry/checks.toml`](../registry/checks.toml).

**Grabe 2015 has no `VM6`.** Its Amira material table names VM6 on both sides. But the published label volume ("sure ones" only) has no voxels for either side. So 54 glomeruli per side are meshed, not 55.

The same table names the material that lobemap reads as `VP2` `VP2_left_VM6andVC6` and `VP2_right_VM6andVC6`. In affine fits to the male CNS and to Schlegel S12, it lies at VM6's position, not VP2's. So Grabe's `VP2` may be VM6. The viewer names it `VP2 (VM6?)` in the table and on the slice, and the name's tooltip gives each side's reason. [`registry/nomenclature.csv`](../registry/nomenclature.csv) still maps it to VP2.

**The male CNS `AME(L)` is incomplete.** In the male CNS neuropil set, `AME(L)` is about a quarter of the volume of `AME(R)`: 4,172 against 16,608 µm³ after the watertight repair. Treat it as incomplete. The source mesh is not kept, so it is not known whether the ROI or the repair lost the rest.

[Data sources](data-sources.md) has more detail on each atlas, and on what is done to the meshes before the viewer opens them.
