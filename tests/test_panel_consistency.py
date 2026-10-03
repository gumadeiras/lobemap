"""Every glomerulus tab reads like every other, and so does every neuropil tab.

All four spaces are opened with every tab built, and each tab is described
by what it shows: its headers, what each column holds (checked against the
registry and the reference tables, not against the panel's own rows), its
details and their order, how a missing value looks, its sort order, and
which fields its search reaches. Any glomerulus tab that differs from
another fails, and so does any neuropil tab.
"""

from __future__ import annotations

import re

import pytest

from lobemap.core import reference
from lobemap.core.names import parse_roi

pytestmark = pytest.mark.requires_data
pytest.importorskip("napari")

SPACES = ("FAFB14", "JRCFIB2018F", "JRCFIB2022M", "GRABE")

#: The tabs each brain opens, as the user reads them.
TABS = {
    "FAFB14": ["Benton 2025", "Neuropils"],
    "JRCFIB2018F": ["neuPrint", "Schlegel (sensory)", "Schlegel (projection)",
                    "Neuropils"],
    "JRCFIB2022M": ["neuPrint", "Neuropils"],
    "GRABE": ["Grabe 2015"],
}

GLOMERULUS = {
    "headers": ("Show", "Glomerulus", "Side", "Label", "Fill", "Receptor"),
    "details": ("Standard name", "Receptor", "Co-receptor", "Sensory neuron",
                "Sensillum", "Organ"),
    "placeholder": "Search name, receptor, sensillum, organ…",
    "searched": frozenset({"name", "published", "standard name", "Receptor",
                           "Co-receptor", "Sensory neuron", "Sensillum", "Organ"}),
}
NEUROPIL = {
    "headers": ("Show", "Neuropil", "Side", "Label", "Fill"),
    "details": ("Full name", "Source"),
    "placeholder": "Search neuropils…",
    "searched": frozenset({"name", "published", "Full name"}),
}

MISSING = ("—", "Not recorded")
SIDE_ORDER = {"Left": 0, "Right": 1, "Midline": 2, "—": 3}
#: A sensillum followed by a neuron letter: `ab9A`, `ac3IA`, `arB`.
NEURON = re.compile(r"^(?:[Aa][bcit]|[Pp]b|[Aa]r|sac)\d*(?:I{1,3})?[A-D]$")


def _natural(text: str):
    return [int(p) if p.isdigit() else p.lower() for p in re.split(r"(\d+)", text)]


def _joined(table, comp, published):
    """The reference row, by standard name then as published: worked out
    here from the registry, not taken from the panel."""
    for key in [*comp.canonical, published]:
        hit = table.get(key) or table.get(key.lower())
        if hit:
            return hit
    return {}


def _expected(registry, tab, index, annotation, neuropils):
    """What each field of compartment `index` should hold."""
    published = tab.surface.meshset.names[index]
    bare, suffix = parse_roi(published)
    if not tab.is_atlas:
        full, source = neuropils.get(bare, ("", ""))
        return {
            "name": bare, "published": published,
            "side": {"L": "Left", "R": "Right"}.get(suffix, "Midline"),
            "Full name": full or "—", "Source": source or "—",
        }
    comp = next(c for c in tab.compartments if c.local_id == index)
    props = _joined(annotation, comp, published)
    renamed = bool(comp.canonical) and tuple(comp.canonical) != (bare,)
    name = f"{bare} ({comp.uncertain})" if comp.uncertain else bare
    fields = {
        "name": name, "shown": name + ("*" if renamed else ""), "published": published,
        "side": {"L": "Left", "R": "Right"}.get(comp.side, "—"),
        "standard name": ", ".join(comp.canonical) or "—",
    }
    for key in reference.FIELDS:
        fields[key] = props.get(key) or "—"
    return fields


def _describe(registry, panel, name, annotation, neuropils) -> dict:
    """Everything a reader can see of one tab, and where it is wrong."""
    from qtpy.QtCore import Qt
    from qtpy.QtWidgets import QFormLayout, QLabel

    from lobemap.viewer.panel import (
        FILL_COL,
        LABEL_COL,
        NAME_COL,
        RECEPTOR_COL,
        SIDE_COL,
        VISIBLE_COL,
    )

    tab = panel.tabs[name]
    table = tab.table
    wrong: list[str] = []
    missing: set[tuple[str, str]] = set()
    blank = 0

    # The details, in the order the form lays them out.
    form = tab.details["Source" if not tab.is_atlas else "Organ"].parentWidget().layout()
    assert isinstance(form, QFormLayout)
    detail_labels = tuple(
        form.itemAt(i, QFormLayout.LabelRole).widget().text()
        for i in range(form.rowCount())
        if form.itemAt(i, QFormLayout.LabelRole) is not None
        and isinstance(form.itemAt(i, QFormLayout.LabelRole).widget(), QLabel)
    )

    expected = {}
    keys = []
    for r in range(table.rowCount()):
        index = tab._index_of(r)
        want = _expected(registry, tab, index, annotation, neuropils)
        expected[index] = want
        keys.append((_natural(want["name"]), SIDE_ORDER[want["side"]]))
        cells = {"name": table.item(r, NAME_COL), "side": table.item(r, SIDE_COL)}
        if tab.is_atlas:
            cells["Receptor"] = table.item(r, RECEPTOR_COL)
        shown = {"name": want.get("shown", want["name"]), "side": want["side"],
                 "Receptor": want.get("Receptor")}
        for key, cell in cells.items():
            if cell.text() != shown[key]:
                wrong.append(f"{name} row {want['published']}: {key} {cell.text()!r} != {shown[key]!r}")
            if cell.text() == "—":
                missing.add((cell.text(), cell.toolTip()))
            blank += not cell.text()
        rgba = tab.surface.colors[index]
        color = cells["name"].foreground().color()
        if [round(color.redF(), 2), round(color.greenF(), 2), round(color.blueF(), 2)] != \
                [round(float(v), 2) for v in rgba[:3]]:
            wrong.append(f"{name} row {want['published']}: not in its draw color")
        on = table.item(r, VISIBLE_COL).checkState() == Qt.Checked
        if on != (index in tab.surface.selection):
            wrong.append(f"{name} row {want['published']}: Show box disagrees with the drawing")
        overlay = tab.contour
        for col, held in ((LABEL_COL, overlay.labels if overlay else set()),
                          (FILL_COL, overlay.filled if overlay else set())):
            if (table.item(r, col).checkState() == Qt.Checked) != (index in held):
                wrong.append(f"{name} row {want['published']}: column {col} disagrees")

        # The details of this row, selected as a user would.
        table.selectRow(r)
        for key, label in tab.details.items():
            want_value = want["standard name"] if key == "Standard name" else want[key]
            if label.text() != want_value:
                wrong.append(f"{name} {want['published']}: {key} {label.text()!r} != {want_value!r}")
            if label.text() == "—":
                missing.add((label.text(), label.toolTip()))
            blank += not label.text()
            if key == "Sensillum" and any(NEURON.match(t) for t in label.text().split("; ")):
                wrong.append(f"{name} {want['published']}: sensillum {label.text()!r} is a neuron")
        vfb = tab.vfb.toolTip()
        if tab.is_atlas and tab.vfb.isEnabled() and not vfb.startswith(
                "Open the Virtual Fly Brain page for "):
            wrong.append(f"{name} {want['published']}: VFB tooltip {vfb!r}")
    table.clearSelection()
    chrome = _chrome(panel, name, tab)

    # The search: which fields it reaches, and that it reaches nothing else.
    def kept(needle):
        tab.filter.setText(needle)
        out = {tab._index_of(r) for r in range(table.rowCount()) if not table.isRowHidden(r)}
        tab.filter.setText("")
        return out

    fields = [f for f in next(iter(expected.values())) if f != "shown"]
    reached = set()
    for field in fields:
        values = sorted({w[field] for w in expected.values() if w[field] != "—"})[:4]
        if values and all(
            {i for i, w in expected.items() if w[field] == v} <= kept(v) for v in values
        ):
            reached.add(field)
    searched = GLOMERULUS["searched"] if tab.is_atlas else NEUROPIL["searched"]
    needles = ["DA1", "VM6", "or", "ab", "sac", "(R)", "_L", "1", "lobe", "Ito",
               "Left", "Right", "Midline", "fbbt", "virtualflybrain", "pheromon"]
    for needle in needles:
        want_rows = {i for i, w in expected.items()
                     if any(needle.lower() in w[f].lower() for f in searched
                            if w[f] != "—")}
        if kept(needle) != want_rows:
            wrong.append(f"{name}: search {needle!r} kept {len(kept(needle))}, "
                         f"wanted {len(want_rows)}")

    return {
        "kind": "glomerulus" if tab.is_atlas else "neuropil",
        "title": panel.tabText(panel.index_of(name)),
        "about": panel.tabToolTip(panel.index_of(name)),
        "headers": tuple(table.horizontalHeaderItem(c).text()
                         for c in range(table.columnCount())),
        "hidden columns": tuple(c for c in range(table.columnCount())
                                if table.isColumnHidden(c)),
        "details": detail_labels,
        "placeholder": tab.filter.placeholderText(),
        "missing": missing,
        "blank": blank,
        "sorted": keys == sorted(keys),
        "searched": tuple(sorted(reached)),
        "wrong": wrong,
        "chrome": chrome,
        "layer": tab.surface.layer.name,
    }


def _chrome(panel, name, tab) -> tuple[str, ...]:
    """Every string the tab shows that is not a value from the data: its
    title, labels, buttons, headers, placeholders and their tooltips."""
    from qtpy.QtWidgets import QLabel, QPushButton

    from lobemap.viewer.panel import FILL_COL, LABEL_COL

    index = panel.index_of(name)
    values = set(map(id, tab.details.values()))
    out = [panel.tabText(index), panel.tabToolTip(index),
           tab.filter.placeholderText(), tab.lines.itemText(0), tab.lines.toolTip()]
    out += [label.text() for label in tab.findChildren(QLabel) if id(label) not in values]
    for button in tab.findChildren(QPushButton):
        out += [button.text(), button.toolTip()]
    for c in range(tab.table.columnCount()):
        item = tab.table.horizontalHeaderItem(c)
        out += [item.text(), item.toolTip()]
    if tab.table.rowCount():
        out += [tab.table.item(0, LABEL_COL).toolTip(), tab.table.item(0, FILL_COL).toolTip()]
    return tuple(t for t in out if t)


@pytest.fixture(scope="module")
def tabs(core_data, registry):
    """space -> tab name -> its description, with every tab of every space built."""
    import napari

    from lobemap.viewer.app import build_scene
    from lobemap.viewer.panel import CompartmentPanel

    annotation = reference.load(registry.root)
    neuropils = reference.neuropil_names(registry.root)
    out: dict[str, dict[str, dict]] = {}
    for space in SPACES:
        try:
            viewer = napari.Viewer(show=False, ndisplay=3)
        except Exception as exc:                    # pragma: no cover
            pytest.skip(f"no Qt display: {exc}")
        try:
            surfaces, contours = build_scene(viewer, registry, space)
            panel = CompartmentPanel(viewer, surfaces, registry=registry,
                                     contours=contours, space=space)
            assert set(panel.tabs) == set(surfaces), "a tab was left unbuilt"
            out[space] = {name: _describe(registry, panel, name, annotation, neuropils)
                          for name in surfaces}
            out[space]["_order"] = [panel.tabText(i) for i in range(panel.count())]
        finally:
            viewer.close()
    return out


def _of_kind(tabs, kind):
    return {f"{space}/{name}": d for space, by_name in tabs.items()
            for name, d in by_name.items() if name != "_order" and d["kind"] == kind}


def test_each_brain_opens_the_approved_tabs(tabs):
    assert {space: by_name["_order"] for space, by_name in tabs.items()} == TABS


@pytest.mark.parametrize(("kind", "spec", "count"), [
    ("glomerulus", GLOMERULUS, 6),
    ("neuropil", NEUROPIL, 3),
])
def test_every_tab_of_a_kind_reads_the_same(tabs, kind, spec, count):
    described = _of_kind(tabs, kind)
    assert len(described) == count, sorted(described)
    shape = {
        key: {name: d[key] for name, d in described.items()}
        for key in ("headers", "hidden columns", "details", "placeholder",
                    "sorted", "searched", "blank")
    }
    expected = {"headers": spec["headers"], "hidden columns": (),
                "details": spec["details"], "placeholder": spec["placeholder"],
                "sorted": True, "searched": tuple(sorted(spec["searched"])), "blank": 0}
    for key, by_tab in shape.items():
        assert set(map(repr, by_tab.values())) == {repr(expected[key])}, (key, by_tab)


def test_a_missing_value_looks_the_same_everywhere(tabs):
    seen = {name: d["missing"] for kind in ("glomerulus", "neuropil")
            for name, d in _of_kind(tabs, kind).items()}
    assert set().union(*seen.values()) == {MISSING}, seen
    # Something is missing somewhere in every glomerulus tab, so the check
    # above looked at a real placeholder rather than passing on none.
    assert all(seen[name] for name in _of_kind(tabs, "glomerulus"))


def test_every_column_holds_what_its_header_says(tabs):
    wrong = [w for kind in ("glomerulus", "neuropil")
             for d in _of_kind(tabs, kind).values() for w in d["wrong"]]
    assert not wrong, "\n".join(wrong[:40])


def test_no_string_a_user_sees_is_an_id_or_jargon(tabs, registry):
    """No layer names, asset ids, snake_case, or "rows", "contour" and
    "canonical" -- the words of the code, not of the reader."""
    banned = re.compile(r"\b(rows?|contours?|canonical)\b", re.IGNORECASE)
    ids = {*registry.assets, *registry.atlases}
    layers = {d["layer"] for kind in ("glomerulus", "neuropil")
              for d in _of_kind(tabs, kind).values()}
    for kind in ("glomerulus", "neuropil"):
        for name, d in _of_kind(tabs, kind).items():
            assert d["chrome"], name
            for text in d["chrome"]:
                assert not banned.search(text), (name, text)
                assert "_" not in text, (name, text)
                assert not any(i in text for i in ids), (name, text)
                assert not any(layer in text for layer in layers), (name, text)


def test_no_tab_title_or_tooltip_is_an_id(tabs):
    for kind in ("glomerulus", "neuropil"):
        for name, d in _of_kind(tabs, kind).items():
            for text in (d["title"], d["about"]):
                assert text and "_" not in text, (name, text)
