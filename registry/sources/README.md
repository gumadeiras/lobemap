# Source data

The published material each built asset is derived from. This is *input*: the outputs live in `registry/data/`, are not tracked, and are fetched or rebuilt (see `registry/data/README.md`).

`registry/recipes.toml` addresses these files by paths relative to the registry root, so `--registry` or `LOBEMAP_REGISTRY` can point anywhere and the recipes still resolve.

| folder | used by | size |
|---|---|---|
| [`benton-2025/`](benton-2025/) | `benton2025_glomeruli` | 63 MB |
| [`grabe-2015/`](grabe-2015/) | `grabe2015_glomeruli`, `grabe2015_labels`, `grabe2015_stack` | 97 MB |
| [`bates-schlegel-2020/`](bates-schlegel-2020/) | nothing — kept for possible future use | 16 MB |
| [`jrc2018unisex/`](jrc2018unisex/) | nothing — kept for possible future use | 39 MB |

The hemibrain glomerulus surfaces exported from `hemibrainr` were here too, and were removed because they duplicate Schlegel 2021 supplementary file 12: the export has the same 58 names (`VC3`, `VC5`, `VM6` among them) and the same vertex count for every glomerulus, and its centroids match S12's to 0.0013 µm. The neuPrint hemibrain names three of them differently -- `VC3l`, `VC3m` and `VC5` for S12's `VC3`, `VC5` and `VM6` -- which is the Schlegel 2021 rename, not a finer subdivision. Three annotation tables went with the export -- receptor, ligand and valence per glomerulus, and Virtual Fly Brain's FBbt terms. Those were not redundant with anything, only unused; they are in `datasets/hemibrain/` at tag [`v0.1.4`](https://github.com/gumadeiras/lobemap/tree/v0.1.4/datasets/hemibrain).

Not every source is here. Some are downloaded at build time instead, because they are large or already have a stable public URL: the Schlegel 2021 supplementary archives from the eLife CDN, the neuPrint ROI meshes, the FlyWire neuropil meshes, and the ~20 GB of synapse tables the virtual stains are built from. `registry/recipes.toml` records which is which.

[`paper-pdf-sources.csv`](paper-pdf-sources.csv) lists where the papers themselves can be downloaded. The PDFs are not tracked, with one exception: Grabe 2015's atlas PDF, which is part of the published atlas rather than the paper.

These folders were `datasets/` at the repository root, each holding a `data/source` tree, a per-dataset napari module and a cache of 256-cube label volumes. The modules and caches belonged to the viewer this one replaced. Tag [`v0.1.4`](https://github.com/gumadeiras/lobemap/tree/v0.1.4), the last release of that viewer, carries the whole original tree, including ten datasets no longer used here.

## Terms

The files here keep the terms of their sources, not the code's MIT License; "Data licenses" in the top-level README lists them. In short: Benton 2025's Dataset EV1 and EV2 are CC0 1.0 and its figure panels CC BY 4.0; the Grabe 2015 files are reproduced from the paper and its in vivo atlas, with no published terms, so the rights stay with the authors and the publisher, while the Grabe 2016 supplemental tables (`grabe-2015/s1.png`, `s1_cont.png`, `s2.png`) are CC BY-NC-ND 4.0; the Bates 2020 atlas figure is CC BY 4.0; and the JRC2018 Unisex files from Virtual Fly Brain are CC BY-NC-SA 4.0.
