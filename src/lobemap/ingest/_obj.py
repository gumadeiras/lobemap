"""Minimal Wavefront OBJ reading: vertices and triangular faces only."""

from __future__ import annotations

import numpy as np


def parse_obj(data: bytes) -> tuple[np.ndarray, np.ndarray]:
    verts: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int]] = []
    for raw in data.decode("utf-8", "replace").splitlines():
        if raw.startswith("v "):
            x, y, z = raw.split()[1:4]
            verts.append((float(x), float(y), float(z)))
        elif raw.startswith("f "):
            idx = [int(tok.split("/")[0]) for tok in raw.split()[1:]]
            # OBJ is 1-based; negative indices count back from the end.
            idx = [i - 1 if i > 0 else len(verts) + i for i in idx]
            for k in range(1, len(idx) - 1):  # fan-triangulate
                faces.append((idx[0], idx[k], idx[k + 1]))
    return (
        np.asarray(verts, dtype=np.float64).reshape(-1, 3),
        np.asarray(faces, dtype=np.int64).reshape(-1, 3),
    )
