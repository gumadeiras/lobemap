# Data Sources

Every atlas and reference volume the viewer can open, and where it came from. `registry/assets.toml` carries the same provenance per asset, machine-readable, and is the authority if the two ever disagree.

Nothing here is redistributed under a license of lobemap's own: the code's MIT License does not cover the data. Each dataset keeps the license and citation requirements of its own source; the "Data licenses" section of the [README](../README.md#data-licenses) lists them, and `registry/assets.toml` records each asset's license with the page that states it. **If you use an atlas, cite the paper it came from.**

Paper PDFs are not tracked, with one exception: Grabe 2015's atlas PDF, which is part of the published atlas rather than the paper. The papers' links are in [`paper-pdf-sources.csv`](../registry/sources/paper-pdf-sources.csv).

## What the viewer opens

Four coordinate spaces, six atlases. A space also carries one reference image, and each EM space its brain neuropils.

| space | atlas | glomeruli | source |
|---|---|---|---|
| FAFB14 | Benton 2025 | 58 | Dataset EV2, ships in `registry/sources/` |
| JRCFIB2018F | neuPrint hemibrain | 58 + 19 | neuPrint `hemibrain:v1.2.1` |
| JRCFIB2018F | Schlegel 2021 S11 | 59 | eLife supplementary file 11 |
| JRCFIB2018F | Schlegel 2021 S12 | 58 | eLife supplementary file 12 |
| JRCFIB2022M | neuPrint male CNS | 58 + 58 | neuPrint `male-cns:v1.0` |
| GRABE | Grabe 2015 | 54 + 54 | Amira label volume, ships in `registry/sources/` |

## Benton 2025 — FAFB14

Folder: [`benton-2025/`](../registry/sources/benton-2025/)

Glomerular segmentation of FAFB, read from the published Slicer scene (`DatasetEV2.seg.vtm`). The names are FAFB's vocabulary; the nomenclature table records how the other atlases map onto them. The meshes are adapted from the FAFB meshes of Bates et al. 2020, not from FlyWire.

The article is CC BY 4.0, and its data, Dataset EV2 included, carry a CC0 1.0 waiver that does not extend to the figures.

- Benton R, et al. *EMBO Reports*, 2025. doi:10.1038/s44319-025-00476-8

## Schlegel 2021 — JRCFIB2018F

Downloaded from the eLife CDN at build time, not tracked. eLife publishes all article content, supplementary files included, under CC BY 4.0:

```
https://cdn.elifesciences.org/articles/66018/elife-66018-supp11-v2.zip
https://cdn.elifesciences.org/articles/66018/elife-66018-supp12-v2.zip
```

Two independent parcellations of the same volume — S11 traced from receptor neurons, S12 from projection neurons — which is why both are kept. The captions of both files name 58 glomeruli (51 olfactory, 7 thermo- and hygrosensory). Supplementary file 11 ships 59 meshes: VM6 comes as three, `VM6l`, `VM6m` and `VM6v`, and VM2 is absent. Verified against a fresh download.

- Schlegel P, Bates AS, et al. *eLife*, 2021. doi:10.7554/eLife.66018

## neuPrint — JRCFIB2018F and JRCFIB2022M

Queried live through `neuprint-python`, so nothing is tracked. Needs `NEUPRINT_APPLICATION_CREDENTIALS`. Both the glomeruli and the whole-brain neuropil set come from the ROI hierarchy; see `registry/data/README.md` for the exact commands.

The dataset version is pinned in `registry/recipes.toml` for every query, not left to the server's default, because the annotations differ between versions: `male-cns:v0.9` exposes only `AL(L)`/`AL(R)` with no glomerular subdivisions at all, so building against it silently yields two ROIs instead of 116.

- hemibrain: https://neuprint.janelia.org — `hemibrain:v1.2.1`; Scheffer LK, et al. *eLife*, 2020. doi:10.7554/eLife.57443. The dataset is CC BY 4.0 ([Janelia](https://www.janelia.org/project-team/flyem/hemibrain)).
- male CNS: https://neuprint-cns.janelia.org — `male-cns:v1.0`; Berg S, et al. *Cell*, 2026. doi:10.1016/j.cell.2026.08.015. The dataset is CC BY 4.0 ([Janelia](https://male-cns.janelia.org/download/)).

Two defects in these sets are in the published data, not introduced here:

- hemibrain `VM2(R)` is a 14 µm³ fragment, where VM2 is 1,342–3,259 µm³ in every other atlas that has one. `registry/checks.toml` records it, so `lobemap check` lists it without failing.
- In the male CNS neuropil set, `AME(L)` is 4,172 µm³ after the watertight repair against 16,608 µm³ for `AME(R)`. The repair log in the asset's metadata cannot say which lost it: its volume changes for open meshes were measured from the world origin, which is meaningless for a mesh with holes (it logged AB(L) and AB(R) as shrinking 85–89% while the repaired AB(R) matches the hemibrain's to 2%). The repair now measures from each mesh's own center.

## Grabe 2015 — GRABE

Folder: [`grabe-2015/`](../registry/sources/grabe-2015/)

A light-microscopy template rather than EM, and an island: no bridging registration connects it to any other space. Three assets come from it — the glomerular meshes, the label volume they were surfaced from, and the confocal stack that serves as its reference image. The meshes are surfaced from the Amira label volume rather than the author-provided OBJ export.

The files are reproduced from the paper and its in vivo atlas. The atlas page at the Max Planck Institute for Chemical Ecology (https://www.ice.mpg.de/232714/vivo-3d-atlas) publishes the atlas PDF and the confocal stack; the article is not open access. Neither states terms for the files, and lobemap grants none: the rights stay with the authors and the publisher.

The label volume has no `VM6`. Its Amira material table names `VM6_left` and `VM6_right`, but neither has a voxel in the published "sure ones" volume, so 54 glomeruli per side are meshed rather than 55. The same table names the material read as `VP2` `VP2_left_VM6andVC6` and `VP2_right_VM6andVC6`, and in affine fits to the male CNS and Schlegel S12 it lies at VM6's position rather than VP2's. The viewer therefore names it `VP2(L) (VM6?)` and `VP2(R) (VM6?)`, from the `[uncertain]` table in `registry/atlases/grabe2015.toml`; its nomenclature row stays VP2.

- Grabe V, Strutz A, Baschwitz A, Hansson BS, Sachse S. *Journal of Comparative Neurology*, 2015. doi:10.1002/cne.23697
- Grabe V, et al. *Cell Reports*, 2016. doi:10.1016/j.celrep.2016.08.063

## FAFB neuropils

Whole-brain neuropil meshes released with FlyWire, via [`fafbseg-py`](https://github.com/navis-org/fafbseg-py): neuropils made for the JFRC2 template brain and mapped into FlyWire space, according to fafbseg's documentation. FlyWire public data is CC BY-NC 4.0 ([guidelines](https://flywire.ai/guidelines)).

- Dorkenwald S, et al. *Nature*, 2024. doi:10.1038/s41586-024-07558-y

These are coarse — about 394 vertices and 7 µm facets — and visibly so beside the neuPrint sets. Warped male CNS meshes were tried as a replacement and reverted: smoother, but a worse fit to FAFB.

## Virtual neuropil stains

Not an atlas: a synthetic reference image, one per EM space. Presynapse density binned at 0.25 µm and blurred with a 450 nm Gaussian, which reads like an nc82 antibody stain while being computed natively in each volume rather than warped in from light microscopy. Built from the published synapse releases, about 20 GB of input that is not kept:

| space | source | license |
|---|---|---|
| JRCFIB2018F | `gs://neuroglancer-janelia-flyem-hemibrain/v1.2/synapses/by_id/` — Scheffer LK, et al. *eLife*, 2020. doi:10.7554/eLife.57443 | CC BY 4.0 |
| JRCFIB2022M | `gs://flyem-male-cns/v1.0/connectome-data/flat-connectome/syn-points-male-cns-v1.0-minconf-0.5.feather` — Berg S, et al. *Cell*, 2026. doi:10.1016/j.cell.2026.08.015 | CC BY 4.0 |
| FAFB14 | FlyWire v783 Princeton synapse table, `fafb_v783_princeton_synapse_table.csv.gz` — Yu SC, et al. New synapse detection in the whole-brain connectome of *Drosophila*. *bioRxiv*, 2025. doi:10.1101/2025.07.11.664377; on the FlyWire reconstruction of Dorkenwald S, et al. *Nature*, 2024. doi:10.1038/s41586-024-07558-y | CC BY-NC 4.0 |

No confidence threshold is applied to any of them. The male CNS file is already filtered to confidence 0.5, as its name says; the hemibrain shards carry no confidence field; and the Princeton table has no confidence or score column. The published FAFB stain's metadata records `confidence_threshold: 0.5`, which the build wrote without applying.

The Princeton coordinates are used as they come, without a FlyWire-to-FAFB14 bridge. Fitting the stain to the Benton meshes by a rigid shift gives a best offset under 1 µm, about the stain's resolution; the fit is shallow, so it bounds the offset rather than measuring it. The FlyWire-to-FAFB14 transform itself was not run.
