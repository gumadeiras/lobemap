"""Canonical image container.

The mesh side of this project keeps every vertex in micrometers; images must
agree, or a stain lands next to the anatomy rather than on it. So a Volume
carries its voxel size and the world position of its first voxel, both in
micrometers, and nothing downstream is allowed to guess either.

Axis order is the other half of the same problem. Mesh vertices are stored as
columns (c0, c1, c2) in the source's own order; a Volume's array axes must use
that SAME order, so `array[i, j, k]` sits at world
`origin_um + (i, j, k) * voxel_um`. TIFF and NRRD readers hand back (z, y, x),
so ingest transposes explicitly and records that it did.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .atomic import replacing

FORMAT_VERSION = 1

#: Past this size the array is written beside the .npz as a plain .npy and
#: memory-mapped on load. Compression is the reason: a compressed npz must be
#: inflated whole into RAM, and a 10 GB stain then costs 10 GB to open at all.
#: Uncompressed costs disk (about 3x these files) and buys random access.
LARGE_VOLUME_BYTES = 2_000_000_000
#: Streaming granularity for hashing and copying, so neither doubles the array.
IO_CHUNK_BYTES = 256_000_000


def _plane_step(data: np.ndarray, chunk_bytes: int = IO_CHUNK_BYTES) -> int:
    """How many leading-axis planes fit in one streaming chunk."""
    plane = max(1, int(np.prod(data.shape[1:], dtype=np.int64)) * data.itemsize)
    return max(1, int(chunk_bytes // plane))


@dataclass
class Volume:
    data: np.ndarray
    voxel_um: tuple[float, float, float]
    origin_um: tuple[float, float, float] = (0.0, 0.0, 0.0)
    meta: dict = field(default_factory=dict)
    #: Multiscale pyramid, finest first, when one was stored. `data` is always
    #: level 0, so everything that does geometry keeps working unchanged and
    #: only the viewer needs to know a pyramid exists.
    levels: list | None = None

    def __post_init__(self) -> None:
        if self.data.ndim != 3:
            raise ValueError(f"expected a 3D array, got shape {self.data.shape}")
        if len(self.voxel_um) != 3 or any(v <= 0 for v in self.voxel_um):
            raise ValueError(f"voxel_um must be three positive values, got {self.voxel_um}")
        self.voxel_um = tuple(float(v) for v in self.voxel_um)
        self.origin_um = tuple(float(v) for v in self.origin_um)

    # -- geometry --------------------------------------------------------

    @property
    def shape(self) -> tuple[int, int, int]:
        return tuple(int(n) for n in self.data.shape)

    @property
    def extent_um(self) -> np.ndarray:
        return np.asarray(self.shape) * np.asarray(self.voxel_um)

    def bounds_um(self) -> tuple[np.ndarray, np.ndarray]:
        lo = np.asarray(self.origin_um, dtype=float)
        return lo, lo + self.extent_um

    def world_to_index(self, points_um: np.ndarray) -> np.ndarray:
        """Nearest voxel index for each world point. May fall outside."""
        pts = np.asarray(points_um, dtype=float)
        rel = (pts - np.asarray(self.origin_um)) / np.asarray(self.voxel_um)
        return np.rint(rel).astype(np.int64)

    def sample(self, points_um: np.ndarray, outside=0.0) -> np.ndarray:
        """Nearest-neighbor sample; points outside the volume give `outside`."""
        idx = self.world_to_index(points_um)
        ok = np.all((idx >= 0) & (idx < np.asarray(self.shape)), axis=1)
        out = np.full(len(idx), outside, dtype=float)
        if ok.any():
            i, j, k = idx[ok].T
            out[ok] = _take_points(self.data, i, j, k)
        return out

    @property
    def is_multiscale(self) -> bool:
        return bool(self.levels) and len(self.levels) > 1

    def napari_data(self):
        """What to hand napari: lazy arrays, pyramid if there is one.

        **The laziness is not an optimization, it is required.** napari slices
        a 2D view with `data[disp_slice]`, and `disp_slice` constrains only the
        *displayed* axes -- the slider axis stays `slice(None)`. On an eager
        array that expression materialises the entire level before one plane
        is projected out of it: 4 GB and 4.5 s per slider step on the FAFB
        stain. Wrapped in dask the same expression stays lazy and only the
        plane's chunks are read, which is 14 ms.
        """
        if self.is_multiscale:
            return [as_lazy(a) for a in self.levels]
        return as_lazy(self.data)

    # -- napari ----------------------------------------------------------

    def napari_kwargs(self) -> dict:
        """scale/translate that place this volume in micrometer world space.

        napari's translate is the position of voxel (0, 0, 0), which is exactly
        what `origin_um` means here.
        """
        return {"scale": self.voxel_um, "translate": self.origin_um}

    # -- io --------------------------------------------------------------

    def content_hash(self) -> str:
        """SHA-256 of the voxels plus the geometry.

        Streamed in chunks: sha256 is incremental, so this is byte-identical to
        hashing the whole array at once, but a 10 GB volume does not need a
        10 GB `tobytes()` copy to produce it.
        """
        h = hashlib.sha256()
        step = _plane_step(self.data)
        for a in range(0, self.data.shape[0], step):
            h.update(np.ascontiguousarray(self.data[a:a + step]).tobytes())
        h.update(json.dumps([self.voxel_um, self.origin_um]).encode())
        return h.hexdigest()[:16]

    def save(self, path: str | Path, sidecar: bool | None = None,
             **zarr_kwargs) -> Path:
        """Write the volume; a `.zarr` path writes OME-Zarr, `.npz` the rest.

        OME-Zarr is the preferred format: chunked, compressed and randomly
        accessible at once, and it carries a multiscale pyramid. The npz path
        stays for small volumes and for reading what already exists; there,
        arrays over `LARGE_VOLUME_BYTES` go to a `.data.npy` beside the .npz
        because a compressed npz has to be inflated whole to be opened at all.
        """
        path = Path(path)
        if path.suffix == ".zarr":
            from .zarrfmt import save_zarr

            return save_zarr(self, path, **zarr_kwargs)
        path.parent.mkdir(parents=True, exist_ok=True)
        meta = dict(self.meta)
        meta.setdefault("format_version", FORMAT_VERSION)
        meta["content_hash"] = self.content_hash()

        if sidecar is None:
            sidecar = self.data.nbytes > LARGE_VOLUME_BYTES
        # Staged and renamed into place, sidecar first, like every other
        # artifact write: an interrupted save left an npz that loaded
        # without error and read zeros.
        with replacing(path) as scratch:
            if not sidecar:
                np.savez_compressed(
                    scratch,
                    data=self.data,
                    voxel_um=np.asarray(self.voxel_um),
                    origin_um=np.asarray(self.origin_um),
                    meta=np.asarray(json.dumps(meta)),
                )
                return path

            npy = scratch.with_suffix(".data.npy")
            _stream_to_npy(self.data, npy)
            meta["data_file"] = npy.name
            np.savez(
                scratch,
                voxel_um=np.asarray(self.voxel_um),
                origin_um=np.asarray(self.origin_um),
                meta=np.asarray(json.dumps(meta)),
            )
        return path

    @classmethod
    def load(cls, path: str | Path, mmap: bool = True) -> Volume:
        """Read a volume, in whichever format it was written."""
        path = Path(path)
        if path.suffix == ".zarr" or path.is_dir():
            from .zarrfmt import load_zarr

            return load_zarr(path)
        with np.load(path, allow_pickle=False) as z:
            meta = json.loads(str(z["meta"]))
            voxel = tuple(z["voxel_um"].tolist())
            origin = tuple(z["origin_um"].tolist())
            ref = meta.get("data_file")
            data = None if ref else z["data"]
        if ref:
            side = path.parent / ref
            if not side.exists():
                raise FileNotFoundError(
                    f"{path.name} points at {ref}, which is missing; the "
                    f"volume was saved as two files and both are needed"
                )
            data = np.load(side, mmap_mode="r" if mmap else None)
        return cls(data=data, voxel_um=voxel, origin_um=origin, meta=meta)


def as_lazy(arr):
    """Wrap a chunked store in dask; pass numpy and dask through unchanged."""
    if isinstance(arr, np.ndarray):
        return arr
    try:
        import dask.array as da
    except ImportError:          # dask is a hard dependency, but do not crash
        return arr               # the viewer over a broken environment
    if isinstance(arr, da.Array):
        return arr
    chunks = getattr(arr, "chunks", None)
    return da.from_array(arr, chunks=chunks or "auto", inline_array=True)


def _take_points(arr, i, j, k) -> np.ndarray:
    """Gather scattered voxels from a numpy, memmap or zarr array.

    zarr has no fancy indexing on `__getitem__`; scattered reads go through
    `vindex`, which also groups them by chunk instead of decompressing one
    chunk per point.
    """
    vindex = getattr(arr, "vindex", None)
    if vindex is not None:
        return np.asarray(vindex[i, j, k])
    return np.asarray(arr[i, j, k])


def _stream_to_npy(data: np.ndarray, path: Path) -> Path:
    """Copy an array into a .npy a chunk at a time, never doubling it in RAM."""
    from numpy.lib.format import open_memmap

    out = open_memmap(path, mode="w+", dtype=data.dtype, shape=data.shape)
    step = _plane_step(data)
    for a in range(0, data.shape[0], step):
        out[a:a + step] = data[a:a + step]
    out.flush()
    del out
    return path
