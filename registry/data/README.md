# Ingested assets

Nothing here is tracked. The artifacts are published as release assets;
`lobemap fetch` puts them on disk from the `base_url` in
`registry/manifest.toml`, verified against the sha256 recorded there.

What follows is how each one is rebuilt from its source, which is what
`registry/recipes.toml` automates and `lobemap build` runs. Use it when
you are regenerating an asset rather than installing; `lobemap pack` then
writes the copies to upload.

Regenerate with, e.g.:

```
lobemap ingest neuprint --dataset hemibrain:v1.2.1 \
    --asset-id neuprint_hemibrain_glomeruli --atlas-id neuprint_hemibrain
lobemap ingest neuprint --dataset hemibrain:v1.2.1 --role neuropil \
    --asset-id neuprint_hemibrain_neuropil
lobemap ingest neuprint --dataset male-cns:v1.0 \
    --asset-id neuprint_cns_glomeruli --atlas-id neuprint_cns
lobemap ingest neuprint --dataset male-cns:v1.0 --role neuropil \
    --asset-id neuprint_cns_neuropil
```

Needs `NEUPRINT_APPLICATION_CREDENTIALS`.

## Schlegel 2021

Supplementary files 11 and 12 are fetched from the eLife CDN (CC BY 4.0):

```
https://cdn.elifesciences.org/articles/66018/elife-66018-supp11-v2.zip
https://cdn.elifesciences.org/articles/66018/elife-66018-supp12-v2.zip
```

Then ingested with `lobemap.ingest.obj_archive.ingest(<zip>)`.

## Grabe 2015

Surfaced from the Amira label volume (not the OBJ export), plus the confocal
stack, both from `registry/sources/grabe-2015/`:

```python
from lobemap.ingest.label_volume import ingest as ingest_labels
from lobemap.ingest.image_stack import ingest as ingest_stack
```

See `registry/assets.toml` for why the masks rather than the OBJs.

## Virtual neuropil stains

Presynapses only, from the published bulk releases; sigma 450 nm; 0.25 um
bins. The bounds are the held neuropil geometry plus a 5 um margin, passed
explicitly so a rebuild reproduces the same physical box. The male CNS bounds
also crop the VNC away.

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

Sources, ~20 GB in total, are not kept:

```
gs://neuroglancer-janelia-flyem-hemibrain/v1.2/synapses/by_id/   (8 shards, 4.2 GB)
https://storage.googleapis.com/flyem-male-cns/v1.0/connectome-data/
  flat-connectome/syn-points-male-cns-v1.0-minconf-0.5.feather   (13.1 GB)
FAFB v783 Princeton synapse table                                 (2.7 GB)
```

At 0.25 um each grid is 2-5 G voxels, so the build goes slab by slab through
`--workdir` (default `registry/data/.stainwork`), which needs about 40 GB free
and is deleted afterwards.

`stain` writes uint8 `.npz` (plus a `<id>.data.npy` sidecar past 2 GB).
Convert to OME-Zarr afterwards, which is what the registry points at:

```
lobemap tozarr registry/data/hemibrain_stain.npz
lobemap tozarr registry/data/fafb_stain.npz
lobemap tozarr registry/data/malecns_stain.npz
```

That builds a 5-6 level multiscale pyramid and leaves the three stains at
2.30 GB in total; the `.npz`/`.npy` inputs can then be deleted.

`grabe2015_stack` is NOT stored that way. A pyramid earns its keep on a
2-5 G-voxel whole-brain grid; that stack is 31 M voxels, so the viewer
always reads level 0 and the extra levels are 184 files of dead weight.
It is a single npz.
