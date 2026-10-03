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
    "headers": ("Show", "Glomerulus", "Label", "Fill", "Receptor"),
    "details": ("Sides", "Standard name", "Receptor", "Co-receptor", "Sensory neuron",
                "Sensillum", "Organ"),
    "placeholder": "Search name, receptor, sensillum, organ…",
    "searched": frozenset({"name", "published", "Standard name", "Receptor",
                           "Co-receptor", "Sensory neuron", "Sensillum", "Organ"}),
}
NEUROPIL = {
    "headers": ("Show", "Neuropil", "Label", "Fill"),
    "details": ("Sides", "Full name", "Source"),
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


def _side(tab, index, annotation, neuropils) -> dict:
    """What one side -- one mesh name -- holds, from the registry."""
    published = tab.surface.meshset.names[index]
    bare, suffix = parse_roi(published)
    if not tab.is_atlas:
        full, source = neuropils.get(bare, ("", ""))
        return {"bare": bare, "published": published, "note": "", "renamed": False,
                "side": {"L": "Left", "R": "Right"}.get(suffix, "Midline"),
                "Full name": full or "—", "Source": source or "—"}
    comp = next(c for c in tab.compartments if c.local_id == index)
    props = _joined(annotation, comp, published)
    out = {"bare": bare, "published": published, "note": comp.uncertain,
           "renamed": bool(comp.canonical) and tuple(comp.canonical) != (bare,),
           "side": {"L": "Left", "R": "Right"}.get(comp.side, "—"),
           "Standard name": ", ".join(comp.canonical) or "—"}
    for key in reference.FIELDS:
        out[key] = props.get(key) or "—"
    return out


def _expected(tab, indices, annotation, neuropils) -> dict:
    """What one row should hold: its sides, each from the registry, said
    once where they agree and a line per side where they do not."""
    sides = sorted((_side(tab, i, annotation, neuropils) for i in indices),
                   key=lambda s: SIDE_ORDER[s["side"]])
    notes = list(dict.fromkeys(s["note"] for s in sides if s["note"]))
    name = sides[0]["bare"] + (f" ({', '.join(notes)})" if notes else "")
    words = [s["side"].lower() if s["side"] != "—" else "—" for s in sides]
    if len({s["note"] for s in sides}) > 1:
        words = [f"{w} ({s['note']})" if s["note"] else w for w, s in zip(words, sides)]
    said = words[0] if len(words) == 1 else f"{', '.join(words[:-1])} and {words[-1]}"
    fields = {"name": name, "Sides": said[:1].upper() + said[1:],
              "shown": name + ("*" if any(s["renamed"] for s in sides) else "")}
    details = GLOMERULUS["details"] if tab.is_atlas else NEUROPIL["details"]
    for key in details[1:]:
        values = [s[key] for s in sides]
        fields[key] = values[0] if len(set(values)) == 1 else "\n".join(
            f"{s['side']}: {v}" for s, v in zip(sides, values))
    #: What the search may look in: every side's value of each field.
    fields["search"] = {"name": [s["bare"] + (f" ({s['note']})" if s["note"] else "")
                                 for s in sides],
                        "published": [s["published"] for s in sides]}
    for key in details[1:]:
        fields["search"][key] = [s[key] for s in sides]
    return fields


def _groups(tab) -> dict[str, set[int]]:
    """Each name's sides, from the mesh names alone."""
    out: dict[str, set[int]] = {}
    for index, published in enumerate(tab.surface.meshset.names):
        out.setdefault(parse_roi(published)[0], set()).add(index)
    return out


def _title_about(panel, name) -> tuple[str, str]:
    """How the panel names a source, and the line it says about it."""
    index = panel.index_of(name)
    return panel.tabText(index), panel.tabToolTip(index)


def _describe(registry, panel, name, annotation, neuropils) -> dict:
    """Everything a reader can see of one tab, and where it is wrong."""
    from qtpy.QtCore import Qt
    from qtpy.QtWidgets import QFormLayout, QLabel

    from lobemap.viewer.panel import (
        FILL_COL,
        LABEL_COL,
        NAME_COL,
        RECEPTOR_COL,
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
        and form.itemAt(i, QFormLayout.LabelRole).widget().text()
    )

    # One row per name, holding exactly that name's sides.
    groups = _groups(tab)
    held = [set(tab.row_at(r).indices) for r in range(table.rowCount())]
    if sorted(map(sorted, held)) != sorted(map(sorted, groups.values())):
        wrong.append(f"{name}: rows do not hold one name's sides each")

    expected = {}
    keys = []
    for r in range(table.rowCount()):
        indices = sorted(held[r])
        want = _expected(tab, indices, annotation, neuropils)
        expected[r] = want
        label = want["name"]
        keys.append(_natural(want["name"]))
        cells = {"name": table.item(r, NAME_COL)}
        if tab.is_atlas:
            cells["Receptor"] = table.item(r, RECEPTOR_COL)
        shown = {"name": want["shown"], "Receptor": want.get("Receptor")}
        for key, cell in cells.items():
            if cell.text() != shown[key]:
                wrong.append(f"{name} row {label}: {key} {cell.text()!r} != {shown[key]!r}")
            if cell.text() == "—":
                missing.add((cell.text(), cell.toolTip()))
            blank += not cell.text()
        rgba = tab.surface.colors[indices[0]]
        color = cells["name"].foreground().color()
        if [round(color.redF(), 2), round(color.greenF(), 2), round(color.blueF(), 2)] != \
                [round(float(v), 2) for v in rgba[:3]]:
            wrong.append(f"{name} row {label}: not in its draw color")

        def state(held_by, indices=indices):
            n = sum(i in held_by for i in indices)
            return (Qt.CheckState.Checked if n == len(indices)
                    else Qt.CheckState.PartiallyChecked if n else Qt.CheckState.Unchecked)

        if table.item(r, VISIBLE_COL).checkState() != state(tab.surface.selection):
            wrong.append(f"{name} row {label}: Show box disagrees with the drawing")
        overlay = tab.contour
        for col, by in ((LABEL_COL, overlay.labels if overlay else set()),
                        (FILL_COL, overlay.filled if overlay else set())):
            if table.item(r, col).checkState() != state(by):
                wrong.append(f"{name} row {label}: column {col} disagrees")

        # The details of this row, selected as a user would.
        table.selectRow(r)
        if tab.detail_title.text() != want["name"]:
            wrong.append(f"{name} {label}: title {tab.detail_title.text()!r}")
        for key, value in tab.details.items():
            if value.text() != want[key]:
                wrong.append(f"{name} {label}: {key} {value.text()!r} != {want[key]!r}")
            if value.text() == "—":
                missing.add((value.text(), value.toolTip()))
            blank += not value.text()
            if key == "Sensillum" and any(NEURON.match(t) for t in value.text().split("; ")):
                wrong.append(f"{name} {label}: sensillum {value.text()!r} is a neuron")
        vfb = tab.vfb.toolTip()
        if tab.is_atlas and tab.vfb.isEnabled() and not vfb.startswith(
                "Open the Virtual Fly Brain page for "):
            wrong.append(f"{name} {label}: VFB tooltip {vfb!r}")
    table.clearSelection()
    chrome = _chrome(panel, name, tab)

    # The search: which fields it reaches, and that it reaches nothing else.
    def kept(needle):
        tab.filter.setText(needle)
        out = {r for r in range(table.rowCount()) if not table.isRowHidden(r)}
        tab.filter.setText("")
        return out

    fields = list(next(iter(expected.values()))["search"])
    reached = set()
    for field in fields:
        values = sorted({v for w in expected.values() for v in w["search"][field]
                         if v != "—"})[:4]
        if values and all(
            {r for r, w in expected.items() if v in w["search"][field]} <= kept(v)
            for v in values
        ):
            reached.add(field)
    searched = GLOMERULUS["searched"] if tab.is_atlas else NEUROPIL["searched"]
    needles = ["DA1", "VM6", "or", "ab", "sac", "(R)", "_L", "1", "lobe", "Ito",
               "Left", "Right", "Midline", "fbbt", "virtualflybrain", "pheromon"]
    for needle in needles:
        want_rows = {r for r, w in expected.items()
                     if any(needle.lower() in v.lower() for f in searched
                            for v in w["search"][f] if v != "—")}
        if kept(needle) != want_rows:
            wrong.append(f"{name}: search {needle!r} kept {len(kept(needle))}, "
                         f"wanted {len(want_rows)}")

    title, about = _title_about(panel, name)
    return {
        "kind": "glomerulus" if tab.is_atlas else "neuropil",
        "title": title,
        "about": about,
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
