# Commands

This page lists every `lobemap` command and its options. The usage lines, the options and their help texts are copied from `lobemap <command> --help`. Where the help gives no text for an option, this page adds a short description.

## Running lobemap

- An installed lobemap is the `lobemap` command.
- In a source checkout, use `uv run lobemap`. [Development](development.md#run-lobemap-from-the-checkout) explains how to drop the `uv run` prefix.
- `python -m lobemap` runs the same command as `lobemap`.
- `lobemap` with no command opens the viewer, as `lobemap view` does.
- `lobemap --help` lists the commands, and `lobemap <command> --help` lists the options of one command.

Wrong input, such as an unknown space or asset, stops with a one-line message before any work starts or any window opens.

### Global options

These go before the command name, as in `lobemap --data-root /path/to/data fetch`.

| option | what it does |
|---|---|
| `--version` | show program's version number and exit |
| `--registry REGISTRY` | registry metadata directory (default: $LOBEMAP_REGISTRY, else the copy installed with lobemap, or registry/ in a source checkout) |
| `--data-root DATA_ROOT` | where asset files live (default: $LOBEMAP_DATA, else <registry>/data if it exists, else the user cache directory) |

### Environment variables

| variable | what it does |
|---|---|
| `LOBEMAP_DATA` | where the data lives, as `--data-root` |
| `LOBEMAP_REGISTRY` | which registry to read, as `--registry` |
| `NEUPRINT_APPLICATION_CREDENTIALS` | the neuPrint token for building the neuPrint assets, for `ingest neuprint`, and for `stain` without `--bucket` |
| `LOBEMAP_CRASH_LOG` | the file where `lobemap view` writes a report if it crashes; by default a temporary file, removed again when nothing was written |

## Commands for viewing

### view

Open a coordinate space.

```text
lobemap view [-h] [--ndisplay {2,3}] [--show NAME] [space]
```

| argument | default | what it does |
|---|---|---|
| `space` | `FAFB14` | space id; `lobemap spaces` lists them (default: FAFB14) |
| `--ndisplay {2,3}` | `3` | open in 3D (`3`) or in Slice view (`2`) |
| `--show NAME` | | start this visible in the first scene: an asset id, an atlas id, or a role such as neuropil. Repeatable. |

`--show` turns on something that starts off, in the first brain only:

- an asset id: `lobemap view FAFB14 --show fafb_neuropil`
- an atlas id: `lobemap view JRCFIB2018F --show schlegel2021_s12`
- a role: `lobemap view --show neuropil`

A name the brain does not have, or an unknown space, is refused with one line before any window opens.

Before it opens a window, `view` fetches every missing artifact except the virtual stains. [Data](data.md#what-lobemap-view-fetches-by-itself) has the details.

### spaces

List spaces and their bridging status.

```text
lobemap spaces [-h]
```

`spaces` has no options. For each space it prints its units, its template, its atlases, how many of its assets are on disk, and what `lobemap view <space>` opens with.

## Commands for data

### fetch

Download or verify data artifacts.

```text
lobemap fetch [-h] [--manifest MANIFEST] [--base-url BASE_URL] [--asset ASSET] [--nostains] [--check]
```

| option | default | what it does |
|---|---|---|
| `--manifest MANIFEST` | `<registry>/manifest.toml` | the manifest to read |
| `--base-url BASE_URL` | | overrides the manifest's |
| `--asset ASSET` | | only this asset; repeatable |
| `--nostains` | | skip the three virtual stains, which are 2.4 GB of the 2.5 GB total; everything else is 76 MB |
| `--check` | | verify what is present and exit; download nothing |

`fetch --check` exits with status 1 if an artifact is missing or fails its check. [Data](data.md) explains the download, its location and its checks.

### build

Derive built assets from their sources. It needs the [extra dependencies](data.md#extra-dependencies).

```text
lobemap build [-h] [--all] [--list] [--overwrite] [asset ...]
```

| argument | what it does |
|---|---|
| `asset ...` | asset ids; omit with --all |
| `--all` | build every asset with a recipe that is missing |
| `--list` | show which assets have a recipe, and their state |
| `--overwrite` | rebuild even if the file is already there |

`--all` skips the three virtual stains. Build them by name. [Data](data.md#rebuilding-the-data-from-source) explains what each build needs, and [`registry/data/README.md`](../registry/data/README.md) describes each pipeline.

### pack

Write upload-ready copies of the data artifacts.

```text
lobemap pack [-h] [--all] [--manifest MANIFEST] [--output OUTPUT] [--overwrite] [asset ...]
```

| argument | default | what it does |
|---|---|---|
| `asset ...` | | asset ids; omit to list what is available |
| `--all` | | pack every artifact in the manifest |
| `--manifest MANIFEST` | `<registry>/manifest.toml` | the manifest to check the copies against |
| `--output OUTPUT` | `<data root>/.pack` | where to write them (default: <data root>/.pack) |
| `--overwrite` | | re-create files that are already there |

`pack` fails if a copy does not match the manifest. [RELEASE.md](../RELEASE.md#data-releases) shows where it fits in a data release.

### manifest

Record checksums for fetchable data.

```text
lobemap manifest [-h] [--base-url BASE_URL] [--output OUTPUT] [--prune]
```

| option | default | what it does |
|---|---|---|
| `--base-url BASE_URL` | the current manifest's | where the artifacts will be published |
| `--output OUTPUT` | `<registry>/manifest.toml` | default: <registry>/manifest.toml |
| `--prune` | | drop records for artifacts not on disk instead of keeping them |

## Commands for checking

### validate

Load and check the registry.

```text
lobemap validate [-h] [--strict]
```

| option | what it does |
|---|---|
| `--strict` | also require flybrains to know every template |

### check

Run the geometry validation harness. It tests the data against its own geometry, including laterality, chirality, image orientation, label containment and compartment size. It lists the known defects in [`registry/checks.toml`](../registry/checks.toml) without failing.

```text
lobemap check [-h] [--roundtrip SRC VIA] [--compare A B SPACE]
```

| option | what it does |
|---|---|
| `--roundtrip SRC VIA` | e.g. --roundtrip JRCFIB2018F FAFB14 |
| `--compare A B SPACE` | compare atlases A and B in SPACE by canonical name and side, bridging either one that is not native to it with biological sides aligned |

`--roundtrip` moves each atlas native to template `SRC` into template `VIA` and back, and checks that the median displacement stays under 10 µm. `check` exits with status 1 if a check fails, or if no data is on disk to check.

### reconcile

Pair two atlases by geometry, and compare their names. Each compartment is paired with the nearest compartment of the other atlas, by centroid, when each is the other's nearest.

```text
lobemap reconcile [-h] [--space SPACE] [--max-distance MAX_DISTANCE] [--ambiguity-ratio AMBIGUITY_RATIO] a b
```

| argument | default | what it does |
|---|---|---|
| `a`, `b` | | the two atlas ids |
| `--space SPACE` | the space of `a` | space to compare in (default: A's native) |
| `--max-distance MAX_DISTANCE` | `5.0` | the largest distance, in µm, between two paired centroids |
| `--ambiguity-ratio AMBIGUITY_RATIO` | `0.5` | match must be this much closer than the runner-up |

### nomenclature

Audit the nomenclature table, [`registry/nomenclature.csv`](../registry/nomenclature.csv), against the atlases. By default it changes nothing, and it exits with status 1 if it finds a difference.

```text
lobemap nomenclature [-h] [--add-missing] [--prune-stale] [--cross-check CROSS_CHECK] [--column COLUMN]
```

| option | default | what it does |
|---|---|---|
| `--add-missing` | | add rows for published names that have none; existing rows are never touched |
| `--prune-stale` | | remove rows for names an atlas no longer publishes |
| `--cross-check CROSS_CHECK` | | CSV of curated names to compare against |
| `--column COLUMN` | `canonical_glomerulus` | column in the cross-check CSV holding the name |

## Commands for single build steps

These commands run one step of a build by hand. They need the [extra dependencies](data.md#extra-dependencies). [`registry/data/README.md`](../registry/data/README.md) shows how each asset uses them.

### bridge

Bridge an asset into another space.

```text
lobemap bridge [-h] --to TO [--mirror] [--no-cache] asset
```

| argument | what it does |
|---|---|
| `asset` | the asset id |
| `--to TO` | target space id (required) |
| `--mirror` | mirror the asset left to right, in its own space, before the bridge |
| `--no-cache` | do not read or write the cache of bridged assets |

The bridged asset is cached under `bridged` in the user cache directory, and the command prints where.

### stain

Build a virtual neuropil stain.

```text
lobemap stain [-h] --space SPACE --asset-id ASSET_ID [--server SERVER] [--dataset DATASET] [--roi ROI] [--bounds-from BOUNDS_FROM] [--bounds X0 Y0 Z0 X1 Y1 Z1] [--confidence CONFIDENCE] [--voxel VOXEL] [--sigma SIGMA] [--dtype {uint8,uint16}] [--workdir WORKDIR] [--keep-workdir] [--slabs SLABS] [--bucket {hemibrain,malecns,fafb}] [--path PATH] [--token TOKEN]
```

| option | default | what it does |
|---|---|---|
| `--space SPACE` | | the space to build the stain in (required) |
| `--asset-id ASSET_ID` | | the asset id; the stain is written to `<data root>/<asset id>.npz` (required) |
| `--server SERVER` | `neuprint.janelia.org` | the neuPrint server |
| `--dataset DATASET` | `hemibrain:v1.2.1` | the neuPrint dataset |
| `--roi ROI` | | restrict to these ROIs (repeatable); omit for whole brain |
| `--bounds-from BOUNDS_FROM` | | mesh asset id to take bounds from |
| `--bounds X0 Y0 Z0 X1 Y1 Z1` | | explicit grid bounds in um; points outside are dropped, which is how the male CNS is cropped to brain |
| `--confidence CONFIDENCE` | `0.5` | the lowest synapse confidence to keep; not used with `--bucket hemibrain` or `--bucket fafb` |
| `--voxel VOXEL` | `0.5` | bin size in um; halving it doubles the grid in each axis and multiplies its size by 8 |
| `--sigma SIGMA` | `0.9` | point-spread width in um; this, not --voxel, sets the stain's actual resolution |
| `--dtype {uint8,uint16}` | `uint8` | stored sample type; uint8 matches the confocal stacks this emulates and halves the file |
| `--workdir WORKDIR` | `<data root>/.stainwork` | scratch space for grids too large for RAM (default: <data root>/.stainwork) |
| `--keep-workdir` | | do not delete the scratch space afterwards |
| `--slabs SLABS` | `24` | how many slabs to split the neuPrint query into |
| `--bucket {hemibrain,malecns,fafb}` | | read presynapses from a bulk release instead of neuPrint |
| `--path PATH` | | shard directory or table file for --bucket |
| `--token TOKEN` | `$NEUPRINT_APPLICATION_CREDENTIALS` | the neuPrint token |

With no `--bounds` or `--bounds-from`, the bounds are the bounding box of the space's template. `stain` writes an `.npz`; `tozarr` converts it to the OME-Zarr store that the registry points at.

### tozarr

Rewrite a volume as multiscale OME-Zarr.

```text
lobemap tozarr [-h] [--chunk CHUNK] [--min-extent MIN_EXTENT] [--force] input [output]
```

| argument | default | what it does |
|---|---|---|
| `input` | | an .npz volume (its .data.npy is picked up) |
| `output` | beside the input | destination .zarr (default: alongside the input) |
| `--chunk CHUNK` | `64` | cubic chunk edge; 64 keeps a uint8 chunk at 256 KB |
| `--min-extent MIN_EXTENT` | `128` | stop halving once the largest axis is this small |
| `--force` | | replace the output if it exists |

### repair

Make stored meshes watertight, in place.

```text
lobemap repair [-h] [--dry-run] [assets ...]
```

| argument | what it does |
|---|---|
| `assets ...` | asset ids (default: all meshsets) |
| `--dry-run` | report what the repair would do, and write nothing |

### ingest neuprint

Build canonical assets from sources: AL ROI meshes from neuPrint. `neuprint` is the only source of `ingest`. It needs a neuPrint token.

```text
lobemap ingest neuprint [-h] [--server SERVER] [--dataset DATASET] [--role {glomeruli,neuropil}] --asset-id ASSET_ID [--atlas-id ATLAS_ID] [--no-repair] [--token TOKEN]
```

| option | default | what it does |
|---|---|---|
| `--server SERVER` | `neuprint.janelia.org` | the neuPrint server |
| `--dataset DATASET` | `hemibrain:v1.2.1` | the neuPrint dataset |
| `--role {glomeruli,neuropil}` | `glomeruli` | which ROIs to fetch |
| `--asset-id ASSET_ID` | | the asset id; the meshes are written to `<data root>/<asset id>.npz` (required) |
| `--atlas-id ATLAS_ID` | | register names under this atlas id |
| `--no-repair` | | skip watertight repair (not recommended) |
| `--token TOKEN` | `$NEUPRINT_APPLICATION_CREDENTIALS` | the neuPrint token |

With `--atlas-id` and the `glomeruli` role, new glomerulus names are added to [`registry/nomenclature.csv`](../registry/nomenclature.csv).
