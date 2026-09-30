# Ingested assets

Nothing here is tracked except this README. The artifacts are published as release assets; `lobemap fetch` puts them on disk from the `base_url` in `registry/manifest.toml`, verified against the sha256 recorded there. In a source checkout this directory is the default data root. An installed lobemap uses the user cache directory instead, and `LOBEMAP_DATA` or `--data-root` names another; the paths below are for a checkout.

What follows is how each asset is rebuilt from its source. `registry/recipes.toml` records it and `lobemap build <asset>` runs it; `lobemap build --list` shows which assets have a recipe and which are on disk. Rebuilding needs the ingest dependencies: `pip install "lobemap[ingest]"`, or a checkout's `uv sync`. Use it when you are regenerating an asset rather than installing; `lobemap pack` then writes the copies to upload (see `RELEASE.md`).

`build` caches what it downloads in `<data root>/.build/`, so a second build does not download again; delete that directory to reclaim the space. A recipe can record a sha256 per downloaded file, and `build` then discards a download that does not match. No recipe records one yet, so `build` reports each download as not verified.

## neuPrint: hemibrain and male CNS

`lobemap build neuprint_hemibrain_glomeruli`, `neuprint_hemibrain_neuropil`, `neuprint_cns_glomeruli` and `neuprint_cns_neuropil` fetch the ROI meshes from neuPrint, drop neuPrint's `AL-` prefix from the glomerulus names, and repair the meshes to watertight. Needs `NEUPRINT_APPLICATION_CREDENTIALS`.

The same step by hand, which also adds new glomerulus names to `registry/nomenclature.csv`:

```
lobemap ingest neuprint --dataset hemibrain:v1.2.1 \
    --asset-id neuprint_hemibrain_glomeruli --atlas-id neuprint_hemibrain
lobemap ingest neuprint --dataset hemibrain:v1.2.1 --role neuropil \
    --asset-id neuprint_hemibrain_neuropil
lobemap ingest neuprint --server neuprint-cns.janelia.org --dataset male-cns:v1.0 \
    --asset-id neuprint_cns_glomeruli --atlas-id neuprint_cns
lobemap ingest neuprint --server neuprint-cns.janelia.org --dataset male-cns:v1.0 \
    --role neuropil --asset-id neuprint_cns_neuropil
```

## Schlegel 2021

`lobemap build schlegel2021_s11_glomeruli` and `schlegel2021_s12_glomeruli` download supplementary files 11 and 12 from the eLife CDN (CC BY 4.0) and ingest them with `lobemap.ingest.obj_archive`:

```
https://cdn.elifesciences.org/articles/66018/elife-66018-supp11-v2.zip
https://cdn.elifesciences.org/articles/66018/elife-66018-supp12-v2.zip
```

## Benton 2025

`lobemap build benton2025_glomeruli` reads Dataset EV2, a 3D Slicer scene, from `registry/sources/benton-2025/` and converts it from Slicer's RAS coordinates to LPS. Offline.

## Grabe 2015

`lobemap build grabe2015_glomeruli grabe2015_labels grabe2015_stack` works offline from `registry/sources/grabe-2015/`. The glomeruli are surfaced from the Amira label volume, not from the author-provided OBJ export; `grabe2015_labels` keeps the published masks as they are; and `grabe2015_stack` is the confocal stack. The docstring of `lobemap.ingest.label_volume` says why the masks rather than the OBJs: the OBJ export sits about 1.1 voxels off the masks in x, and it has only the left lobe.

## FAFB14 neuropils

`lobemap build fafb_neuropil` fetches FlyWire's neuropil meshes through fafbseg, which needs FlyWire access, and bridges them from FlyWire space into FAFB14 as part of the build. The viewer labels the layer `fafb_neuropil [bridged]`.

## Virtual neuropil stains

Presynapses only, from the published bulk releases; sigma 450 nm; 0.25 um bins. The bounds are recorded in `registry/recipes.toml` and passed explicitly, so a rebuild reproduces the same physical box; the grid adds a 5 um margin around them for the tail of the blur. The male CNS bounds also crop the VNC away.

`lobemap build hemibrain_stain`, `fafb_stain` and `malecns_stain` download their sources, about 20 GB for the three, and write the OME-Zarr store the registry points at, a 5-6 level multiscale pyramid. `build --all` skips them, so they must be named. The recipes record the voxel size and sigma the published stains were built with.

```
gs://neuroglancer-janelia-flyem-hemibrain/v1.2/synapses/by_id/   (8 shards, 4.2 GB)
https://storage.googleapis.com/flyem-male-cns/v1.0/connectome-data/
  flat-connectome/syn-points-male-cns-v1.0-minconf-0.5.feather   (13.1 GB)
FAFB v783 Princeton synapse table                                 (2.7 GB)
```

At 0.25 um each grid is 2-5 G voxels, so a build goes slab by slab through a scratch directory of its own, `.stainwork/<asset>-<random>/` under the data root, which needs about 40 GB free. It is removed when the build ends, also when it fails, and `.stainwork` itself goes once no build uses it. A recipe's `workdir` param puts the scratch directory on another disk.

The same stain by hand, from a source you downloaded yourself:

```
lobemap stain --bucket hemibrain --path <dir of by_id/*.shard> \
  --space JRCFIB2018F --asset-id hemibrain_stain --voxel 0.25 --sigma 0.45 \
  --bounds 0 0 0 275.5 316.5 331.5

lobemap stain --bucket fafb --path fafb_v783_princeton_synapse_table.csv.gz \
  --space FAFB14 --asset-id fafb_stain --voxel 0.25 --sigma 0.45 \
  --bounds 192.2 75.853 2.007 853.7 398.853 271.507

lobemap stain --bucket malecns --path syn-points-male-cns-v1.0-minconf-0.5.feather \
  --space JRCFIB2022M --asset-id malecns_stain --voxel 0.25 --sigma 0.45 \
  --bounds 37.6 37.3 79.8 732.1 421.8 345.3
```

`stain` works in a scratch directory of its own, `<asset>-<random>/` inside `--workdir` (by default `.stainwork` under the data root), and removes only that directory when the run ends, also when it fails, unless `--keep-workdir` is given. Other files in `--workdir` are left alone. It writes a uint8 `.npz` (plus a `<id>.data.npy` sidecar past 2 GB). Convert it to the OME-Zarr store the registry points at:

```
lobemap tozarr registry/data/hemibrain_stain.npz
lobemap tozarr registry/data/fafb_stain.npz
lobemap tozarr registry/data/malecns_stain.npz
```

That builds the 5-6 level pyramid and leaves the three stains at 2.44 GB in total; the `.npz`/`.npy` inputs can then be deleted.

`grabe2015_stack` is NOT stored that way. A pyramid earns its keep on a 2-5 G-voxel whole-brain grid; that stack is 31 M voxels, so the viewer always reads level 0 and the extra levels are 184 files of dead weight. It is a single npz.
