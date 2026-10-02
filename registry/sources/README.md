# Source data

The published material each built asset is derived from. This is *input*: the
outputs live in `registry/data/`, are not tracked, and are fetched or rebuilt
(see `registry/data/README.md`).

`registry/recipes.toml` addresses these files by paths relative to the registry
root, so `--registry` or `LOBEMAP_REGISTRY` can point anywhere and the recipes
still resolve.

| folder | used by | size |
|---|---|---|
| [`benton-2025/`](benton-2025/) | `benton2025_glomeruli` | 63 MB |
| [`grabe-2015/`](grabe-2015/) | `grabe2015_glomeruli`, `grabe2015_labels`, `grabe2015_stack` | 97 MB |
| [`bates-schlegel-2020/`](bates-schlegel-2020/) | nothing — kept for possible future use | 16 MB |
| [`jrc2018unisex/`](jrc2018unisex/) | nothing — kept for possible future use | 39 MB |

The hemibrain glomerulus surfaces exported from `hemibrainr` were here too,
and were removed: the same 58 glomeruli come from the live neuPrint query,
which resolves two of them further (`VC3l`/`VC3m` where the export had
`VC3`). Three annotation tables went with them -- receptor, ligand and
valence per glomerulus, and Virtual Fly Brain's FBbt terms. Those were not
redundant with anything, only unused; they are on the `legacy` branch.

Not every source is here. Some are downloaded at build time instead, because
they are large or already have a stable public URL: the Schlegel 2021
supplementary archives from the eLife CDN, the neuPrint ROI meshes, the FlyWire
neuropil meshes, and the ~20 GB of synapse tables the virtual stains are built
from. `registry/recipes.toml` records which is which.

[`paper-pdf-sources.csv`](paper-pdf-sources.csv) lists where the papers
themselves can be downloaded. The PDFs are not tracked, with one exception:
Grabe 2015's atlas PDF, which is part of the published atlas rather than the
paper.

These folders were `datasets/` at the repository root, each holding a
`data/source` tree, a per-dataset napari module and a cache of 256-cube label
volumes. The modules and caches belonged to the viewer this one replaced and
are on the `legacy` branch, which still carries the whole original tree
including ten datasets no longer used here.
