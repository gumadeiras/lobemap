"""What each row of the panel says, before any widget shows it.

One row per compartment: a glomerulus of an atlas, or a neuropil of a
reference set, with every side of it in that one row. An atlas publishes
each side as a mesh of its own -- `VA3(L)` and `VA3(R)` -- and each is a
`Side` here; `combine` puts the sides of one name into one `Row`, so Show,
Label and Fill act on every side at once, and the details say which sides
there are and how they differ.

Every tab of a kind builds its rows here, so a column, a detail and the
search mean the same thing in all of them -- which they did not while each
was worked out inside the table: the name kept its side in two atlases and
dropped it in two others, and the search matched columns the tab had hidden.

Nothing here imports Qt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..core import reference
from ..core.names import parse_roi

#: Shown wherever a value is not recorded, with `MISSING_TIP` as its tooltip.
MISSING = "—"
MISSING_TIP = "Not recorded"

SIDES = {"L": "Left", "R": "Right"}
#: A neuropil with no side suffix is one structure across the midline.
MIDLINE = "Midline"
#: The sides of a row, in the order they are listed.
_SIDE_ORDER = {"Left": 0, "Right": 1, MIDLINE: 2, MISSING: 3}

#: Written after a glomerulus name the atlas does not share with its space's
#: standard vocabulary: a rename or a split. Its tooltip says which.
RENAMED_MARK = "*"

#: Which sides the atlas has of the compartment; the first detail of either kind.
SIDES_FIELD = "Sides"
STANDARD_NAME = "Standard name"
#: The details of a glomerulus, in the order they are listed.
GLOMERULUS_DETAILS = (SIDES_FIELD, STANDARD_NAME, *reference.FIELDS)
FULL_NAME = "Full name"
SOURCE = "Source"
#: The details of a neuropil, in the order they are listed.
NEUROPIL_DETAILS = (SIDES_FIELD, FULL_NAME, SOURCE)

RECEPTOR = "Receptor"

#: How a relation reads in a sentence; see `core.model.Relation`.
_RELATION_WORDS = {"renamed": "renamed", "split": "split", "merge": "merged"}


def natural_key(text: str):
    """DA10 after DA9, not between DA1 and DA2."""
    return [
        int(part) if part.isdigit() else part.lower()
        for part in re.split(r"(\d+)", text)
    ]


def side_name(published: str, note: str = "") -> str:
    """A compartment's name as its row shows it: without its side, with any
    doubt about it. `VP2(L)` in doubt as VM6 is 'VP2 (VM6?)'; `MB_PED_L`
    is 'MB_PED', the dataset's own abbreviation."""
    bare = parse_roi(published)[0]
    return f"{bare} ({note})" if note else bare


def _value(text: str | None) -> str:
    return (text or "").strip() or MISSING


def _searchable(*values: str) -> tuple[str, ...]:
    return tuple(v.lower() for v in values if v and v != MISSING)


@dataclass(frozen=True)
class Side:
    """One side of a compartment, as its atlas publishes it: `VA3(L)`."""

    #: Its index in the mesh.
    index: int
    #: The name without its side, with any doubt about it: `VP2 (VM6?)`.
    name: str
    #: The name exactly as published: `VP2(L)`, `AL_R`.
    published: str
    #: `Left`, `Right`, `Midline` or `MISSING`.
    where: str
    #: Field -> value, for every detail of its kind but the sides.
    details: dict[str, str] = field(default_factory=dict)
    #: What the atlas's identity for it may really be, `VM6?`, or "".
    note: str = ""
    #: Why its identity is in doubt, or "".
    doubt: str = ""
    #: What its standard name is, when it is not the published one, or "".
    standard_note: str = ""
    #: The reference table's own name for it, or "": what driver lines are
    #: keyed on.
    reference_name: str = ""
    #: Its Virtual Fly Brain term page, or "".
    vfb: str = ""
    #: The lowercase text the search looks in.
    search: tuple[str, ...] = ()

    @property
    def tip(self) -> str:
        """Why its name is marked: the doubt, then the standard name."""
        return "\n\n".join(t for t in (self.doubt, self.standard_note) if t)


@dataclass(frozen=True)
class Row:
    """One compartment as the panel shows it: every side of it, in one row."""

    #: Its place among its tab's rows, which a sorted table's row number is not.
    key: int
    #: The name without a side, with the doubt of any side: `VP2 (VM6?)`.
    name: str
    #: Left, right, midline, then unrecorded.
    sides: tuple[Side, ...]
    #: Field -> value, in the order of the kind's details, `Sides` first; a
    #: value the sides disagree on is given for each side, a line each.
    details: dict[str, str] = field(default_factory=dict)

    @property
    def indices(self) -> tuple[int, ...]:
        """Its sides' indices in the mesh: what Show, Label and Fill act on."""
        return tuple(side.index for side in self.sides)

    @property
    def shown_name(self) -> str:
        """The name, marked if any side's standard name differs from it."""
        renamed = any(side.standard_note for side in self.sides)
        return self.name + (RENAMED_MARK if renamed else "")

    @property
    def name_tip(self) -> str:
        """Why the name is marked; for each side, if they say different things."""
        return _per_side([(side.where, side.tip) for side in self.sides],
                         sep="\n\n", skip_empty=True)

    @property
    def reference_name(self) -> str:
        return next((s.reference_name for s in self.sides if s.reference_name), "")

    @property
    def vfb(self) -> str:
        return next((s.vfb for s in self.sides if s.vfb), "")

    def side(self, index: int) -> Side:
        """The side at mesh index `index`."""
        return next(side for side in self.sides if side.index == index)

    def sort_key(self):
        """Natural order on the name."""
        return natural_key(self.name)

    def matches(self, needle: str) -> bool:
        """Whether a search for `needle` keeps this row. Empty keeps all.

        Anything a side is searched on, so `DA1(R)` finds the row of DA1.
        """
        needle = needle.strip().lower()
        return not needle or any(
            needle in text for side in self.sides for text in side.search
        )


def _per_side(pairs, sep: str = "\n", skip_empty: bool = False) -> str:
    """One value if every side agrees, else 'Left: x', a line per side."""
    if len({value for _where, value in pairs}) <= 1:
        return pairs[0][1] if pairs else ""
    return sep.join(f"{where}: {value}" for where, value in pairs
                    if value or not skip_empty)


def _join(words: list[str]) -> str:
    """'left', 'left and right', 'left, right and midline'."""
    return words[0] if len(words) == 1 else f"{', '.join(words[:-1])} and {words[-1]}"


def sides_text(sides) -> str:
    """Which sides a row has, as its Sides detail: 'Left and right'.

    A doubt that only some sides carry, or that differs between them, is
    written after each: 'Left (VM6?) and right'. One every side shares is in
    the name already.
    """
    differ = len({side.note for side in sides}) > 1
    words = [side.where.lower() if side.where != MISSING else MISSING for side in sides]
    if differ:
        words = [f"{w} ({side.note})" if side.note else w
                 for w, side in zip(words, sides, strict=True)]
    text = _join(words)
    return text[:1].upper() + text[1:]


def combine(sides, fields) -> list[Row]:
    """One row per name: the sides of each, in the order the mesh first has it.

    `fields` are the kind's details after `Sides`.
    """
    groups: dict[str, list[Side]] = {}
    for side in sides:
        groups.setdefault(parse_roi(side.published)[0], []).append(side)
    rows = []
    for key, group in enumerate(groups.values()):
        group.sort(key=lambda s: _SIDE_ORDER.get(s.where, len(_SIDE_ORDER)))
        bare = parse_roi(group[0].published)[0]
        notes = list(dict.fromkeys(side.note for side in group if side.note))
        details = {SIDES_FIELD: sides_text(group)}
        details.update({
            name: _per_side([(side.where, side.details[name]) for side in group])
            for name in fields
        })
        rows.append(Row(
            key=key,
            name=f"{bare} ({', '.join(notes)})" if notes else bare,
            sides=tuple(group),
            details=details,
        ))
    return rows


def _joined(annotation, comp, published: str) -> dict:
    """The reference row of a glomerulus: by its standard names, then as
    published. The standard name is what the reference table uses, and it
    is what makes the same glomerulus match across atlases."""
    names = list(comp.canonical) if comp and comp.canonical else []
    names.append(published)
    for n in names:
        hit = annotation.get(n) or annotation.get(n.lower())
        if hit:
            return hit
    return {}


def _standard_note(bare: str, comp) -> str:
    """The sentence for a glomerulus named differently from its space's
    standard vocabulary, or "".

    Compared on the BARE name: `DA1(R)` and `DA1` are one glomerulus written
    two ways. A glomerulus with no standard name is a gap, not a difference.
    """
    if comp is None or not comp.canonical or tuple(comp.canonical) == (bare,):
        return ""
    how = _RELATION_WORDS.get(comp.relation)
    standard = ", ".join(comp.canonical)
    return (f"This atlas calls it {bare}; its standard name is {standard}"
            + (f" ({how})." if how else "."))


def hover_line(side: Side, title: str) -> str:
    """What the status bar says under the cursor: 'VA3 (left) — Benton 2025'.

    The side under the cursor, not its row's. A doubt joins the side,
    'VP2 (VM6?, left)', and a neuropil gives its full name: 'AL, antennal
    lobe (right) — Neuropils (FlyWire)'.
    """
    name = side.name
    full = side.details.get(FULL_NAME, MISSING)
    if full != MISSING:
        name = f"{name}, {full}"
    if side.where != MISSING:
        where = side.where.lower()
        # A name ends in a parenthesis only with a doubt: its side went.
        name = f"{name[:-1]}, {where})" if name.endswith(")") else f"{name} ({where})"
    return f"{name} — {title}"


def glomerulus_sides(names, compartments, annotation) -> list[Side]:
    """Each mesh name of an atlas as a side, in mesh order.

    `annotation` is `core.reference.load`'s table; a glomerulus it does not
    list shows `MISSING` in each of its fields.
    """
    by_index = {c.local_id: c for c in compartments or ()}
    out = []
    for index, published in enumerate(names):
        comp = by_index.get(index)
        bare, suffix = parse_roi(published)
        note = comp.uncertain if comp else ""
        name = side_name(published, note)
        where = (comp.side if comp else None) or suffix
        props = _joined(annotation, comp, published)
        standard = ", ".join(comp.canonical) if comp and comp.canonical else ""
        details = {STANDARD_NAME: _value(standard)}
        details.update({key: _value(props.get(key)) for key in reference.FIELDS})
        out.append(Side(
            index=index,
            name=name,
            published=published,
            where=SIDES.get(where, MISSING),
            details=details,
            note=note,
            doubt=comp.uncertain_reason if comp else "",
            standard_note=_standard_note(bare, comp),
            reference_name=props.get(reference.KEY, ""),
            vfb=props.get(reference.VFB, ""),
            search=_searchable(name, published, *details.values()),
        ))
    return out


def neuropil_sides(names, full_names) -> list[Side]:
    """Each mesh name of a neuropil set as a side, in mesh order.

    `full_names` is `core.reference.neuropil_names`'s table: the name
    without its side -> (full name, the source that gives it).
    """
    out = []
    for index, published in enumerate(names):
        bare, where = parse_roi(published)
        full, source = full_names.get(bare, ("", ""))
        details = {FULL_NAME: _value(full), SOURCE: _value(source)}
        out.append(Side(
            index=index,
            name=bare,
            published=published,
            where=SIDES.get(where, MIDLINE),
            details=details,
            search=_searchable(bare, published, details[FULL_NAME]),
        ))
    return out


def glomerulus_rows(names, compartments, annotation) -> list[Row]:
    """The rows of a glomerulus table, one per glomerulus."""
    return combine(glomerulus_sides(names, compartments, annotation),
                   GLOMERULUS_DETAILS[1:])


def neuropil_rows(names, full_names) -> list[Row]:
    """The rows of a neuropil table, one per neuropil."""
    return combine(neuropil_sides(names, full_names), NEUROPIL_DETAILS[1:])


__all__ = [
    "FULL_NAME",
    "GLOMERULUS_DETAILS",
    "MIDLINE",
    "MISSING",
    "MISSING_TIP",
    "NEUROPIL_DETAILS",
    "RECEPTOR",
    "RENAMED_MARK",
    "SIDES",
    "SIDES_FIELD",
    "SOURCE",
    "STANDARD_NAME",
    "Row",
    "Side",
    "combine",
    "glomerulus_rows",
    "glomerulus_sides",
    "hover_line",
    "natural_key",
    "neuropil_rows",
    "neuropil_sides",
    "side_name",
    "sides_text",
]
