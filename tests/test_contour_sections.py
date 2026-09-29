"""Slice contours: the same polygons as before, and redrawn exactly when needed.

Until 2e3ae7a every contour came from `trimesh.Trimesh.section`, one
compartment at a time; `viewer.contours.MeshSections` now computes them for a
whole atlas at once. `trimesh_sections` below is the old computation, kept as
the reference, and `assert_same_sections` states what "the same" means:

- the same compartments are cut;
- every segment where the plane crosses the mesh is drawn at most once, in
  closed polylines with no zero-length edge, and the drawn line work is
  trimesh's to within TOL_UM;
- wherever trimesh also drew each segment at most once, the polylines pair
  up one to one, each within TOL_UM of its partner.

Edges shorter than `contours.MIN_EDGE_UM`, 1e-4 um, are merged away, and so
is any edge float32 cannot resolve, as napari stores points; a loop that
collapses whole is too small to see and is left out on both sides. TOL_UM
covers that and trimesh's own vertex merging, which rounds to a 1e-5 um grid.
Otherwise the polylines differ only in where each starts and which way it
runs.

The one place trimesh draws a segment twice is a mesh seam -- distinct
vertices at one position -- where its merging joins two loops into a figure
eight that it then walks as two overlapping cycles; the male CNS neuropil
`VES(R)` has one. A compartment `MeshSections` hands back to trimesh comes
out as trimesh drew it, less any zero-length edges.

The rest is invalidation. Sections are cached per plane, and a refresh that
would draw the same shapes again does nothing, so the contours must still
follow a change of selection, of the mirror and of space, and a 2D/3D switch
must draw at most once.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from lobemap.core.meshfmt import MeshSet
from lobemap.core.registry import Registry
from lobemap.viewer.contours import ContourOverlay, MeshSections

REGISTRY = Path(__file__).resolve().parents[1] / "registry"

#: MIN_EDGE_UM, plus one cell diagonal of trimesh's 1e-5 um merge grid in a
#: plane and one of float32's below 1024 um (8.6e-5). A contour line is
#: 0.35 um wide.
TOL_UM = 2e-4

SPACES = ("FAFB14", "JRCFIB2018F", "JRCFIB2022M", "GRABE")
MESH_ASSETS = (
    "benton2025_glomeruli",
    "fafb_neuropil",
    "neuprint_hemibrain_glomeruli",
    "neuprint_hemibrain_neuropil",
    "schlegel2021_s11_glomeruli",
    "schlegel2021_s12_glomeruli",
    "neuprint_cns_glomeruli",
    "neuprint_cns_neuropil",
    "grabe2015_glomeruli",
)


# -- reference and comparison ------------------------------------------------


def _mesh(meshset: MeshSet, index: int):
    import trimesh

    v, f = meshset.compartment(index)
    return trimesh.Trimesh(vertices=v, faces=f, process=False)


def _plane(axis: int, position: float):
    origin = np.zeros(3)
    origin[axis] = position
    normal = np.zeros(3)
    normal[axis] = 1.0
    return origin, normal


def trimesh_sections(meshset: MeshSet, axis: int, position: float) -> dict:
    """Every compartment's section, computed the way 2e3ae7a computed it."""
    origin, normal = _plane(axis, position)
    out = {}
    for index in range(meshset.n_compartments):
        if meshset.face_offsets[index + 1] == meshset.face_offsets[index]:
            continue
        mesh = _mesh(meshset, index)
        lo, hi = mesh.bounds[0][axis], mesh.bounds[1][axis]
        if not (lo <= position <= hi):
            continue
        try:
            section = mesh.section(plane_origin=origin, plane_normal=normal)
        except Exception:  # noqa: S112 - as 2e3ae7a did
            continue
        if section is None:
            continue
        polys = []
        for poly in section.discrete:
            if len(poly) < 2:
                continue
            pts = np.asarray(poly, dtype=float)
            pts[:, axis] = position
            polys.append(pts)
        if polys:
            out[index] = polys
    return out


def _segments(meshset: MeshSet, index: int, axis: int, position: float) -> int:
    """How many segments the plane cuts from one compartment's faces."""
    from trimesh.intersections import mesh_plane

    origin, normal = _plane(axis, position)
    return len(mesh_plane(_mesh(meshset, index), normal, origin))


def _hausdorff(a, b) -> float:
    from scipy.spatial import cKDTree

    return max(cKDTree(b).query(a)[0].max(), cKDTree(a).query(b)[0].max())


def _closed(poly) -> bool:
    return bool(np.allclose(poly[0], poly[-1]))


def _distinct(poly) -> int:
    """Points of a polyline that float32 tells apart, closure aside."""
    return len(np.unique(np.asarray(poly, np.float32), axis=0))


def _repeats(poly) -> bool:
    """Whether a polyline has a zero-length edge in float32, closure aside."""
    ring = np.asarray(poly[:-1] if _closed(poly) else poly, np.float32)
    edges = ring - np.roll(ring, 1, axis=0) if _closed(poly) else np.diff(ring, axis=0)
    return bool(np.any(np.all(edges == 0, axis=1)))


def _identical(got, want, tol) -> bool:
    return len(got) == len(want) and all(
        a.shape == b.shape and np.allclose(a, b, rtol=0, atol=tol)
        for a, b in zip(got, want, strict=True)
    )


def assert_same_sections(meshset, axis, position, got: dict, want: dict,
                         tol: float, where: str = "") -> None:
    """`got` is trimesh's `want`, compartment by compartment; see the module doc."""
    want = {k: kept for k, polys in want.items()
            if (kept := [p for p in polys if _distinct(p) >= 3])}
    assert set(got) == set(want), (
        f"{where}: compartments differ: only drawn {sorted(set(got) - set(want))}, "
        f"only in trimesh {sorted(set(want) - set(got))}"
    )
    for index, reference in want.items():
        drawn = list(got[index])
        name = f"{where} {meshset.names[index]}"
        for poly in drawn:
            assert not _repeats(poly), f"{name}: a zero-length edge"
        if _identical(drawn, reference, tol):
            continue
        segments = _segments(meshset, index, axis, position)
        assert sum(len(p) - 1 for p in drawn) <= segments, f"{name}: segments"
        assert all(_closed(p) for p in drawn), f"{name}: an open polyline"
        distance = _hausdorff(np.vstack(drawn), np.vstack(reference))
        assert distance <= tol, f"{name}: {distance:.2e} um from trimesh"
        if sum(len(p) - 1 for p in reference) > segments:
            continue            # trimesh walked a seam twice; see the module doc
        assert len(drawn) == len(reference), (
            f"{name}: {len(drawn)} polylines, trimesh has {len(reference)}"
        )
        for poly in reference:
            best = min(range(len(drawn)), key=lambda j: _hausdorff(poly, drawn[j]))
            distance = _hausdorff(poly, drawn[best])
            assert distance <= tol, f"{name}: a polyline {distance:.2e} um from trimesh"
            assert _closed(poly), f"{name}: trimesh drew an open polyline"
            drawn.pop(best)


def _need(registry, *asset_ids) -> None:
    missing = [a for a in asset_ids if not registry.assets[a].path.exists()]
    if missing:
        pytest.skip(f"data not fetched: {', '.join(missing)}")


@pytest.fixture(scope="module")
def registry():
    return Registry.load(REGISTRY)


# -- the geometry ------------------------------------------------------------


def _parts(*named):
    return [(name, np.asarray(m.vertices, np.float32), np.asarray(m.faces))
            for name, m in named]


def _synthetic() -> MeshSet:
    """Closed meshes with several loops per plane and vertices on the planes."""
    import trimesh

    sphere = trimesh.creation.icosphere(subdivisions=3, radius=3.0)
    torus = trimesh.creation.torus(major_radius=4.0, minor_radius=1.0)
    torus.apply_translation((12.0, 0.0, 0.0))
    box = trimesh.creation.box(extents=(2.0, 2.0, 2.0))
    box.apply_translation((0.0, 10.0, 0.0))
    return MeshSet.from_parts(_parts(("sphere", sphere), ("torus", torus), ("box", box)))


# Includes planes through vertices (z = 0 is the icosphere's equator) and
# through the box's faces (z = +-1), where trimesh's on-plane rules decide.
@pytest.mark.parametrize("axis, position", [
    (2, -2.9), (2, -1.0), (2, 0.0), (2, 0.37), (2, 1.0), (2, 2.5),
    (0, 0.0), (0, 12.0), (0, 14.5), (1, 9.5), (1, 11.0), (1, 0.0),
])
def test_sections_match_trimesh_on_synthetic_meshes(axis, position):
    meshset = _synthetic()
    got = MeshSections(meshset).at(axis, position)
    want = trimesh_sections(meshset, axis, position)
    assert_same_sections(meshset, axis, position, got, want, TOL_UM,
                         f"axis {axis} at {position}")
    for polys in got.values():
        for poly in polys:
            assert np.all(poly[:, axis] == position)


def test_a_mesh_with_loose_ends_is_left_to_trimesh():
    """An open box cuts to a path with ends, which is not a loop.

    trimesh's `discrete` keeps only closed curves, so the old viewer drew no
    part of such a section, and handing it back to trimesh keeps that. The
    sphere shares the compartment, so its loop must still be drawn.
    """
    import trimesh

    box = trimesh.creation.box(extents=(2.0, 2.0, 2.0))
    side = np.flatnonzero(np.isclose(box.face_normals[:, 0], 1.0))[0]
    box = trimesh.Trimesh(box.vertices, np.delete(box.faces, side, axis=0), process=False)
    sphere = trimesh.creation.icosphere(subdivisions=2, radius=1.0)
    sphere.apply_translation((5.0, 0.0, 0.0))
    meshset = MeshSet.from_parts(_parts(("open", trimesh.util.concatenate([box, sphere]))))
    got = MeshSections(meshset).at(2, 0.25)
    want = trimesh_sections(meshset, 2, 0.25)
    assert len(want[0]) == 1, "trimesh draws the sphere's loop only"
    assert len(got[0]) == 1
    np.testing.assert_array_equal(got[0][0], want[0][0])


@pytest.mark.parametrize("asset", MESH_ASSETS)
def test_sections_match_trimesh_on_every_shipped_mesh(registry, asset):
    _need(registry, asset)
    meshset = registry.mesh(asset)
    sections = MeshSections(meshset)
    for axis in range(3):
        lo = float(meshset.vertices[:, axis].min())
        hi = float(meshset.vertices[:, axis].max())
        # Evenly spaced planes, and the same snapped to the 0.25 um steps a
        # slider moves in, which land on float32 vertex coordinates.
        for position in np.linspace(lo, hi, 6)[1:-1]:
            for p in (float(position), round(float(position) * 4) / 4):
                assert_same_sections(
                    meshset, axis, p, sections.at(axis, p),
                    trimesh_sections(meshset, axis, p),
                    TOL_UM, f"{asset} axis {axis} at {p}:",
                )


# -- through the viewer ------------------------------------------------------


def _settle():
    from qtpy.QtWidgets import QApplication

    for _ in range(3):
        QApplication.instance().processEvents()


def _open(registry, space, ndisplay=2):
    from lobemap.viewer.app import load_space

    napari = pytest.importorskip("napari")
    atlas = registry.primary_atlas(space)
    _need(registry, atlas.asset)
    viewer = napari.Viewer(show=False, ndisplay=ndisplay)
    session = load_space(viewer, registry, space, fit=False)
    _settle()
    return viewer, session, atlas.id


def _extent(viewer, surface) -> tuple[float, float]:
    """A surface's world extent along the slider's axis."""
    axis = int(viewer.dims.order[0])
    extent = surface.layer.extent.world
    return float(extent[0][axis]), float(extent[1][axis])


def _step_to(viewer, world: float) -> float:
    """Move the slider to the step nearest `world`; return where it landed."""
    axis = int(viewer.dims.order[0])
    start, _stop, step = viewer.dims.range[axis]
    viewer.dims.set_current_step(axis, round((world - start) / step))
    _settle()
    return float(viewer.dims.point[axis])


def _step_into(viewer, surface, fraction: float) -> float:
    """Put the slider `fraction` of the way through a surface."""
    lo, hi = _extent(viewer, surface)
    return _step_to(viewer, lo + fraction * (hi - lo))


def _drawn(overlay: ContourOverlay) -> dict:
    """What the contour layer holds, by compartment, named as picking names it."""
    names = overlay.meshset.names
    out: dict[int, list] = {}
    for i, pts in enumerate(overlay.layer.data):
        out.setdefault(names.index(overlay.name_at_shape(i)), []).append(
            np.asarray(pts, float))
    return out


def _expected(overlay: ContourOverlay, position: float, selection=None) -> dict:
    """The trimesh sections at `position`, for the shown compartments."""
    keep = overlay.selection if selection is None else selection
    return {
        i: polys
        for i, polys in trimesh_sections(overlay.meshset, overlay.axis, position).items()
        if i in keep
    }


def assert_draws(overlay, position, where, selection=None) -> None:
    """The layer holds trimesh's sections at `position`, as float32."""
    assert_same_sections(overlay.meshset, overlay.axis, position, _drawn(overlay),
                         _expected(overlay, position, selection), TOL_UM, where)


@pytest.mark.parametrize("space", SPACES)
def test_2d_draws_the_same_contours_labels_and_fills(registry, space):
    viewer, session, primary = _open(registry, space)
    try:
        overlay = session.contours[primary]
        surface = session.surfaces[primary]
        assert overlay.layer.visible
        for fraction in (0.3, 0.5, 0.7):
            position = _step_into(viewer, surface, fraction)
            assert_draws(overlay, position, f"{space} at {position}:")

        everything = set(overlay.selection)
        overlay.set_labels(everything)
        overlay.set_fills(everything)
        _settle()
        layer = overlay.layer
        assert layer.nshapes
        assert {str(t) for t in layer.shape_type} == {"polygon"}
        faces = np.asarray(layer.face_color)
        owners = [overlay.meshset.names.index(overlay.name_at_shape(i))
                  for i in range(layer.nshapes)]
        np.testing.assert_allclose(faces[:, 3], overlay.FILL_ALPHA, atol=1e-6)
        np.testing.assert_allclose(faces[:, :3], surface.colors[owners][:, :3], atol=1e-6)
        np.testing.assert_allclose(np.asarray(layer.edge_color)[:, :3],
                                   surface.colors[owners][:, :3], atol=1e-6)
        # One name per compartment, on its longest polyline.
        text = [str(s) for s in np.atleast_1d(layer.text.values)]
        assert len(text) == layer.nshapes
        for index, polys in _drawn(overlay).items():
            name = overlay.meshset.names[index]
            mine = [i for i in range(layer.nshapes) if overlay.name_at_shape(i) == name]
            labeled = [i for i in mine if text[i]]
            assert [text[i] for i in labeled] == [name]
            assert len(layer.data[labeled[0]]) == max(len(p) for p in polys)

        overlay.set_fills(set())
        overlay.set_labels(set())
        _settle()
        assert {str(t) for t in layer.shape_type} == {"path"}
        np.testing.assert_allclose(np.asarray(layer.face_color)[:, 3], 0.0)
        assert not any(str(s) for s in np.atleast_1d(layer.text.values))
    finally:
        viewer.close()


def test_filling_works_without_a_compiled_triangulator(registry):
    """napari's pure-Python fill raised `KeyError: (0, 0)` on a zero-length edge.

    GRABE's slider steps fall on its float32 vertex grid, so crossings a
    fraction of a float32 step apart were common there, and fills failed on
    every plane from 79.68 to 87.36 um before repeats were dropped.
    """
    from napari.utils.triangulation_backend import TriangulationBackend, set_backend

    viewer, session, primary = _open(registry, "GRABE")
    previous = set_backend(TriangulationBackend.pure_python)
    try:
        overlay = session.contours[primary]
        overlay.set_fills(set(overlay.selection))
        for world in (79.68, 83.52, 87.36):
            position = _step_to(viewer, world)
            assert overlay.layer.nshapes
            assert {str(t) for t in overlay.layer.shape_type} == {"polygon"}
            assert_draws(overlay, position, f"filled at {position}:")
    finally:
        set_backend(previous)
        viewer.close()


def test_contours_follow_the_table_on_a_cached_plane(registry):
    from qtpy.QtCore import Qt

    from lobemap.viewer.panel import INDEX_ROLE, VISIBLE_COL

    viewer, session, primary = _open(registry, "FAFB14")
    try:
        overlay = session.contours[primary]
        surface = session.surfaces[primary]
        here = _step_into(viewer, surface, 0.5)
        index = min(_drawn(overlay))
        table = session.panel.tabs[primary].table
        row = next(r for r in range(table.rowCount())
                   if table.item(r, VISIBLE_COL).data(INDEX_ROLE) == index)

        table.item(row, VISIBLE_COL).setCheckState(Qt.Unchecked)
        _settle()
        shown = set(range(overlay.meshset.n_compartments)) - {index}
        assert_draws(overlay, here, "unticked:", shown)

        # Away and back: the plane now comes from the cache, and must still
        # leave the unticked compartment out.
        _step_into(viewer, surface, 0.6)
        back = _step_into(viewer, surface, 0.5)
        assert back == here
        assert index not in _drawn(overlay)

        table.item(row, VISIBLE_COL).setCheckState(Qt.Checked)
        _settle()
        assert_draws(overlay, here, "ticked again:")
    finally:
        viewer.close()


def _switcher(viewer, registry, session):
    from lobemap.viewer.app import load_space
    from lobemap.viewer.switcher import SpaceSwitcher

    return SpaceSwitcher(
        viewer, registry, session,
        lambda space: load_space(viewer, registry, space, fit=False),
    )


def test_contours_follow_the_mirror(registry):
    """Slicing along the mirrored axis, the plane on screen is the reflected one."""
    viewer, session, primary = _open(registry, "FAFB14")
    switcher = _switcher(viewer, registry, session)
    try:
        overlay = session.contours[primary]
        surface = session.surfaces[primary]
        z = _step_into(viewer, surface, 0.5)

        # Across z the mirror changes nothing that is cut.
        switcher.mirror.setChecked(True)
        _settle()
        assert_draws(overlay, z, "mirrored, cut in z:")
        switcher.mirror.setChecked(False)
        _settle()

        viewer.dims.order = (0, 1, 2)      # the slider on x, the mirror's axis
        _settle()
        # A plane cutting the atlas both as it is and as reflected.
        center = session.mirror_center
        lo, hi = _extent(viewer, surface)
        lo, hi = max(lo, 2 * center - hi), min(hi, 2 * center - lo)
        assert lo < hi, "the atlas does not straddle the mirror plane"
        x = _step_to(viewer, lo + 0.3 * (hi - lo))
        assert_draws(overlay, x, "cut in x:")

        switcher.mirror.setChecked(True)
        _settle()
        mirrored = 2 * center - x
        assert _expected(overlay, mirrored), "the reflected plane cuts nothing"
        assert_draws(overlay, mirrored, "mirrored, cut in x:")
        # And it is drawn on the plane the slider shows.
        for pts in overlay.layer.data:
            world = overlay.layer.data_to_world(pts[0])
            assert world[0] == pytest.approx(x, abs=1e-3)

        switcher.mirror.setChecked(False)
        _settle()
        assert_draws(overlay, x, "unmirrored:")
    finally:
        viewer.close()


def test_a_new_space_draws_its_own_contours(registry):
    _need(registry, registry.primary_atlas("GRABE").asset)
    viewer, session, _primary = _open(registry, "FAFB14")
    switcher = _switcher(viewer, registry, session)
    try:
        _step_into(viewer, session.surfaces[_primary], 0.5)
        old = session.all_layers()
        switcher.combo.setCurrentIndex(switcher.combo.findData("GRABE"))
        _settle()
        session = switcher.session
        assert session.space == "GRABE"
        primary = registry.primary_atlas("GRABE").id
        overlay = session.contours[primary]
        position = _step_into(viewer, session.surfaces[primary], 0.5)
        assert_draws(overlay, position, "GRABE after FAFB14:")
        assert not any(layer in viewer.layers for layer in old)
    finally:
        viewer.close()


def test_a_mode_switch_draws_the_contours_at_most_once(registry):
    """Three hooks reach `refresh` on a switch into 2D; it used to rebuild three times."""
    viewer, session, primary = _open(registry, "FAFB14", ndisplay=3)
    try:
        writes = {name: 0 for name in session.contours}

        def counter(name):
            def count(event):
                if str(event.action) in ("added", "changed", "removed"):
                    writes[name] += 1
            return count

        for name, overlay in session.contours.items():
            overlay.layer.events.data.connect(counter(name))
        overlay = session.contours[primary]

        def switch(ndisplay):
            for name in writes:
                writes[name] = 0
            viewer.dims.ndisplay = ndisplay
            _settle()
            return dict(writes)

        first = switch(2)
        assert first[primary] == 1, first
        assert all(n <= 1 for n in first.values()), first
        position = float(viewer.dims.point[overlay.axis])
        assert_draws(overlay, position, "first entry into 2D:")
        for _ in range(2):
            assert all(n == 0 for n in switch(3).values())
            again = switch(2)
            assert all(n <= 1 for n in again.values()), again
            assert overlay.layer.visible
            assert_draws(overlay, position, "back in 2D:")

        writes[primary] = 0
        _step_into(viewer, session.surfaces[primary], 0.3)
        assert writes[primary] == 1
    finally:
        viewer.close()
