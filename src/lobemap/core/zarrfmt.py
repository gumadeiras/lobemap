"""OME-Zarr (NGFF) storage for volumes, with a multiscale pyramid.

Why this rather than a flat `.npy`: a whole-brain stain at 0.25 um is 2-5 G
voxels, and napari cannot render that as a single array -- it has to page the
whole thing in. Given a *pyramid* it renders the coarsest level covering the
view and refines on zoom, which is the difference between viewable and not.
Chunking also makes opening lazy, restores the compression that a memory-
mapped `.npy` had to give up, and lets a store be served over plain HTTP so a
reader pulls only the chunks it looks at.

**Axis order.** This project's invariant is that a Volume's array axes match
the mesh vertex columns, which for every atlas here is (x, y, z). That is kept,
and the NGFF `axes` metadata declares it honestly rather than transposing to
the z, y, x that many readers assume. NGFF 0.4 requires only that space axes
come last, not that they are in any particular order among themselves, so this
is spec-legal -- but a reader that hardcodes z, y, x instead of reading the
metadata will show these transposed.

**Level geometry.** Factors are per axis, not a single 2^L: an axis is only
halved while it has room, so a thin z stops shrinking while x and y carry on.
That matters for confocal stacks, which are far coarser in z, and it is also
what keeps the reducer well defined -- an axis of size 1 cannot be halved, and
treating the factor as uniform would either crash or silently drop the axis.

A level whose factor on some axis is `f` has a voxel `f` times wider there,
and its first voxel center sits `(f - 1) / 2` original voxels further in. Both
go into each dataset's `coordinateTransformations`; getting the translation
wrong shifts coarse levels by up to half a voxel against the meshes, which
reads as a registration error rather than a storage bug.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

NGFF_VERSION = "0.4"
#: Mirrors imagefmt's, recorded in the group's own attributes.
FORMAT_VERSION = 1
#: 64^3 uint8 is 256 KB before compression -- small enough for range requests
#: over HTTP, large enough that per-chunk overhead stays negligible.
DEFAULT_CHUNK = (64, 64, 64)
#: Stop halving once the largest axis is this small; below it a level costs
#: more in metadata than it saves in reading.
MIN_LEVEL_EXTENT = 128


def pyramid_levels(shape, min_extent: int = MIN_LEVEL_EXTENT):
    """[(shape, factors)] per level; factors are cumulative and per axis.

    An axis halves only while it stays at or above 2, so a thin axis holds
    its size while the others keep shrinking.
    """
    shape = tuple(int(n) for n in shape)
    levels = [(shape, (1,) * len(shape))]
    while max(levels[-1][0]) > min_extent:
        cur, fac = levels[-1]
        step = tuple(2 if n >= 2 else 1 for n in cur)
        if all(s == 1 for s in step):
            break
        nxt = tuple(n // s for n, s in zip(cur, step))
        levels.append((nxt, tuple(f * s for f, s in zip(fac, step))))
    return levels


def pyramid_shapes(shape, min_extent: int = MIN_LEVEL_EXTENT) -> list[tuple[int, ...]]:
    return [s for s, _f in pyramid_levels(shape, min_extent)]


def level_transform(factors, voxel_um, origin_um):
    """Scale and translation for one level, in NGFF's order."""
    f = np.asarray(factors, dtype=float)
    voxel = np.asarray(voxel_um, dtype=float)
    origin = np.asarray(origin_um, dtype=float)
    return (voxel * f).tolist(), (origin + voxel * (f - 1.0) / 2.0).tolist()


def multiscale_metadata(levels, voxel_um, origin_um, name: str,
                        axes_names=("x", "y", "z"), unit="micrometer") -> dict:
    """The `multiscales` attribute for an NGFF 0.4 group.

    `levels` is what `pyramid_levels` returns.
    """
    datasets = []
    for level, (_shape, factors) in enumerate(levels):
        scale, translation = level_transform(factors, voxel_um, origin_um)
        datasets.append({
            "path": str(level),
            # NGFF requires scale before translation.
            "coordinateTransformations": [
                {"type": "scale", "scale": scale},
                {"type": "translation", "translation": translation},
            ],
        })
    return {
        "version": NGFF_VERSION,
        "name": name,
        "axes": [{"name": a, "type": "space", "unit": unit} for a in axes_names],
        "datasets": datasets,
    }


def downsample(src, dst, step=(2, 2, 2), block_planes: int = 64) -> None:
    """Block-mean `src` into `dst` by `step` per axis, a slab at a time.

    Mean, not subsampling: this is a density map, so averaging preserves the
    integral and gives coarse levels the same intensity scale as level 0. A
    subsampled pyramid would be noisier *and* dimmer.

    A step of 1 passes an axis through untouched. An axis whose extent does
    not divide evenly drops its trailing remainder, as every pyramid
    convention does, which is why `dst` is floor-sized.
    """
    sx, sy, sz = (int(s) for s in step)
    nx, ny, nz = (int(n) for n in dst.shape)
    for a in range(0, nx, block_planes):
        b = min(nx, a + block_planes)
        block = np.asarray(
            src[sx * a:sx * b, :sy * ny, :sz * nz], dtype=np.float32
        )
        # (sx*n, sy*m, sz*p) -> (n, sx, m, sy, p, sz), mean over the step axes
        block = block.reshape(b - a, sx, ny, sy, nz, sz).mean(axis=(1, 3, 5))
        if np.issubdtype(dst.dtype, np.integer):
            info = np.iinfo(dst.dtype)
            block = np.clip(np.rint(block), info.min, info.max)
        dst[a:b] = block.astype(dst.dtype)


def downsample_half(src, dst, block_planes: int = 64) -> None:
    """Backwards-compatible wrapper: halve every axis."""
    downsample(src, dst, (2, 2, 2), block_planes)


def read_attrs(path: str | Path) -> dict:
    """The group's attributes, without needing zarr installed."""
    p = Path(path) / ".zattrs"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    p = Path(path) / "zarr.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8")).get("attributes", {})
    raise FileNotFoundError(f"{path} has no .zattrs or zarr.json")


def _open_group(path: Path, mode: str):
    import zarr

    # zarr v2 on-disk format: NGFF 0.4 is what Fiji, neuroglancer and vizarr
    # actually read today. zarr-python 3 writes it happily via zarr_format.
    try:
        return zarr.open_group(store=str(path), mode=mode, zarr_format=2)
    except TypeError:                               # zarr-python 2.x
        return zarr.open_group(str(path), mode=mode)


def _create(group, name: str, shape, dtype, chunks, compressor):
    """Create one array, across zarr-python 2 and 3 signatures."""
    chunks = tuple(min(int(c), int(n)) for c, n in zip(chunks, shape))
    for kwargs in (
        {"compressors": compressor},                # zarr-python 3
        {"compressor": compressor},                 # zarr-python 2
    ):
        try:
            return group.create_array(
                name=name, shape=tuple(int(n) for n in shape),
                dtype=dtype, chunks=chunks, **kwargs,
            )
        except (TypeError, AttributeError):
            continue
    return group.create_dataset(
        name, shape=tuple(int(n) for n in shape), dtype=dtype,
        chunks=chunks, compressor=compressor,
    )


def default_compressor():
    from numcodecs import Blosc

    # zstd over bit-shuffled bytes: these are smooth 8-bit density maps with a
    # large near-zero background, which bit shuffling exposes to the entropy
    # coder far better than byte shuffling can at 1 byte per sample.
    return Blosc(cname="zstd", clevel=5, shuffle=Blosc.BITSHUFFLE)


def save_zarr(volume, path: str | Path, chunks=DEFAULT_CHUNK,
              min_extent: int = MIN_LEVEL_EXTENT, compressor=None,
              block_planes: int = 64) -> Path:
    """Write a Volume as an OME-Zarr group with a multiscale pyramid.

    Levels are built from the level below rather than from level 0, so the
    whole pyramid costs one extra pass over the data rather than one per
    level, and nothing larger than a slab is ever resident.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    compressor = default_compressor() if compressor is None else compressor
    levels = pyramid_levels(volume.shape, min_extent)

    group = _open_group(path, "w")
    arrays = []
    for level, (shape, _factors) in enumerate(levels):
        arr = _create(group, str(level), shape, volume.data.dtype, chunks,
                      compressor)
        if level == 0:
            step = max(1, (block_planes // max(1, chunks[0])) * chunks[0])
            for a in range(0, int(shape[0]), step):
                b = min(int(shape[0]), a + step)
                arr[a:b] = np.asarray(volume.data[a:b])
        else:
            prev_shape = levels[level - 1][0]
            stride = tuple(p // n for p, n in zip(prev_shape, shape))
            downsample(arrays[-1], arr, stride, block_planes)
        arrays.append(arr)

    meta = dict(volume.meta)
    meta.setdefault("format_version", FORMAT_VERSION)
    # `data_file` names the .npy sidecar of the npz format. Carrying it into a
    # zarr store would point a reader at a file that is not there.
    meta.pop("data_file", None)
    group.attrs["multiscales"] = [multiscale_metadata(
        levels, volume.voxel_um, volume.origin_um, meta.get("source", path.stem)
    )]
    group.attrs["lobemap"] = meta
    return path


def load_zarr(path: str | Path):
    """Read an OME-Zarr group back into a Volume, lazily.

    Geometry is taken from the NGFF `coordinateTransformations` rather than
    from our own attributes, so a store stays readable -- and correct -- even
    if it was written or rewritten by another tool.
    """
    from .imagefmt import Volume

    path = Path(path)
    group = _open_group(path, "r")
    attrs = dict(group.attrs)
    ms = attrs["multiscales"][0]
    datasets = sorted(ms["datasets"], key=lambda d: int(d["path"]))
    arrays = [group[d["path"]] for d in datasets]

    transforms = {t["type"]: t for t in datasets[0]["coordinateTransformations"]}
    voxel = tuple(float(v) for v in transforms["scale"]["scale"])
    origin = tuple(float(v) for v in
                   transforms.get("translation", {}).get("translation", (0.0,) * 3))
    return Volume(data=arrays[0], voxel_um=voxel, origin_um=origin,
                  meta=dict(attrs.get("lobemap", {})), levels=arrays)
