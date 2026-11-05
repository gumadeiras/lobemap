"""Exact mesh picking, with a spatial index for large compartments.

The index only filters candidates. napari's triangle tests still decide
the hit, so thin tubes, overlapping meshes and perspective keep their
usual meaning. Index construction reads only the immutable MeshSet and
can run in a background job.
"""

from __future__ import annotations

import threading
from itertools import chain

import numpy as np

from ..core.meshfmt import MeshSet

# Small glomeruli already have cheap compartment-level culling.
INDEX_MIN_FACES = 16_384

# Short boxes follow oblique rays; one box can cover almost an entire arbor.
RAY_SEGMENTS = 32


class MeshPicker:
    def __init__(self, meshset: MeshSet) -> None:
        self.meshset = meshset
        self.lo = np.full((meshset.n_compartments, 3), np.nan)
        self.hi = np.full_like(self.lo, np.nan)
        for index in range(meshset.n_compartments):
            start, stop = meshset.vertex_offsets[index:index + 2]
            vertices = meshset.vertices[start:stop]
            if len(vertices):
                self.lo[index], self.hi[index] = vertices.min(axis=0), vertices.max(axis=0)
        self.large = np.flatnonzero(np.diff(meshset.face_offsets) >= INDEX_MIN_FACES)
        self._trees = {}
        # libspatialindex does not support simultaneous queries, even read-only.
        self._lock = threading.Lock()
        self._cancelled = threading.Event()

    def prepare(self) -> dict:
        """Build indices off the UI thread; return an empty dict if cancelled."""
        from trimesh.triangles import bounds_tree

        trees = {}
        for index in self.large:
            if self._cancelled.is_set():
                return {}
            start, stop = self.meshset.face_offsets[index:index + 2]
            trees[int(index)] = bounds_tree(self.meshset.vertices[self.meshset.faces[start:stop]])
        return {} if self._cancelled.is_set() else trees

    def cancel(self) -> None:
        """Stop preparation after the current compartment; safe from any thread."""
        self._cancelled.set()

    def install(self, trees: dict) -> None:
        """Publish a completed build; queries use full scans until it is ready."""
        self._trees = trees

    def pick(self, start, direction, selection, first=None) -> int | None:
        """The selected compartment hit first along a unit ray in mesh coordinates."""
        from napari.utils.geometry import (
            intersect_line_with_triangles,
            line_in_triangles_3d,
        )

        indices = np.array(sorted(selection), dtype=np.int64)
        indices = indices[np.isfinite(self.lo[indices]).all(axis=1)]
        if not len(indices):
            return None
        with np.errstate(divide="ignore", invalid="ignore"):
            near = (self.lo[indices] - start) / direction
            far = (self.hi[indices] - start) / direction
        enter = np.maximum(np.nanmax(np.minimum(near, far), axis=1), first or 0.0)
        leave = np.nanmin(np.maximum(near, far), axis=1)
        crossed = leave >= enter
        best, best_t = None, np.inf
        for j in np.flatnonzero(crossed)[np.argsort(enter[crossed])]:
            if enter[j] > best_t:
                break
            index = int(indices[j])
            begin, end = self.meshset.face_offsets[index:index + 2]
            f = self.meshset.faces[begin:end]
            tree = self._trees.get(index)
            if tree is not None:
                segments = RAY_SEGMENTS if np.count_nonzero(direction) > 1 else 1
                along = np.linspace(enter[j], leave[j], segments + 1)
                points = start + along[:, None] * direction
                lower = np.minimum(points[:-1], points[1:]) - 1e-5
                upper = np.maximum(points[:-1], points[1:]) + 1e-5
                with self._lock:
                    candidates = np.fromiter(chain.from_iterable(
                        tree.intersection(box) for box in np.column_stack((lower, upper))),
                        dtype=np.int64)
                candidates = np.unique(candidates)
                f = f[candidates]
            if not len(f):
                continue
            triangles = self.meshset.vertices[f]
            met = line_in_triangles_3d(start, direction, triangles)
            if not met.any():
                continue
            points = intersect_line_with_triangles(start, direction, triangles[met])
            t = (np.asarray(points, float) - start) @ direction
            if first is not None:
                t = t[t >= first]
            if t.size and float(t.min()) < best_t:
                best, best_t = index, float(t.min())
        return best
