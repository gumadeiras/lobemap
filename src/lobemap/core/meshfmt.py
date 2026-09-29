"""Canonical mesh container.

One .npz per atlas holding every compartment concatenated, plus offsets so a
single compartment can be sliced out in O(1). That matters because the viewer
rebuilds its Surface layer on every selection change.

Vertices are ALWAYS micrometers, in the asset's native space. Storing anything
else here is the single most likely way to produce confident, wrong geometry.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .atomic import replacing

FORMAT_VERSION = 1


@dataclass
class MeshSet:
    """Concatenated triangle meshes with per-compartment slice bounds.

    `faces` indexes into the global `vertices` array. `vertex_offsets` and
    `face_offsets` are both length K+1 for K compartments.
    """

    vertices: np.ndarray  # (N, 3) float32, micrometers
    faces: np.ndarray  # (M, 3) int32, global vertex indices
    vertex_offsets: np.ndarray  # (K+1,) int64
    face_offsets: np.ndarray  # (K+1,) int64
    names: list[str]
    meta: dict

    def __post_init__(self) -> None:
        k = len(self.names)
        if len(self.vertex_offsets) != k + 1 or len(self.face_offsets) != k + 1:
            raise ValueError(
                f"offsets must be len(names)+1 = {k + 1}, got "
                f"{len(self.vertex_offsets)} / {len(self.face_offsets)}"
            )
        if self.vertex_offsets[-1] != len(self.vertices):
            raise ValueError("vertex_offsets[-1] must equal len(vertices)")
        if self.face_offsets[-1] != len(self.faces):
            raise ValueError("face_offsets[-1] must equal len(faces)")

    # -- construction ----------------------------------------------------

    @classmethod
    def from_parts(
        cls,
        parts: list[tuple[str, np.ndarray, np.ndarray]],
        meta: dict | None = None,
    ) -> MeshSet:
        """Build from [(name, vertices (n,3) um, faces (m,3) local)]."""
        names: list[str] = []
        vs: list[np.ndarray] = []
        fs: list[np.ndarray] = []
        voff = [0]
        foff = [0]
        base = 0
        for name, v, f in parts:
            v = np.ascontiguousarray(v, dtype=np.float32)
            f = np.ascontiguousarray(f, dtype=np.int64)
            if v.ndim != 2 or v.shape[1] != 3:
                raise ValueError(f"{name}: vertices must be (n, 3), got {v.shape}")
            if f.size and (f.min() < 0 or f.max() >= len(v)):
                raise ValueError(f"{name}: face indices out of range")
            names.append(name)
            vs.append(v)
            fs.append(f + base)
            base += len(v)
            voff.append(base)
            foff.append(foff[-1] + len(f))
        return cls(
            vertices=(
                np.concatenate(vs) if vs else np.zeros((0, 3), np.float32)
            ),
            faces=(
                np.concatenate(fs).astype(np.int32)
                if fs
                else np.zeros((0, 3), np.int32)
            ),
            vertex_offsets=np.asarray(voff, dtype=np.int64),
            face_offsets=np.asarray(foff, dtype=np.int64),
            names=names,
            meta=dict(meta or {}),
        )

    # -- access ----------------------------------------------------------

    @property
    def n_compartments(self) -> int:
        return len(self.names)

    def compartment(self, i: int) -> tuple[np.ndarray, np.ndarray]:
        """Vertices and *locally indexed* faces for one compartment."""
        v0, v1 = int(self.vertex_offsets[i]), int(self.vertex_offsets[i + 1])
        f0, f1 = int(self.face_offsets[i]), int(self.face_offsets[i + 1])
        return self.vertices[v0:v1], self.faces[f0:f1] - v0

    def select(
        self, indices: list[int] | np.ndarray
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Concatenate the given compartments into napari Surface data.

        Returns (vertices, faces, values) where `values` is the compartment
        index per vertex. Because compartments are disjoint meshes, every
        triangle's three vertices carry the same value -- so napari's
        barycentric interpolation during 3D picking returns that index exactly.
        """
        idx = list(indices)
        if not idx:
            return (
                np.zeros((0, 3), np.float32),
                np.zeros((0, 3), np.int32),
                np.zeros((0,), np.float32),
            )
        vs, fs, vals = [], [], []
        base = 0
        for i in idx:
            v, f = self.compartment(i)
            vs.append(v)
            fs.append(f + base)
            vals.append(np.full(len(v), i, dtype=np.float32))
            base += len(v)
        return (
            np.concatenate(vs),
            np.concatenate(fs).astype(np.int32),
            np.concatenate(vals),
        )

    def centroid(self, i: int) -> np.ndarray:
        v, _ = self.compartment(i)
        return v.mean(axis=0) if len(v) else np.full(3, np.nan, np.float32)

    def extent_um(self) -> np.ndarray:
        """Bounding-box extent of the whole set, in micrometers."""
        if not len(self.vertices):
            return np.zeros(3)
        return self.vertices.max(axis=0) - self.vertices.min(axis=0)

    def transformed(self, vertices: np.ndarray, meta: dict | None = None) -> MeshSet:
        """Same topology, new vertex positions (after a bridge or mirror)."""
        if vertices.shape != self.vertices.shape:
            raise ValueError("transformed vertices must keep the same shape")
        m = dict(self.meta)
        m.update(meta or {})
        return MeshSet(
            vertices=np.ascontiguousarray(vertices, dtype=np.float32),
            faces=self.faces,
            vertex_offsets=self.vertex_offsets,
            face_offsets=self.face_offsets,
            names=list(self.names),
            meta=m,
        )

    # -- io --------------------------------------------------------------

    def content_hash(self) -> str:
        h = hashlib.sha256()
        h.update(self.vertices.tobytes())
        h.update(self.faces.tobytes())
        h.update("\0".join(self.names).encode())
        return h.hexdigest()[:16]

    def save(self, path: str | Path) -> Path:
        """Write the container; an interrupted save leaves `path` untouched."""
        path = Path(path)
        meta = dict(self.meta)
        meta.setdefault("format_version", FORMAT_VERSION)
        meta["content_hash"] = self.content_hash()
        # Through a file handle, so numpy writes exactly this path rather
        # than appending `.npz` to one without it.
        with replacing(path) as scratch, scratch.open("wb") as fh:
            np.savez_compressed(
                fh,
                vertices=self.vertices,
                faces=self.faces,
                vertex_offsets=self.vertex_offsets,
                face_offsets=self.face_offsets,
                # JSON, not an object array: an object array can only be
                # read back through pickle, and these containers are meant
                # to be fetched rather than shipped. See `load`.
                names_json=np.asarray(json.dumps(list(self.names))),
                meta=np.asarray(json.dumps(meta)),
            )
        return path

    @classmethod
    def load(cls, path: str | Path, allow_legacy_pickle: bool = False) -> MeshSet:
        """Read a container, without unpickling.

        Containers written before names were stored as JSON hold them in a
        numpy object array, which numpy can only read by unpickling, and
        unpickling runs whatever code the file carries. A data root, the
        bridge cache or a custom `--base-url` can all hand this a file
        nobody here wrote, so such a container is refused unless the caller
        passes `allow_legacy_pickle=True` for a file it trusts. Re-saving
        migrates it: `MeshSet.load(p, allow_legacy_pickle=True).save(p)`.
        """
        path = Path(path)
        with np.load(path, allow_pickle=False) as z:
            meta = json.loads(str(z["meta"]))
            names = (json.loads(str(z["names_json"]))
                     if "names_json" in z.files else None)
            kwargs = {
                "vertices": z["vertices"],
                "faces": z["faces"],
                "vertex_offsets": z["vertex_offsets"],
                "face_offsets": z["face_offsets"],
                "meta": meta,
            }
        if names is None:
            if not allow_legacy_pickle:
                raise LegacyContainerError(
                    f"{path} stores its names as a pickled object array, and "
                    f"reading them would run pickle. If you trust the file, "
                    f"migrate it with MeshSet.load(path, "
                    f"allow_legacy_pickle=True).save(path)."
                )
            with np.load(path, allow_pickle=True) as z:
                names = [str(n) for n in z["names"]]
            kwargs["meta"] = {**meta, "legacy_names_container": True}
        return cls(names=[str(n) for n in names], **kwargs)


class LegacyContainerError(ValueError):
    """A container that can only be read by unpickling, refused by default."""
