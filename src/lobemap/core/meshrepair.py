"""Make source meshes watertight.

neuPrint's ROI meshes come out of marching cubes and are not uniformly clean:
hemibrain's AL shells are watertight, the male CNS ones (~7k vertices) are not.
A shell with holes cannot support an inside/outside test, which is what the
containment validator needs, so repair happens once at ingest rather than being
worked around at every use.

Repair CHANGES GEOMETRY -- filling a hole invents a surface that was not in the
source. Every repair is therefore recorded in the MeshSet meta, and a
compartment that cannot be made watertight is reported rather than quietly
passed through.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .meshfmt import MeshSet


@dataclass
class RepairReport:
    repaired: list[str] = field(default_factory=list)
    still_open: list[str] = field(default_factory=list)
    already_watertight: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    volume_change_pct: dict[str, float] = field(default_factory=dict)
    method: dict[str, str] = field(default_factory=dict)

    @property
    def large_changes(self) -> dict[str, float]:
        """Repairs that moved volume enough to be a geometry change."""
        return {
            k: v
            for k, v in self.volume_change_pct.items()
            if abs(v) >= VOLUME_CHANGE_WARN_PCT
        }

    @property
    def n_total(self) -> int:
        return (
            len(self.repaired)
            + len(self.still_open)
            + len(self.already_watertight)
            + len(self.failed)
        )

    def summary(self) -> str:
        return (
            f"{len(self.already_watertight)} already watertight, "
            f"{len(self.repaired)} repaired, "
            f"{len(self.still_open)} still open, "
            f"{len(self.failed)} failed"
        )


def _approx_volume(mesh) -> float:
    """Enclosed volume, tolerating an open mesh.

    Used only to quantify how much a repair changed the geometry.
    """
    try:
        return float(abs(mesh.volume))
    except Exception:  # noqa: BLE001 - degenerate input
        return 0.0


def _clean(mesh) -> None:
    """Topology hygiene that must precede hole filling."""
    mesh.merge_vertices()
    # trimesh moved these from methods to face-index properties.
    for prop in ("nondegenerate_faces", "unique_faces"):
        getter = getattr(mesh, prop, None)
        if callable(getter):
            mesh.update_faces(getter())
        elif getter is not None:
            mesh.update_faces(getter)
    mesh.remove_infinite_values()
    mesh.remove_unreferenced_vertices()


#: A repair that moves enclosed volume by more than this is reported loudly:
#: MeshFix is free to discard or bridge components, and at that magnitude it
#: has changed the anatomy rather than closed a seam.
VOLUME_CHANGE_WARN_PCT = 5.0


#: Components smaller than this are segmentation slivers, not anatomy, and are
#: dropped. A 1 um^3 blob is about 1 um across -- below anything meaningful at
#: EM segmentation scale.
MIN_COMPONENT_VOLUME_UM3 = 1.0


def _repair_one_component(mesh, trimesh):
    """Close a single connected component. Returns (mesh, method)."""
    if mesh.is_watertight:
        return mesh, "none"

    _clean(mesh)
    if not mesh.is_watertight:
        trimesh.repair.fill_holes(mesh)
    trimesh.repair.fix_winding(mesh)
    method = "trimesh.fill_holes"

    if not mesh.is_watertight:
        try:
            import pymeshfix

            mf = pymeshfix.MeshFix(
                np.asarray(mesh.vertices, dtype=np.float64),
                np.asarray(mesh.faces, dtype=np.int32),
            )
            mf.repair()
            fixed = trimesh.Trimesh(
                vertices=np.asarray(mf.points),
                faces=np.asarray(mf.faces),
                process=False,
            )
            if fixed.is_watertight:
                mesh, method = fixed, "pymeshfix"
        except ImportError:  # pragma: no cover - optional at runtime
            pass

    if mesh.is_watertight:
        trimesh.repair.fix_inversion(mesh)
        trimesh.repair.fix_normals(mesh)
    return mesh, method


def repair_mesh(
    vertices: np.ndarray, faces: np.ndarray
) -> tuple[np.ndarray, np.ndarray, bool, bool, float, str]:
    """Return (vertices, faces, was_watertight, is_watertight, dvol, method).

    Repairs each CONNECTED COMPONENT separately and keeps them all. That
    matters: several neuPrint glomeruli arrive as multiple disconnected bodies
    (male CNS VP1l is 11 pieces on the left, 5 on the right), and MeshFix's
    default is to keep only the largest -- which silently deleted 35% of VP1l's
    volume. Those pieces sit 1-4 um from the main mass and are plainly the same
    structure split by a segmentation break, not noise.

    A union of closed components is still watertight (every edge shared by
    exactly two faces), so point-in-mesh containment works unchanged.

    Within a component: trimesh's conservative `fill_holes` first, then MeshFix
    for damage past its reach.
    """
    import trimesh

    mesh = trimesh.Trimesh(
        vertices=np.asarray(vertices, dtype=np.float64),
        faces=np.asarray(faces, dtype=np.int64),
        process=False,
    )
    was = bool(mesh.is_watertight)
    if was:
        return mesh.vertices, mesh.faces, True, True, 0.0, "none"

    # NB: do not gate this on `is_volume`. That is False for precisely the open
    # meshes being repaired, which would make the change metric read 0.0 for
    # every repair -- hiding the cases worth looking at.
    before = _approx_volume(mesh)

    # Merge duplicate vertices BEFORE splitting. 3D Slicer VTPs ship every
    # triangle with its own copy of each vertex, so an unmerged split() sees
    # one component per triangle and every one of them is then discarded as a
    # sliver. Merging first collapses Benton's VM7d from 6408 vertices and
    # 1602 "components" to a watertight 1604-vertex body.
    _clean(mesh)
    if mesh.is_watertight:
        trimesh.repair.fix_inversion(mesh)
        trimesh.repair.fix_normals(mesh)
        after = _approx_volume(mesh)
        change = (after - before) / before if before > 0 else 0.0
        return mesh.vertices, mesh.faces, was, True, change, "merge_vertices"

    components = mesh.split(only_watertight=False)
    if len(components) == 0:
        components = [mesh]

    kept, methods, n_dropped = [], set(), 0
    for comp in components:
        if len(comp.faces) < 4:  # cannot enclose a volume
            n_dropped += 1
            continue
        fixed, method = _repair_one_component(comp, trimesh)
        if len(fixed.faces) < 4 or _approx_volume(fixed) < MIN_COMPONENT_VOLUME_UM3:
            n_dropped += 1
            continue
        kept.append(fixed)
        methods.add(method)

    if not kept:
        return mesh.vertices, mesh.faces, was, False, 0.0, "failed"

    out = kept[0] if len(kept) == 1 else trimesh.util.concatenate(kept)
    after = _approx_volume(out)
    change = (after - before) / before if before > 0 else 0.0
    method = "+".join(sorted(m for m in methods if m != "none")) or "none"
    if n_dropped:
        method += f" (dropped {n_dropped} slivers)"
    return out.vertices, out.faces, was, bool(out.is_watertight), change, method


def repair_meshset(ms: MeshSet) -> tuple[MeshSet, RepairReport]:
    """Repair every compartment, preserving names, order and meta."""
    report = RepairReport()
    parts: list[tuple[str, np.ndarray, np.ndarray]] = []

    for i, name in enumerate(ms.names):
        v, f = ms.compartment(i)
        try:
            nv, nf, was, now, change, method = repair_mesh(v, f)
        except Exception as exc:  # noqa: BLE001 - one bad mesh must not stop the run
            report.failed.append(f"{name}: {type(exc).__name__}: {exc}")
            parts.append((name, v, f))
            continue

        if was:
            report.already_watertight.append(name)
        elif now:
            report.repaired.append(name)
            report.volume_change_pct[name] = change * 100.0
            report.method[name] = method
        else:
            report.still_open.append(name)
            report.method[name] = method
        parts.append((name, np.asarray(nv), np.asarray(nf)))

    meta = dict(ms.meta)
    meta["repaired"] = {
        "n_repaired": len(report.repaired),
        "n_still_open": len(report.still_open),
        "n_already_watertight": len(report.already_watertight),
        "still_open": report.still_open,
        "max_volume_change_pct": (
            max(report.volume_change_pct.values(), key=abs)
            if report.volume_change_pct
            else 0.0
        ),
        "large_volume_changes": report.large_changes,
        "methods": sorted(set(report.method.values())),
    }
    return MeshSet.from_parts(parts, meta=meta), report


def watertight_status(ms: MeshSet) -> dict[str, bool]:
    """Per-compartment watertightness, for reporting and tests."""
    import trimesh

    out: dict[str, bool] = {}
    for i, name in enumerate(ms.names):
        v, f = ms.compartment(i)
        out[name] = bool(
            trimesh.Trimesh(vertices=v, faces=f, process=False).is_watertight
        )
    return out
