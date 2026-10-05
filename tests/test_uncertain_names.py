"""A glomerulus whose identity is in doubt says so wherever it is named.

Grabe 2015's `VP2` material is named `VP2_*_VM6andVC6` in its Amira table and
lies at VM6's position, so the viewer writes "(VM6?)" after the name: in the
table, in the hover status and on the slice. The published name, the
nomenclature and every lookup stay `VP2(L)` / `VP2(R)`.
"""

from __future__ import annotations

import shutil

import pytest
from viewer_harness import (
    clear_all,
    contour_loops,
    hover,
    launched,
    pump,
    rendered_labels,
    session,
)

pytestmark = pytest.mark.requires_data(
    "grabe2015_glomeruli", "grabe2015_labels", "grabe2015_stack")


def test_only_grabe_vp2_is_marked(registry):
    marked = {(a.id, c.published_name): c.label
              for a in registry.atlases.values() for c in a.compartments if c.uncertain}
    assert marked == {("grabe2015", "VP2(L)"): "VP2(L) (VM6?)",
                      ("grabe2015", "VP2(R)"): "VP2(R) (VM6?)"}
    vp2 = registry.atlases["grabe2015"].by_name("VP2(L)")
    assert vp2.canonical == ("VP2",) and "VM6andVC6" in vp2.uncertain_reason


def test_a_misspelled_name_is_refused(registry, registry_root, tmp_path):
    from lobemap.core.registry import Registry, RegistryError

    copy = tmp_path / "registry"
    shutil.copytree(registry_root, copy, ignore=shutil.ignore_patterns("data", "sources"))
    atlas = copy / "atlases" / "grabe2015.toml"
    atlas.write_text(atlas.read_text().replace('[uncertain."VP2(L)"]', '[uncertain."VP9(L)"]'))
    with pytest.raises(RegistryError, match="VP9"):
        Registry.load(copy, validate=False, data_root=registry.data_root)


def test_the_viewer_shows_the_doubt_where_it_names_the_glomerulus(monkeypatch):
    from qtpy.QtCore import Qt

    from lobemap.viewer.panel import LABEL_COL, NAME_COL, VISIBLE_COL

    with launched(monkeypatch, "view", "GRABE", "--ndisplay", "2") as (code, viewer):
        assert code == 0
        tab = session(viewer).panel.tabs["grabe2015"]
        surface, overlay = tab.surface, tab.contour
        vp2 = surface.meshset.names.index("VP2(L)")
        da1 = surface.meshset.names.index("DA1(L)")

        # The table, with each side's reason as its tooltip; a neighbor is
        # unchanged.
        cell = tab.table.item(tab.table_row(vp2), NAME_COL)
        assert cell.text() == "VP2 (VM6?)"
        assert cell.toolTip() == "\n\n".join(
            f"{side}: Grabe 2015 labels this region 'VP2_{side.lower()}_VM6andVC6'. "
            "When the atlas is aligned to the male CNS and to Schlegel (projection), "
            "it sits where VM6 is, not VP2."
            for side in ("Left", "Right")
        )
        assert tab.table.item(tab.table_row(da1), NAME_COL).text() == "DA1"

        # The slice label: the VP2 row alone, labeled, on a plane through it.
        clear_all(tab)
        tab.table.item(tab.table_row(vp2), VISIBLE_COL).setCheckState(Qt.Checked)
        tab.table.item(tab.table_row(vp2), LABEL_COL).setCheckState(Qt.Checked)
        axis = int(viewer.dims.order[0])
        viewer.dims.set_point(axis, float(surface.meshset.centroid(vp2)[axis]))
        pump(300)
        # As the table names it: the side is where it is.
        assert "VP2 (VM6?)" in [text for text, _pos, _rgba in rendered_labels(overlay)]

        # The hover status, in 2D and in 3D.
        path = max((loop for owner, loop in contour_loops(overlay) if owner == vp2), key=len)
        assert hover(viewer, path.mean(axis=0)) == "VP2 (VM6?, left) — Grabe 2015"
        viewer.dims.ndisplay = 3
        pump()
        assert hover(viewer, surface.meshset.centroid(vp2)) == "VP2 (VM6?, left) — Grabe 2015"
