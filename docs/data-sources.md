# Data Sources

This document records where each dataset lobemap ships came from, what is done
to it before the viewer opens it, and how to obtain it. `registry/assets.toml`
carries the same provenance per asset in machine-readable form, and is the
authority if the two ever disagree.

Nothing here is redistributed under a license of lobemap's own. Each dataset
keeps the license and citation requirements of its own publication. **If you use
an atlas, cite the paper it came from.** Links to the papers themselves are in
[`paper-pdf-sources.csv`](../registry/sources/paper-pdf-sources.csv); the PDFs
are not tracked.

## Getting the data

The viewer does not read the published sources directly. Each one is ingested
once into a container — a compressed `.npz` of meshes or a Zarr volume — and
those containers are what ship. There are fourteen, 2.5 GB in total, attached
to a tagged release rather than committed:

```bash
lobemap fetch
```

Of that total, 2.4 GB is the three virtual neuropil stains. Everything else —
all six atlases, the neuropil sets and the Grabe confocal stack — is 76 MB:

```bash
lobemap fetch --nostains
```

`registry/manifest.toml` is the authority on where the containers live and what
they should contain. It pins a sha256 per artifact, so a copy can be verified
without being trusted:

```bash
lobemap fetch --check
```

That reports what is present, what is missing and what fails its hash, and
downloads nothing. If you host the containers elsewhere, `--base-url` overrides
the location while still checking against the same hashes.

## What is done to the data

Every container is built by a recipe in `registry/recipes.toml`, and the
processing below is applied on the way in. None of it is reversible from the
container, so it is worth knowing before measuring anything from these meshes.

**Units.** All geometry is stored in micrometers. The conversion factor is taken
from the source, never deduced from the result: neuPrint states its voxel grid
in the dataset's `:Meta` node, and for formats that cannot carry units — OBJ,
VTP — the recipe declares `source_units` alongside where that declaration comes
from.

**Mesh repair.** Source meshes are made watertight, because an open shell cannot
support the inside/outside test the viewer's containment checks depend on. Holes
are filled, duplicate vertices merged, and stray fragments below 1 µm³ dropped.
This changes geometry. How much varies by atlas:

| atlas | already watertight | repaired | volume changed by at most |
|---|---|---|---|
| Benton 2025 | 31 of 58 | 27 | 0% |
| neuPrint hemibrain | 76 of 77 | 1 | 0% |
| Schlegel 2021 S11 | 0 of 59 | 59 | 0% |
| Schlegel 2021 S12 | 0 of 58 | 58 | 0% |
| neuPrint male CNS | 96 of 116 | 20 | 0.06% |
| Grabe 2015 | 108 of 108 | 0 | — |

What the repair does not do is remove a tunnel. Some glomeruli arrive from their
source enclosing one, so that the surface is a torus rather than a sphere, and
others arrive as several disconnected pieces; both survive. Counting each
glomerulus once, that is 1 of 58 in Benton, 4 of 77 in the neuPrint hemibrain,
4 of 59 in S11, 6 of 58 in S12, 9 of 116 in the male CNS and 1 of 108 in Grabe.
These are properties of the published meshes, and they affect the surfaces only
— volumes and centroids are sound.

**Names.** Each atlas keeps its published glomerulus names, with one exception:
neuPrint's `AL-` neuropil qualifier is dropped, so `AL-DA1(R)` is stored as
`DA1(R)`. The nomenclature table records how every atlas's names map onto its
space's vocabulary.

**Selection.** The male CNS neuropil set is cut to the brain, built from the
`CentralBrain` and `Optic` branches of the ROI hierarchy, so no ventral nerve
cord or cervical connective ROI enters. The hemibrain has no such branches and
nothing is removed there.

## Benton 2025 — FAFB14

Folder: [`benton-2025/`](../registry/sources/benton-2025/)

Glomerular segmentation of FAFB, read from the published 3D Slicer scene
(`DatasetEV2.seg.vtm`) and tracked in this repository. Delivered in Slicer's RAS
convention and converted to FAFB14's.

- Benton R, et al. *EMBO Reports*, 2025. doi:10.1038/s44319-025-00476-8

## Schlegel 2021 — JRCFIB2018F

Two independent parcellations of the hemibrain, S11 traced from receptor neurons
and S12 from projection neurons. Downloaded from the eLife CDN at build time
(CC BY 4.0) rather than tracked:

```
https://cdn.elifesciences.org/articles/66018/elife-66018-supp11-v2.zip
https://cdn.elifesciences.org/articles/66018/elife-66018-supp12-v2.zip
```

Supplementary file 11 ships 59 meshes rather than the 60 its caption states;
VM2 is absent.

- Schlegel P, Bates AS, et al. *eLife*, 2021. doi:10.7554/eLife.66018

## neuPrint — JRCFIB2018F and JRCFIB2022M

Queried live through `neuprint-python`, so nothing is tracked. Requires a
`NEUPRINT_APPLICATION_CREDENTIALS` token. Both the glomeruli and the whole-brain
neuropil sets come from each dataset's ROI hierarchy; `registry/data/README.md`
has the exact commands.

The dataset version is pinned per query rather than left to the server's
default, because the ROIs differ between versions — `male-cns:v0.9` has no
glomerular subdivisions at all.

- hemibrain: https://neuprint.janelia.org — `hemibrain:v1.2.1`;
  Scheffer LK, et al. *eLife*, 2020. doi:10.7554/eLife.57443 (CC BY 4.0)
- male CNS: https://neuprint-cns.janelia.org — `male-cns:v1.0`;
  Berg S, et al. *Cell*, 2026. doi:10.1016/j.cell.2026.08.015

## Grabe 2015 — GRABE

Folder: [`grabe-2015/`](../registry/sources/grabe-2015/)

A light-microscopy template rather than EM, and the one space no bridging
registration reaches, so its atlas cannot be compared with the others
quantitatively. Three assets come from it: the glomerular meshes, the Amira
label volume they are surfaced from, and the confocal stack that serves as the
space's reference image. The meshes are surfaced from the label volume rather
than taken from the published OBJ export.

- Grabe V, Strutz A, Baschwitz A, Hansson BS, Sachse S. *Journal of Comparative
  Neurology*, 2015. doi:10.1002/cne.23697

## FAFB neuropils

Whole-brain neuropil meshes from the FlyWire segmentation, retrieved through
[`fafbseg-py`](https://github.com/navis-org/fafbseg-py) and bridged into FAFB14.

These are coarse: a median of 394 vertices per mesh and 7 µm facets, against
13,241 vertices for the neuPrint hemibrain set. They serve as context for the
glomeruli rather than as geometry to measure.

## Virtual neuropil stains

A synthetic reference image rather than an atlas, one per EM space. Presynapse
density binned at 0.25 µm and blurred with a 450 nm Gaussian, which reads much
like an nc82 antibody stain while being computed natively in each volume instead
of warped in from light microscopy. Built from the published synapse releases,
roughly 20 GB of input that is not kept:

| space | synapse source |
|---|---|
| JRCFIB2018F | `gs://neuroglancer-janelia-flyem-hemibrain/v1.2/synapses/by_id/` |
| JRCFIB2022M | `gs://flyem-male-cns/v1.0/connectome-data/flat-connectome/syn-points-male-cns-v1.0-minconf-0.5.feather` |
| FAFB14 | `gs://flywire-data/codex/data/fafb/783/fafb_v783_princeton_synapse_table.csv.gz` |

The FAFB table is the Princeton synapse table for FAFB v783 — Dorkenwald S, et
al. *Nature*, 2024. doi:10.1038/s41586-024-07558-y
