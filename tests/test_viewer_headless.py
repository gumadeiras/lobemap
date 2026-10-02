"""Headless viewer tests: build a real scene from the real registry.

These need a Qt display and the ingested data, so they skip cleanly when
either is absent.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

REGISTRY = Path(__file__).resolve().parents[1] / "registry"

pytest.importorskip("napari")


@pytest.fixture(scope="module")
def registry():
    from lobemap.core.registry import Registry

    if not (REGISTRY / "data").is_dir():
        pytest.skip("no ingested data")
    return Registry.load(REGISTRY)


@pytest.fixture(scope="module")
def viewer():
    import napari

    try:
        v = napari.Viewer(show=False, ndisplay=3)
    except Exception as exc:  # pragma: no cover - no display
        pytest.skip(f"no Qt display: {exc}")
    yield v
    v.close()


def test_build_scene_hemibrain(registry, viewer):
    from lobemap.viewer.app import build_scene

    surfaces, _contours = build_scene(viewer, registry, "JRCFIB2018F")
    assert "neuprint_hemibrain" in surfaces
    s = surfaces["neuprint_hemibrain"]
    assert s.meshset.n_compartments == 77
    # All compartments visible by default.
    assert len(s.layer.data[0]) == len(s.meshset.vertices)


def test_selection_rebuilds_layer(registry, viewer):
    from lobemap.viewer.app import build_scene

    s = build_scene(viewer, registry, "JRCFIB2018F")[0]["neuprint_hemibrain"]
    s.set_selection([0, 1])
    s.compact()
    v, _f, vals = s.layer.data
    expected = sum(len(s.meshset.compartment(i)[0]) for i in (0, 1))
    assert len(v) == expected
    assert set(np.unique(vals)) == {0.0, 1.0}
    s.show_none()
    assert s.layer.visible is False
    s.show_all()
    s.compact()
    assert s.layer.visible is True
    assert len(s.layer.data[0]) == len(s.meshset.vertices)


def test_picked_value_maps_back_to_a_name(registry, viewer):
    from lobemap.viewer.app import build_scene

    s = build_scene(viewer, registry, "JRCFIB2018F")[0]["neuprint_hemibrain"]
    for i in (0, 5, s.meshset.n_compartments - 1):
        assert s.name_at_value(float(i)) == s.meshset.names[i]
    assert s.name_at_value(None) is None
    assert s.name_at_value(10_000.0) is None


def test_anatomy_is_plausible(registry):
    """Guards the unit inference: a glomerulus is a glomerulus."""
    ms = registry.mesh("neuprint_hemibrain_glomeruli")
    per = np.array(
        [
            np.max(ms.compartment(i)[0].max(0) - ms.compartment(i)[0].min(0))
            for i in range(ms.n_compartments)
        ]
    )
    assert 4.0 < np.median(per) < 45.0, "glomerulus size is not anatomical"
    # Bilateral span of the whole set.
    assert 100.0 < ms.extent_um()[0] < 300.0


def test_glomeruli_sit_inside_their_neuropil(registry):
    """A cheap containment check: every glomerulus centroid is within the
    AL neuropil bounding box for its own side."""
    glom = registry.mesh("neuprint_hemibrain_glomeruli")
    npil = registry.mesh("neuprint_hemibrain_neuropil")
    # By NAME, not by position. This kept whichever compartment came last
    # for each side, which was the AL only while the neuropil asset held
    # nothing else; it now holds all 63 brain neuropils, so the box became
    # some unrelated region and every glomerulus fell outside it. The same
    # mistake was fixed in `check_containment` earlier for the same reason.
    boxes = {}
    for i, name in enumerate(npil.names):
        if not name.startswith("AL("):
            continue
        v, _ = npil.compartment(i)
        boxes["L" if "(L)" in name else "R"] = (v.min(0), v.max(0))
    assert set(boxes) == {"L", "R"}, f"no AL(L)/AL(R) in {npil.names[:5]}..."

    misses = []
    for i, name in enumerate(glom.names):
        side = "L" if name.endswith("(L)") else "R" if name.endswith("(R)") else None
        if side is None or side not in boxes:
            continue
        lo, hi = boxes[side]
        c = glom.centroid(i)
        if not np.all((c >= lo - 1.0) & (c <= hi + 1.0)):
            misses.append(name)
    assert not misses, f"centroids outside their AL: {misses}"


def test_hidden_compartment_is_not_reported_by_picking(registry, viewer):
    """Between a toggle and compaction, hidden geometry is still resident and
    can intercept the pick ray; it must not be named."""
    from lobemap.viewer.app import build_scene

    s = build_scene(viewer, registry, "JRCFIB2018F")[0]["neuprint_hemibrain"]
    s.set_selection([3, 4])
    assert s.name_at_value(3.0) == s.meshset.names[3]
    assert s.name_at_value(0.0) is None  # hidden
    s.show_all()
    assert s.name_at_value(0.0) == s.meshset.names[0]


def test_alpha_repaint_is_immediate_and_cheap(registry, viewer):
    import time

    from lobemap.viewer.app import build_scene

    s = build_scene(viewer, registry, "JRCFIB2018F")[0]["neuprint_hemibrain"]
    s.compact_delay_ms = 250  # debounce, so refresh() must not compact
    ts = []
    for i in range(10):
        t0 = time.perf_counter()
        s.set_visible(i, False)
        ts.append((time.perf_counter() - t0) * 1000)
    median = float(np.median(ts))
    assert median < 100.0, f"toggle took {median:.1f} ms"
    # Hidden compartments are alpha 0 in the colormap.
    assert float(s.layer.colormap.colors[0][3]) == 0.0
    assert float(s.layer.colormap.colors[20][3]) == 1.0


def test_a_reference_image_is_visible_wherever_it_is_present(registry):
    """If the data is on disk, the backdrop is on.

    These layers were created hidden and turned back on by each default
    scene preset, so the default only ever governed a scene that did not
    mention its own image -- and `hemibrain_three_ways` opened with the
    stain off because of it, which nobody had chosen. The preset keeps
    the power to turn one off; it is no longer what turns them on.
    """
    import napari

    from lobemap.viewer.app import load_space

    try:
        viewer = napari.Viewer(show=False)
    except Exception as exc:                        # pragma: no cover
        pytest.skip(f"no Qt display: {exc}")
    try:
        for space_id in registry.spaces:
            if not registry.atlases_in_space(space_id):
                continue            # a bridging target, never opened
            viewer.layers.clear()
            load_space(viewer, registry, space_id, fit=False)
            for layer in viewer.layers:
                meta = layer.metadata.get("lobemap", {})
                if meta.get("kind") == "image":
                    assert layer.visible, (
                        f"{space_id}: {layer.name} is present but hidden"
                    )
                elif meta.get("kind") == "labels":
                    # A segmentation of the glomeruli the meshes already
                    # draw: on by default would draw each one twice.
                    assert not layer.visible, (
                        f"{space_id}: {layer.name} should stay off"
                    )
    finally:
        viewer.close()


@pytest.mark.parametrize("ndisplay", [3, 2])
def test_a_space_opens_showing_its_primary_atlas(registry, ndisplay):
    """In 3D its mesh, in 2D its contours -- never nothing.

    A regression guard on an ordering bug. `install_display_mode` applies
    itself on installation, and in 2D its first act is to hide every
    surface; it then reads each surface's visibility to decide which
    contours to show. With the primary atlas set visible only at creation,
    it had already been hidden by the time the hook looked, so 2D opened
    with the stain and no glomeruli at all. Visibility is therefore
    re-asserted after the hook, and this checks both modes because the
    3D path never had the problem.
    """
    import napari

    from lobemap.viewer.app import load_space

    try:
        viewer = napari.Viewer(show=False, ndisplay=ndisplay)
    except Exception as exc:                        # pragma: no cover
        pytest.skip(f"no Qt display: {exc}")
    try:
        for space_id in registry.spaces:
            primary = registry.primary_atlas(space_id)
            if primary is None:
                continue
            viewer.layers.clear()
            load_space(viewer, registry, space_id, fit=False)
            wanted = primary.title or primary.id
            if ndisplay == 2:
                wanted += " [contours]"
            assert viewer.layers[wanted].visible, (
                f"{space_id} in {ndisplay}D: {wanted} is off"
            )
            # And exactly one atlas is drawn, whatever the mode.
            drawn = [
                layer.name for layer in viewer.layers
                if layer.visible and layer.name.removesuffix(" [contours]")
                in {(registry.atlases[a].title or a)
                    for a in registry.atlases}
            ]
            assert drawn == [wanted], (space_id, ndisplay, drawn)
    finally:
        viewer.close()
