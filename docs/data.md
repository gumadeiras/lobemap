# Data

This page explains how to download, store, check and rebuild lobemap's data, and under which licenses the data is.

## What you download

The data that the viewer opens is published separately, not shipped in the package. `lobemap fetch` downloads it:

```bash
lobemap fetch
```

A full fetch is 2.5 GB and gets everything: the atlases, the neuropil sets, the Grabe confocal stack and label volume, and the three virtual neuropil stains. The stains are 2.4 GB of that. To leave them out:

```bash
lobemap fetch --nostains
```

That takes 76 MB. Every space still opens. The three EM spaces just open without their reference image, and running the full `fetch` later fills them in.

To fetch one asset only, name it:

```bash
lobemap fetch --asset hemibrain_stain
```

### What `lobemap view` fetches by itself

`lobemap view` fetches before it opens a window: every missing artifact except the stains, up to 11 files and 76 MB, whichever space you open. So the explicit `fetch` is a convenience, not a requirement.

`lobemap view` never fetches a stain, though. After `fetch --nostains`, the EM spaces open without a reference image until you fetch one. A stain that *is* on disk is always shown.

## Where the data goes

| how lobemap is installed | where the data goes |
|---|---|
| from PyPI, on macOS | `~/Library/Caches/lobemap/data` |
| from PyPI, on Linux | `~/.cache/lobemap/data` |
| a source checkout | `registry/data` |

An installed lobemap keeps its data in the user cache directory. `lobemap fetch` prints the location.

To keep the data somewhere else, set `LOBEMAP_DATA`, or pass `--data-root` before the command name:

```bash
LOBEMAP_DATA=/path/to/data lobemap fetch
lobemap --data-root /path/to/data view
```

Either one moves the data for every command that reads or writes it.

The commands work from any directory. A checkout reads its own `registry/`, and a package installed from PyPI carries a copy of the registry metadata. `--registry` or `LOBEMAP_REGISTRY` points at a different one.

## How the data is published

The data is not committed to the repository. Its fourteen artifacts are published as assets of the [`data-v1` release](https://github.com/gumadeiras/lobemap/releases/tag/data-v1): 2.51 GB, of which the three virtual stains are 2.44 GB.

The repository does commit:

- the published source data that some artifacts are built from, about 220 MB under [`registry/sources/`](../registry/sources/README.md);
- the registry metadata.

Only the metadata ships in the package.

## Checking the data

[`registry/manifest.toml`](../registry/manifest.toml) records where the artifacts are fetched from, and the sha256 of every one. `lobemap fetch` checks each download against it. A file that does not match is discarded, not kept.

To check what is on disk without downloading anything:

```bash
lobemap fetch --check
```

[Data sources](data-sources.md#getting-the-data) has more on checking, and on `--base-url` for data hosted elsewhere.

## Rebuilding the data from source

You can also rebuild the data from source instead of downloading it.

### Extra dependencies

Viewing needs nothing more than `pip install lobemap`. Some commands need about 100 more packages:

- rebuilding data from source: `build`, `stain` and `ingest`;
- moving geometry between spaces: `bridge`, and `check` or `reconcile` on an atlas outside its own space.

Add them with:

```bash
pip install "lobemap[ingest]"
```

In a source checkout, `uv sync` and `uv run` install them too. [Development](development.md#set-up) explains how to leave them out.

### Build an asset

List the assets that have a recipe, and which are on disk:

```bash
lobemap build --list
```

Build one asset by name:

```bash
lobemap build hemibrain_stain
```

Each stain needs several gigabytes downloaded from the published synapse releases, about 40 GB of scratch space, and a long run. So `build --all` skips the stains, and you have to ask for them by name.

Everything else is derived from sources that either ship in `registry/sources/` or are downloaded by the build:

- the neuPrint assets need a neuPrint token in `NEUPRINT_APPLICATION_CREDENTIALS`;
- `fafb_neuropil` needs FlyWire access.

[`registry/recipes.toml`](../registry/recipes.toml) records exactly how each asset is built, and [`registry/data/README.md`](../registry/data/README.md) describes each pipeline.

### Compare a rebuilt asset

A rebuilt asset is not byte-identical to the original, because every pipeline stamps the date it ran. So compare its *content* hash, which the build prints, instead.

### Publish a data release

If you are republishing the data, `lobemap pack` writes the upload-ready copies. [RELEASE.md](../RELEASE.md#data-releases) has the full steps for a data release.

## Data licenses

The MIT License in [LICENSE](../LICENSE) covers the lobemap code. It does not cover the data. Each data asset keeps the license of its source. [`registry/assets.toml`](../registry/assets.toml) records it per asset as `source.license`, with the page that states it as `source.license_url`.

| assets | license | stated at |
|---|---|---|
| `neuprint_hemibrain_glomeruli`, `neuprint_hemibrain_neuropil`, `hemibrain_stain` | CC BY 4.0 | [Janelia FlyEM hemibrain](https://www.janelia.org/project-team/flyem/hemibrain) |
| `neuprint_cns_glomeruli`, `neuprint_cns_neuropil`, `malecns_stain` | CC BY 4.0 | [male CNS downloads](https://male-cns.janelia.org/download/) |
| `schlegel2021_s11_glomeruli`, `schlegel2021_s12_glomeruli` | CC BY 4.0 | [Schlegel et al. 2021, eLife](https://elifesciences.org/articles/66018) |
| `benton2025_glomeruli` | CC0 1.0 (the article itself is CC BY 4.0) | [Benton et al. 2025, EMBO Reports](https://europepmc.org/article/PMC/PMC12187929) |
| `fafb_neuropil`, `fafb_stain` | CC BY-NC 4.0: attribution, no commercial use | [FlyWire guidelines](https://flywire.ai/guidelines) |
| `grabe2015_glomeruli`, `grabe2015_labels`, `grabe2015_stack` | none published | [Grabe et al. 2015](https://doi.org/10.1002/cne.23697), [atlas page](https://www.ice.mpg.de/232714/vivo-3d-atlas) |

The Grabe 2015 assets are built from files reproduced from the paper and its in vivo atlas: the confocal stack, and the Amira label volume with its material table. Neither the journal nor the atlas page publishes terms for them, and lobemap grants none. The rights stay with the authors and the publisher.

The tracked source files under `registry/sources/` keep the terms of the same sources:

- Benton's Dataset EV1 and EV2 are CC0 1.0, and its figure panels are CC BY 4.0.
- The Grabe files are reproduced from the paper, as above. The exception is the Grabe 2016 supplemental tables (`s1.png`, `s1_cont.png`, `s2.png`), which are [CC BY-NC-ND 4.0](https://doi.org/10.1016/j.celrep.2016.08.063).
- The Bates 2020 atlas figure is CC BY 4.0.
- The JRC2018 Unisex template and ROI volumes from Virtual Fly Brain are [CC BY-NC-SA 4.0](https://www.virtualflybrain.org/reports/JRC2018).

[`registry/reference/glomerulus_ground_truth.csv`](../registry/reference/README.md) compiles values from published tables, and each value keeps the terms of its source.

CC BY and CC BY-NC require attribution, so cite the paper behind each atlas that you use. [Data sources](data-sources.md) has the citations. CC BY-NC data may not be used commercially. This includes everything in FAFB14 except the Benton atlas.
