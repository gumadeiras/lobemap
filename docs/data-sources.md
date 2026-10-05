# Data Sources

This document records where each dataset lobemap ships came from, what is done to it before the viewer opens it, and how to obtain it. `registry/assets.toml` carries the same provenance per asset in machine-readable form, and is the authority if the two ever disagree.

Nothing here is redistributed under a license of lobemap's own: the code's MIT License does not cover the data. Each dataset keeps the license and citation requirements of its own source; the "Data licenses" section of [Data](data.md#data-licenses) lists them, and `registry/assets.toml` records each asset's license with the page that states it. **If you use an atlas, cite the paper it came from.**

Paper PDFs are not tracked, with one exception: Grabe 2015's atlas PDF, which is part of the published atlas rather than the paper. The papers' links are in [`paper-pdf-sources.csv`](../registry/sources/paper-pdf-sources.csv).

## Getting the data

The viewer does not read the published sources directly. Each one is ingested once into a container — a compressed `.npz` of meshes or a Zarr volume — and those containers are what ship. There are fourteen, 2.5 GB in total, attached to the `data-v1` release rather than committed:

```bash
lobemap fetch
```

Of that total, 2.4 GB is the three virtual neuropil stains. Everything else — all six atlases, the neuropil sets and the Grabe confocal stack — is 76 MB:

```bash
lobemap fetch --nostains
```

`registry/manifest.toml` is the authority on where the containers live and what they should contain. It pins the sha256 of each uploaded file, and for each Zarr store a digest of its content on disk, so a copy can be verified without being trusted:

```bash
lobemap fetch --check
```

That reports what is present, what is missing and what fails its check, and downloads and writes nothing. If you host the containers elsewhere, `--base-url` overrides the location while still checking against the same hashes.

## What is done to the data

Every container is built by a recipe in `registry/recipes.toml`, and the processing below is applied on the way in. None of it is reversible from the container, so it is worth knowing before measuring anything from these meshes.

**Units.** All geometry is stored in micrometers. The conversion factor is taken from the source, never deduced from the result: neuPrint states its voxel grid in the dataset's `:Meta` node, and for formats that cannot carry units — OBJ, VTP — the recipe declares `source_units` alongside where that declaration comes from.

**Mesh repair.** Source meshes are made watertight, because an open shell cannot support the inside/outside test the viewer's containment checks depend on. Holes are filled, duplicate vertices merged, and stray fragments below 1 µm³ dropped. This changes geometry. How much varies by atlas:

| atlas | already watertight | repaired | volume changed by at most |
|---|---|---|---|
| Benton 2025 | 31 of 58 | 27 | 0% |
| neuPrint hemibrain | 76 of 77 | 1 | 0% |
| Schlegel 2021 S11 | 0 of 59 | 59 | 0% |
| Schlegel 2021 S12 | 0 of 58 | 58 | 0% |
| neuPrint male CNS | 96 of 116 | 20 | 0.06% |
| Grabe 2015 | 108 of 108 | 0 | — |

What the repair does not do is remove a tunnel. Some glomeruli arrive from their source enclosing one, so that the surface is a torus rather than a sphere, and others arrive as several disconnected pieces; both survive. Counting each glomerulus once, that is 1 of 58 in Benton, 4 of 77 in the neuPrint hemibrain, 4 of 59 in S11, 6 of 58 in S12, 9 of 116 in the male CNS and 1 of 108 in Grabe. These are properties of the published meshes, and they affect the surfaces only — volumes and centroids are sound.

**Names.** Each atlas keeps its published glomerulus names, with one exception: neuPrint's `AL-` neuropil qualifier is dropped, so `AL-DA1(R)` is stored as `DA1(R)`. The nomenclature table records how every atlas's names map onto its space's vocabulary.

**Selection.** The male CNS neuropil set is cut to the brain, built from the `CentralBrain` and `Optic` branches of the ROI hierarchy, so no ventral nerve cord or cervical connective ROI enters. The hemibrain has no such branches and nothing is removed there.

## Benton 2025 — FAFB14

Folder: [`benton-2025/`](../registry/sources/benton-2025/)

Glomerular segmentation of FAFB, read from the published 3D Slicer scene (`DatasetEV2.seg.vtm`) and tracked in this repository. Delivered in Slicer's RAS convention and converted to FAFB14's. The meshes are adapted from the FAFB meshes of Bates et al. 2020, not from FlyWire.

The article is CC BY 4.0, and its data, Dataset EV2 included, carry a CC0 1.0 waiver that does not extend to the figures.

- Benton R, et al. *EMBO Reports*, 2025. doi:10.1038/s44319-025-00476-8

## Schlegel 2021 — JRCFIB2018F

Two independent parcellations of the hemibrain, S11 traced from receptor neurons and S12 from projection neurons. Downloaded from the eLife CDN at build time rather than tracked; eLife publishes all article content, supplementary files included, under CC BY 4.0:

```
https://cdn.elifesciences.org/articles/66018/elife-66018-supp11-v2.zip
https://cdn.elifesciences.org/articles/66018/elife-66018-supp12-v2.zip
```

The captions of both files name 58 glomeruli (51 olfactory, 7 thermo- and hygrosensory). Supplementary file 11 ships 59 meshes: VM6 comes as three, `VM6l`, `VM6m` and `VM6v`, and VM2 is absent. Verified against a fresh download.

- Schlegel P, Bates AS, et al. *eLife*, 2021. doi:10.7554/eLife.66018

## neuPrint — JRCFIB2018F and JRCFIB2022M

Queried live through `neuprint-python`, so nothing is tracked. Requires a `NEUPRINT_APPLICATION_CREDENTIALS` token. Both the glomeruli and the whole-brain neuropil sets come from each dataset's ROI hierarchy; `registry/data/README.md` has the exact commands.

The dataset version is pinned per query in `registry/recipes.toml` rather than left to the server's default, because the ROIs differ between versions: `male-cns:v0.9` exposes only `AL(L)`/`AL(R)` with no glomerular subdivisions at all, so building against it silently yields two ROIs instead of 116.

- hemibrain: https://neuprint.janelia.org — `hemibrain:v1.2.1`; Scheffer LK, et al. *eLife*, 2020. doi:10.7554/eLife.57443. The dataset is CC BY 4.0 ([Janelia](https://www.janelia.org/project-team/flyem/hemibrain)).
- male CNS: https://neuprint-cns.janelia.org — `male-cns:v1.0`; Berg S, et al. *Cell*, 2026. doi:10.1016/j.cell.2026.08.015. The dataset is CC BY 4.0 ([Janelia](https://male-cns.janelia.org/download/)).

Two defects in these sets are in the published data, not introduced here:

- hemibrain `VM2(R)` is a 14 µm³ fragment, where VM2 is 1,342–3,259 µm³ in every other atlas that has one. `registry/checks.toml` records it, so `lobemap check` lists it without failing.
- In the male CNS neuropil set, `AME(L)` is 4,172 µm³ after the watertight repair against 16,608 µm³ for `AME(R)`. The repair log in the asset's metadata cannot say which lost it: its volume changes for open meshes were measured from the world origin, which is meaningless for a mesh with holes (it logged AB(L) and AB(R) as shrinking 85–89% while the repaired AB(R) matches the hemibrain's to 2%). The repair now measures from each mesh's own center.

## Grabe 2015 — GRABE

Folder: [`grabe-2015/`](../registry/sources/grabe-2015/)

A light-microscopy template rather than EM, and the one space no bridging registration reaches, so its atlas cannot be compared with the others quantitatively. Three assets come from it: the glomerular meshes, the Amira label volume they are surfaced from, and the confocal stack that serves as the space's reference image. The meshes are surfaced from the label volume rather than taken from the author-provided OBJ export.

The files are reproduced from the paper and its in vivo atlas. The atlas page at the Max Planck Institute for Chemical Ecology (https://www.ice.mpg.de/232714/vivo-3d-atlas) publishes the atlas PDF and the confocal stack; the article is not open access. Neither states terms for the files, and lobemap grants none: the rights stay with the authors and the publisher.

The label volume has no `VM6`. Its Amira material table names `VM6_left` and `VM6_right`, but neither has a voxel in the published "sure ones" volume, so 54 glomeruli per side are meshed rather than 55. The same table names the material read as `VP2` `VP2_left_VM6andVC6` and `VP2_right_VM6andVC6`, and in affine fits to the male CNS and Schlegel S12 it lies at VM6's position rather than VP2's. The viewer therefore names it `VP2 (VM6?)`, from the `[uncertain]` table in `registry/atlases/grabe2015.toml`; its nomenclature row stays VP2.

- Grabe V, Strutz A, Baschwitz A, Hansson BS, Sachse S. *Journal of Comparative Neurology*, 2015. doi:10.1002/cne.23697

## FAFB neuropils

Whole-brain neuropil meshes released with FlyWire, retrieved through [`fafbseg-py`](https://github.com/navis-org/fafbseg-py) and bridged into FAFB14: neuropils made for the JFRC2 template brain and mapped into FlyWire space by the fafbseg authors, according to fafbseg's documentation. FlyWire public data is CC BY-NC 4.0 ([guidelines](https://flywire.ai/guidelines)).

- Dorkenwald S, et al. *Nature*, 2024. doi:10.1038/s41586-024-07558-y

These are coarse: a median of 394 vertices per mesh and 7 µm facets, against 13,241 vertices for the neuPrint hemibrain set. They serve as context for the glomeruli rather than as geometry to measure.

## Virtual neuropil stains

A synthetic reference image rather than an atlas, one per EM space. Presynapse density binned at 0.25 µm and blurred with a 450 nm Gaussian, which reads much like an nc82 antibody stain while being computed natively in each volume instead of warped in from light microscopy. Built from the published synapse releases, roughly 20 GB of input that is not kept:

| space | synapse source | license |
|---|---|---|
| JRCFIB2018F | `gs://neuroglancer-janelia-flyem-hemibrain/v1.2/synapses/by_id/` — Scheffer LK, et al. *eLife*, 2020. doi:10.7554/eLife.57443 | CC BY 4.0 |
| JRCFIB2022M | `gs://flyem-male-cns/v1.0/connectome-data/flat-connectome/syn-points-male-cns-v1.0-minconf-0.5.feather` — Berg S, et al. *Cell*, 2026. doi:10.1016/j.cell.2026.08.015 | CC BY 4.0 |
| FAFB14 | `gs://flywire-data/codex/data/fafb/783/fafb_v783_princeton_synapse_table.csv.gz`, the FlyWire v783 Princeton synapse table — Yu SC, et al. New synapse detection in the whole-brain connectome of *Drosophila*. *bioRxiv*, 2025. doi:10.1101/2025.07.11.664377; on the FlyWire reconstruction of Dorkenwald S, et al. *Nature*, 2024. doi:10.1038/s41586-024-07558-y | CC BY-NC 4.0 |

No confidence threshold is applied to any of them. The male CNS file is already filtered to confidence 0.5, as its name says; the hemibrain shards carry no confidence field; and the Princeton table has no confidence or score column. The published FAFB stain's metadata records `confidence_threshold: 0.5`, which the build wrote without applying.

The Princeton coordinates are used as they come, without a FlyWire-to-FAFB14 bridge. Fitting the stain to the Benton meshes by a rigid shift gives a best offset under 1 µm, about the stain's resolution; the fit is shallow, so it bounds the offset rather than measuring it. The FlyWire-to-FAFB14 transform itself was not run.
