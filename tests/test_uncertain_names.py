"""A glomerulus whose identity is in doubt says so wherever it is named.

Grabe 2015's `VP2` material is named `VP2_*_VM6andVC6` in its Amira table and
lies at VM6's position, so the viewer writes "(VM6?)" after the name: in the
table, in the hover status and on the slice. The published name, the
nomenclature and every lookup stay `VP2(L)` / `VP2(R)`.
"""

from __future__ import annotations

import shutil

import numpy as np
import pytest
from viewer_harness import hover, launched, pump, session

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
    from qtpy.QtWidgets import QPushButton

    from lobemap.viewer.panel import LABEL_COL, NAME_COL, VISIBLE_COL

    with launched(monkeypatch, "view", "GRABE", "--ndisplay", "2") as (code, viewer):
        assert code == 0
        tab = session(viewer).panel.tabs["grabe2015"]
        surface, overlay = tab.surface, tab.contour
        vp2 = surface.meshset.names.index("VP2(L)")
        da1 = surface.meshset.names.index("DA1(L)")

        # The table, with the reason as its tooltip; a neighbor is unchanged.
        cell = tab.table.item(tab._row_of(vp2), NAME_COL)
        assert cell.text() == "VP2(L) (VM6?)"
        assert "VM6andVC6" in cell.toolTip()
        assert tab.table.item(tab._row_of(da1), NAME_COL).text() == "DA1(L)"

        # The slice label: VP2 alone, labeled, on a plane through it.
        next(b for b in tab.findChildren(QPushButton) if b.text() == "Show none").click()
        tab.table.item(tab._row_of(vp2), VISIBLE_COL).setCheckState(Qt.Checked)
        tab.table.item(tab._row_of(vp2), LABEL_COL).setCheckState(Qt.Checked)
        axis = int(viewer.dims.order[0])
        viewer.dims.set_point(axis, float(surface.meshset.centroid(vp2)[axis]))
        pump(300)
        assert "VP2(L) (VM6?)" in [str(t) for t in overlay.layer.text.values]

        # The hover status, in 2D and in 3D.
        path = max((np.asarray(p) for p in overlay.layer.data), key=len)
        assert hover(viewer, path.mean(axis=0)) == "grabe2015: VP2(L) (VM6?)"
        viewer.dims.ndisplay = 3
        pump()
        assert hover(viewer, surface.meshset.centroid(vp2)) == "grabe2015: VP2(L) (VM6?)"
