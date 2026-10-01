"""Slice contours: the same polygons as before, and redrawn exactly when needed.

Until 2e3ae7a every contour came from `trimesh.Trimesh.section`, one
compartment at a time; `viewer.sections.MeshSections` now computes them for a
whole atlas at once. `trimesh_sections` below is the old computation, kept as
the reference, and `assert_same_sections` states what "the same" means:

- the same compartments are cut;
- every segment where the plane crosses the mesh is drawn at most once, in
  closed polylines with no zero-length edge, and the drawn line work is
  trimesh's to within TOL_UM;
- wherever trimesh also drew each segment at most once, the polylines pair
  up one to one, each within TOL_UM of its partner.

Edges shorter than `sections.MIN_EDGE_UM`, 1e-4 um, are merged away, and so
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

import numpy as np
import pytest
from viewer_harness import assert_renders_loops, contour_loops, rendered_labels

from lobemap.core.meshfmt import MeshSet
from lobemap.viewer.contours import ContourOverlay
from lobemap.viewer.sections import MeshSections

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


def open_box_and_sphere() -> MeshSet:
    """An open box alone in one compartment, a closed sphere in the other.

    A plane through the box cuts it to a path with ends, and trimesh gives
    no loop for it, so that compartment hands back nothing at all.
    """
    import trimesh

    box = trimesh.creation.box(extents=(2.0, 2.0, 2.0))
    side = np.flatnonzero(np.isclose(box.face_normals[:, 0], 1.0))[0]
    box = trimesh.Trimesh(box.vertices, np.delete(box.faces, side, axis=0), process=False)
    sphere = trimesh.creation.icosphere(subdivisions=3, radius=3.0)
    sphere.apply_translation((6.0, 0.0, 0.0))
    return MeshSet.from_parts(_parts(("open box", box), ("sphere", sphere)))


@pytest.mark.parametrize("position", [0.25, -0.5, 1.0])
def test_an_open_compartment_with_no_loop_leaves_the_others_drawn(position):
    """The open box gives no loop, so only the sphere is drawn, as trimesh draws it."""
    meshset = open_box_and_sphere()
    got = MeshSections(meshset).at(2, position)
    want = trimesh_sections(meshset, 2, position)
    assert 0 not in want and 1 in want
    assert_same_sections(meshset, 2, position, got, want, TOL_UM, f"open box at {position}")
    assert set(got) == {1}


def _triangle_area(points, faces) -> float:
    a, b, c = (np.asarray(points, float)[np.asarray(faces)[:, k]] for k in range(3))
    return float(np.abs((b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1])
                        - (b[:, 1] - a[:, 1]) * (c[:, 0] - a[:, 0])).sum()) / 2.0


@pytest.mark.parametrize("overlapping", [0, 1, 2, 3, 8, 17, 18])
def test_a_fill_never_overlaps_itself(monkeypatch, overlapping):
    """A triangulation from bermuda that covers more than the ring -- it
    overlaps itself -- gives way to the ring turned, each of `_TURNS` in
    turn, then to napari's own triangulation; the fill lies on the ring
    either way."""
    import sys
    import types

    from viewer_harness import ring_area

    from lobemap.viewer import contours, napari_private

    assert len(contours._TURNS) == 18

    calls = []

    def triangulate(polygons):
        from scipy.spatial import cKDTree

        (ring,) = polygons
        ring = np.asarray(ring, np.float32)
        points, faces = napari_private.triangulate_face(ring)
        # As bermuda does, the very points it was given, which napari moves
        # by a rounding error on a turned ring.
        faces = cKDTree(ring).query(np.asarray(points, float))[1][np.asarray(faces)]
        calls.append(np.array(ring))
        if len(calls) <= overlapping:
            faces = np.vstack([faces, faces[:1]])          # one triangle drawn twice
        return faces, ring

    monkeypatch.setitem(sys.modules, "bermuda",
                        types.SimpleNamespace(triangulate_polygons_face=triangulate))
    u = np.array([[0, 0], [3, 0], [3, 3], [2, 3], [2, 1], [1, 1], [1, 3], [0, 3]], float)
    points, faces = contours._fill(u + 100.0)
    assert len(calls) == min(overlapping + 1, len(contours._TURNS))
    assert _triangle_area(points, faces) == pytest.approx(ring_area(u), rel=1e-12)
    assert {tuple(p) for p in points[np.unique(faces)]} == {tuple(p) for p in u + 100.0}


@pytest.mark.requires_data("benton2025_glomeruli")
def test_a_fill_covers_its_ring_where_bermuda_overlaps(registry):
    """Benton's VP4 cut at y = 247 um: bermuda, given the ring in the plane's
    own order, covers 2.5% more than the ring, so overlapping triangles would
    draw darker; the fill covers the ring exactly."""
    import bermuda
    from viewer_harness import ring_area

    from lobemap.viewer.contours import _fill

    meshset = registry.mesh("benton2025_glomeruli")
    (loop,) = MeshSections(meshset).at(1, 247.0)[meshset.names.index("VP4")]
    ring = loop[:-1][:, [0, 2]]
    faces, points = bermuda.triangulate_polygons_face([np.asarray(ring, np.float32)])
    assert _triangle_area(points, faces) > 1.02 * ring_area(ring), "the case is gone"
    points, faces = _fill(ring)
    assert _triangle_area(points.astype(np.float32), faces) == pytest.approx(
        ring_area(ring), rel=1e-9)


class PanicException(BaseException):
    """What pyo3 raises when bermuda's Rust code panics: not an Exception."""


def test_a_ring_bermuda_panics_on_is_drawn_by_napari(monkeypatch):
    import sys
    import types

    from viewer_harness import ring_area

    from lobemap.viewer import contours, napari_private

    def panic(*args, **kwargs):
        raise PanicException("Segment not found in interval")

    monkeypatch.setitem(sys.modules, "bermuda", types.SimpleNamespace(
        triangulate_polygons_face=panic, triangulate_path_edge=panic))
    u = np.array([[0, 0], [3, 0], [3, 3], [2, 3], [2, 1], [1, 1], [1, 3], [0, 3]], float)
    points, faces = contours._fill(u)
    assert _triangle_area(points, faces) == pytest.approx(ring_area(u), rel=1e-12)
    vertices, triangles = contours._stroke(u, 0.35)
    centers, offsets, want = napari_private.triangulate_edge(u.astype(np.float32))
    np.testing.assert_array_equal(vertices, centers + 0.35 * offsets)
    np.testing.assert_array_equal(triangles, want)


@pytest.mark.requires_data("neuprint_cns_neuropil")
def test_a_section_bermuda_panics_on_is_filled_exactly(registry):
    """The male CNS `LA(L)` cut at y = 198 um: bermuda panics on the ring."""
    import bermuda
    from viewer_harness import ring_area

    from lobemap.viewer.contours import _fill

    meshset = registry.mesh("neuprint_cns_neuropil")
    loops = MeshSections(meshset).at(1, 198.0)[meshset.names.index("LA(L)")]
    ring = max(loops, key=len)[:-1][:, [0, 2]]
    with pytest.raises(BaseException, match="Segment not found") as caught:
        bermuda.triangulate_polygons_face([np.asarray(ring, np.float32)])
    assert type(caught.value).__name__ == "PanicException", "the case is gone"
    points, faces = _fill(ring)
    assert _triangle_area(points.astype(np.float32), faces) == pytest.approx(
        ring_area(ring), rel=1e-9)


def test_a_doubled_face_is_left_to_trimesh(monkeypatch):
    """A face listed twice cuts one segment twice: two points joined twice.

    Every point still ends two segments, so only the pairing shows it is
    not a simple loop, and the compartment goes to trimesh like any other
    that is not. Its sphere, and the separate box, are still drawn.
    """
    import trimesh

    from lobemap.viewer import sections

    sphere = trimesh.creation.icosphere(subdivisions=2, radius=1.0)
    sheet = trimesh.Trimesh([[5, 0, -1], [6, 0, 1], [5, 1, 1]], [[0, 1, 2], [0, 2, 1]],
                            process=False)
    box = trimesh.creation.box(extents=(2.0, 2.0, 2.0))
    box.apply_translation((0.0, 10.0, 0.0))
    meshset = MeshSet.from_parts(_parts(("sheeted", trimesh.util.concatenate([sphere, sheet])),
                                        ("box", box)))
    handed = []
    real = sections.MeshSections._trimesh_section

    def spy(self, index, axis, p):
        handed.append(index)
        return real(self, index, axis, p)

    monkeypatch.setattr(sections.MeshSections, "_trimesh_section", spy)
    got = MeshSections(meshset).at(2, 0.25)
    assert handed == [0]
    assert_same_sections(meshset, 2, 0.25, got, trimesh_sections(meshset, 2, 0.25),
                         TOL_UM, "doubled face")
    assert set(got) == {0, 1}


@pytest.mark.parametrize("asset", [
    pytest.param(a, marks=pytest.mark.requires_data(a)) for a in MESH_ASSETS])
def test_sections_match_trimesh_on_every_shipped_mesh(registry, asset):
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
    """The loops on screen, by compartment, named as picking names them."""
    out: dict[int, list] = {}
    for owner, loop in contour_loops(overlay):
        out.setdefault(owner, []).append(loop)
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
    """The visuals draw trimesh's sections at `position`, and only them.

    Checked on the rendered geometry too, across planes where the loop
    count rises and falls: the visuals are rebuilt on every step, and each
    outline must still be the overlay's width and its compartment's color.
    """
    assert_same_sections(overlay.meshset, overlay.axis, position, _drawn(overlay),
                         _expected(overlay, position, selection), TOL_UM, where)
    assert_renders_loops(overlay)


@pytest.mark.requires_data
def test_reference_contours_keep_their_color_and_width(registry):
    viewer, session, _primary = _open(registry, "FAFB14")
    try:
        session.panel.tab("fafb_neuropil")      # built when its tab opens
        shell = session.contours["fafb_neuropil"]
        shell.layer.visible = True
        counts = []
        for fraction in (0.2, 0.5, 0.8, 0.35, 0.65, 0.5):
            position = _step_into(viewer, session.surfaces["fafb_neuropil"], fraction)
            assert_draws(shell, position, f"neuropil at {position}:")
            counts.append(len(contour_loops(shell)))
        assert len(set(counts)) > 2, f"the loop count should vary: {counts}"
    finally:
        viewer.close()


@pytest.mark.requires_data
@pytest.mark.parametrize("space", SPACES)
def test_2d_draws_the_same_contours_labels_and_fills(registry, space):
    viewer, session, primary = _open(registry, space)
    try:
        overlay = session.contours[primary]
        surface = session.surfaces[primary]
        assert overlay.layer.visible
        for fraction in (0.3, 0.5, 0.7, 0.4, 0.6):
            position = _step_into(viewer, surface, fraction)
            assert_draws(overlay, position, f"{space} at {position}:")

        # Filled and labeled: every drawn compartment's fill covers its
        # loops, in its color, and its name is written once, on its longest
        # loop (`assert_renders_loops`).
        everything = set(overlay.selection)
        overlay.set_labels(everything)
        overlay.set_fills(everything)
        _settle()
        drawn = _drawn(overlay)
        assert drawn
        assert_draws(overlay, position, f"{space} filled at {position}:")
        assert sorted(text for text, _pos, _rgba in rendered_labels(overlay)) == sorted(
            overlay.display_names[i] for i in drawn)

        overlay.set_fills(set())
        overlay.set_labels(set())
        _settle()
        assert_draws(overlay, position, f"{space} unfilled at {position}:")
        assert not rendered_labels(overlay)
    finally:
        viewer.close()


@pytest.mark.requires_data
def test_filling_works_without_a_compiled_triangulator(registry, monkeypatch):
    """napari's pure-Python fill raised `KeyError: (0, 0)` on a zero-length edge.

    GRABE's slider steps fall on its float32 vertex grid, so crossings a
    fraction of a float32 step apart were common there, and fills failed on
    every plane from 79.68 to 87.36 um before repeats were dropped.

    Without bermuda the outlines and the fills that are not a fan come
    from napari's pure-Python triangulation.
    """
    import sys

    viewer, session, primary = _open(registry, "GRABE")
    try:
        overlay = session.contours[primary]
        overlay.set_fills(set(overlay.selection))
        # An import that fails, exactly as when the package is absent.
        monkeypatch.setitem(sys.modules, "bermuda", None)
        for world in (79.68, 83.52, 87.36):
            position = _step_to(viewer, world)
            assert _drawn(overlay)
            monkeypatch.undo()          # the check itself uses bermuda
            assert_draws(overlay, position, f"filled at {position}:")
            monkeypatch.setitem(sys.modules, "bermuda", None)
    finally:
        viewer.close()


@pytest.mark.requires_data
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


@pytest.mark.requires_data
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
        for _owner, pts in contour_loops(overlay):
            world = overlay.layer.data_to_world(pts[0])
            assert world[0] == pytest.approx(x, abs=1e-3)

        switcher.mirror.setChecked(False)
        _settle()
        assert_draws(overlay, x, "unmirrored:")
    finally:
        viewer.close()


@pytest.mark.requires_data
def test_a_new_space_draws_its_own_contours(registry):
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


@pytest.mark.requires_data
def test_a_mode_switch_draws_the_contours_at_most_once(registry):
    """Three hooks reach `refresh` on a switch into 2D; it used to rebuild three times."""
    viewer, session, primary = _open(registry, "FAFB14", ndisplay=3)
    try:
        writes = {name: 0 for name in session.contours}

        def counter(name, draw):
            # Every time the visuals are handed a new slice.
            def count(*args, **kwargs):
                writes[name] += 1
                return draw(*args, **kwargs)
            return count

        for name, overlay in session.contours.items():
            overlay.visual.draw = counter(name, overlay.visual.draw)
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
            # Nothing of the slice is drawn over the 3D scene.
            for other in session.contours.values():
                assert not (other.visual.mesh.visible or other.visual.text.visible)
            again = switch(2)
            assert all(n <= 1 for n in again.values()), again
            assert overlay.layer.visible
            assert_draws(overlay, position, "back in 2D:")

        writes[primary] = 0
        _step_into(viewer, session.surfaces[primary], 0.3)
        assert writes[primary] == 1
    finally:
        viewer.close()
