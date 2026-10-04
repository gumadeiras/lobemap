"""Every string lobemap's window shows, and which of them read as code.

`collect` walks the window as it is: its title, every dock, tab, label,
button, menu, table cell and tooltip, napari's layer list, layer settings,
button rows, the popups they have opened, and sliders, and the status bar.
`open_popups` opens the popups napari's buttons have, as a right-click does. `hover_all` moves the cursor over what is
drawn, through napari's own mouse-move path, and collects what the status
bar says. `problems` names each string that holds an identifier, given the
`Allowed` vocabulary of the registry and what napari itself shows.

Strings napari shows on its own -- its menus, its layer-settings labels,
its buttons and popups -- are napari's wording, not lobemap's, and
`napari_baseline` collects them from a bare viewer holding a layer of each
kind lobemap adds, its popups opened in 2D and in 3D.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import numpy as np

#: Abbreviations lobemap shows, and where each is spelled out: the Brain
#: menu's tooltip of the brain whose title carries it.
EXPLAINED = {
    "EM": "electron microscopy",
    "CNS": "central nervous system",
    "FAFB": "full adult fly brain",
}
#: Units napari writes after a pyramid level's size, which need no spelling out.
UNITS = {"KB", "MB", "GB", "TB"}

SNAKE = re.compile(r"[A-Za-z0-9]_[A-Za-z0-9]")
BRACKETED = re.compile(r"\[[^\]]*\]")
ABBREVIATION = re.compile(r"\b[A-Z][A-Z0-9]+\b")
#: Quoted spans are a source's own label, shown as such.
QUOTED = re.compile(r"'[^']*'|\"[^\"]*\"|‘[^’]*’|“[^”]*”")
#: What separates the words a vocabulary is matched on.
SPLIT = re.compile(r"[\s,;()]+")


@dataclass
class Allowed:
    """What may read like code: the biology the registry names, and the rest."""

    #: Glomerulus, neuropil, receptor, neuron, sensillum, organ and driver
    #: line names, word by word.
    biology: set[str] = field(default_factory=set)
    #: Each neuropil set's own abbreviations, as its dataset publishes them
    #: less the side -- `MB_CA` in FlyWire, `CA` in neuPrint -- which the
    #: table and the slice show, and the asset's `about` cites. Exactly
    #: these: a name with its side still on, `MB_PED_L`, reads as code.
    neuropils: set[str] = field(default_factory=set)
    #: Asset and atlas ids, which must never show.
    ids: set[str] = field(default_factory=set)
    #: Published template names the Brain menu's tooltips name.
    templates: set[str] = field(default_factory=set)
    #: The citations a tab's tooltip opens with -- "Benton et al. 2025,
    #: EMBO Reports, Dataset EV2" -- word by word: a source's own label.
    sources: set[str] = field(default_factory=set)
    #: Exactly what napari shows of its own.
    napari: set[str] = field(default_factory=set)

    @classmethod
    def from_registry(cls, registry) -> Allowed:
        from lobemap.core import reference
        from lobemap.core.names import parse_roi

        words: set[str] = set()

        def add(text) -> None:
            if not text:
                return
            words.update(w for w in SPLIT.split(str(text)) if w)

        for atlas in registry.atlases.values():
            for comp in atlas.compartments:
                for name in (comp.published_name, *comp.canonical, comp.uncertain):
                    add(name)
                    add(parse_roi(name)[0] if name else "")
        atlas_assets = {atlas.asset for atlas in registry.atlases.values()}
        neuropils = {parse_roi(name)[0]
                     for asset in registry.assets.values()
                     if asset.kind == "meshset" and asset.id not in atlas_assets
                     and asset.about and asset.path.exists()
                     for name in registry.mesh(asset.id).names}
        for row in reference.load(registry.root).values():
            for value in row.values():
                add(value)
        for line in reference.lines(registry.root):
            add(line)
        for _name, (full, _source) in reference.neuropil_names(registry.root).items():
            add(full)
        templates = {s.flybrains_template for s in registry.spaces.values()
                     if s.flybrains_template}
        sources = {w for asset in registry.assets.values()
                   for w in SPLIT.split(asset.about.partition(":")[0]) if w}
        return cls(biology=words, neuropils=neuropils,
                   ids={*registry.assets, *registry.atlases},
                   templates=templates, sources=sources)


@dataclass(frozen=True)
class Shown:
    """One string, where it is shown, and the tooltip it is shown with."""

    where: str
    text: str
    tip: str = ""


def problems(shown, allowed: Allowed) -> list[tuple[Shown, str]]:
    """Each string that reads as code, with why."""
    out = []
    for item in shown:
        if item.text in allowed.napari:
            continue
        why = why_code(item.text, allowed, context=item.tip)
        if why:
            out.append((item, why))
    return out


def why_code(text: str, allowed: Allowed, context: str = "") -> str:
    """Why a string reads as code, or "" if it does not."""
    for i in sorted(allowed.ids, key=len, reverse=True):
        if re.search(rf"(?<![\w.]){re.escape(i)}(?![\w])", text):
            return f"id {i}"
    rest = QUOTED.sub(" ", text)
    words = (w.strip(".:!?*") for w in SPLIT.split(rest))
    rest = " ".join(w for w in words
                    if w and w not in allowed.biology and w not in allowed.neuropils
                    and w not in allowed.templates
                    and w not in allowed.sources and w not in UNITS)
    if BRACKETED.search(rest):
        return "bracketed tag"
    if SNAKE.search(rest):
        return "snake_case"
    for word in ABBREVIATION.findall(rest):
        if word not in EXPLAINED:
            return f"unexplained abbreviation {word}"
    return ""


# -- collecting ---------------------------------------------------------------


def _widget_strings(root, where: str) -> list[Shown]:
    """What every widget under `root` shows: texts, items, cells and tips."""
    from qtpy.QtCore import Qt
    from qtpy.QtWidgets import (
        QAbstractButton,
        QAbstractSpinBox,
        QComboBox,
        QDoubleSpinBox,
        QGroupBox,
        QLabel,
        QLineEdit,
        QSpinBox,
        QTabBar,
        QTableWidget,
        QWidget,
    )

    out: list[Shown] = []

    def add(kind, text, tip="") -> None:
        if text and str(text).strip():
            out.append(Shown(f"{where} / {kind}", str(text), tip or ""))

    for w in [root, *root.findChildren(QWidget)]:
        tip = w.toolTip()
        add("tooltip", tip)
        if isinstance(w, QLabel):
            add("label", w.text(), tip)
        elif isinstance(w, QAbstractButton):
            add("button", w.text(), tip)
        elif isinstance(w, QLineEdit):
            add("placeholder", w.placeholderText(), tip)
        elif isinstance(w, QGroupBox):
            add("group", w.title(), tip)
        elif isinstance(w, QComboBox):
            for i in range(w.count()):
                item_tip = w.itemData(i, Qt.ItemDataRole.ToolTipRole) or ""
                add("menu item", w.itemText(i), item_tip or tip)
                add("menu item tooltip", item_tip)
        elif isinstance(w, QTabBar):
            for i in range(w.count()):
                add("tab", w.tabText(i), w.tabToolTip(i))
                add("tab tooltip", w.tabToolTip(i))
        elif isinstance(w, QTableWidget):
            for c in range(w.columnCount()):
                head = w.horizontalHeaderItem(c)
                if head is not None:
                    add("column header", head.text(), head.toolTip())
                    add("column header tooltip", head.toolTip())
            for r in range(w.rowCount()):
                for c in range(w.columnCount()):
                    cell = w.item(r, c)
                    if cell is not None:
                        add("cell", cell.text(), cell.toolTip())
                        add("cell tooltip", cell.toolTip())
        if isinstance(w, (QSpinBox, QDoubleSpinBox)):
            add("suffix", w.suffix().strip(), tip)
            add("box", w.specialValueText(), tip)
        elif isinstance(w, QAbstractSpinBox):
            add("box", w.text(), tip)
    return out


def _menu_strings(menu, where: str) -> list[Shown]:
    out = []
    for action in menu.actions():
        if action.isSeparator():
            continue
        text = action.text().replace("&", "")
        if text:
            out.append(Shown(f"{where} / menu", text, action.toolTip()))
        sub = action.menu()
        if sub is not None:
            sub.aboutToShow.emit()
            out += _menu_strings(sub, where)
    return out


def collect(viewer) -> list[Shown]:
    """Every string the window shows now, napari's included."""
    from qtpy.QtWidgets import QDockWidget

    window = viewer.window._qt_window
    out = [Shown("window title", window.windowTitle())]
    for dock in window.findChildren(QDockWidget):
        out.append(Shown("dock title", dock.windowTitle()))
        if dock.widget() is not None:
            out += _widget_strings(dock.widget(), dock.windowTitle())
    qt_viewer = viewer.window._qt_viewer
    out += _widget_strings(qt_viewer.dims, "sliders")
    out += _menu_strings(window.menuBar(), "menu bar")
    for layer in viewer.layers:
        out.append(Shown("layer name", layer.name))
        colormap = getattr(layer, "colormap", None)
        name = getattr(colormap, "name", None)
        if name:
            out.append(Shown("colormap", name))
    out += [Shown("slider label", label) for label in viewer.dims.axis_labels]
    for what in ("status", "help"):
        text = getattr(viewer, what)
        out.append(Shown(f"status bar {what}", text if isinstance(text, str) else str(text)))
    return [s for s in out if s.text.strip()]


def hover_all(viewer, sess, per_part: int = 6) -> list[Shown]:
    """What the status bar says over the compartments drawn now.

    In 3D, at each shown compartment's centroid; in 2D, inside its loops on
    the plane. Through napari's own mouse-move path (`viewer_harness.hover`).
    """
    from viewer_harness import hover

    out = []
    three_d = viewer.dims.ndisplay == 3
    for name, surface in sess.surfaces.items():
        contour = sess.contours.get(name)
        if three_d:
            shown = sorted(surface.selection)
            points = [surface.layer.data_to_world(surface.meshset.centroid(i))
                      for i in shown[:: max(1, len(shown) // per_part)][:per_part]]
        elif contour is not None and contour.layer.visible:
            loops = list(contour.paths)
            points = [contour.layer.data_to_world(np.asarray(loop, float).mean(axis=0))
                      for loop in loops[:: max(1, len(loops) // per_part)][:per_part]]
        else:
            points = []
        for point in points:
            said = hover(viewer, point)
            if said:
                out.append(Shown("hover", said))
    viewer.status = ""
    return out


def open_popups(viewer) -> None:
    """Open the popups of napari's buttons that take a right-click now: the
    camera's, and in 2D the axis order's. Each is collected with the Layers
    dock it opens from (`collect`), and closed after."""
    from chrome_harness import popups_offscreen, right_click

    row = viewer.window._qt_viewer.viewerButtons
    with popups_offscreen():
        for button in (row.ndisplayButton, row.rollDimsButton):
            right_click(button)


def napari_baseline(viewer) -> set[str]:
    """What a bare napari window shows with a layer of each kind lobemap
    adds: its own menus, layer settings, buttons, popups and sliders."""
    from chrome_harness import close_popups
    from napari.utils.colormaps import AVAILABLE_COLORMAPS
    from viewer_harness import pump

    data = np.zeros((4, 5, 6), np.uint8)
    viewer.add_image(data, multiscale=False)
    viewer.add_image([data, data[::2, ::2, ::2]], multiscale=True)
    viewer.add_labels(data)
    viewer.add_shapes(ndim=3)
    viewer.add_surface((np.eye(3), np.array([[0, 1, 2]]), np.arange(3.0)))
    pump()
    texts = {s.text for s in collect(viewer)}
    for ndisplay in (2, 3):
        viewer.dims.ndisplay = ndisplay
        pump()
        open_popups(viewer)
        texts |= {s.text for s in collect(viewer)}
        close_popups(viewer)
    # Never a colormap lobemap registered earlier in this process.
    return {t for t in texts if t in BUILTIN_COLORMAPS or t not in AVAILABLE_COLORMAPS}


def _builtin_colormaps() -> frozenset[str]:
    from napari.utils.colormaps import AVAILABLE_COLORMAPS

    return frozenset(AVAILABLE_COLORMAPS)


#: napari's own colormaps: read when this module is first imported, before
#: any scene of lobemap's has registered one.
BUILTIN_COLORMAPS = _builtin_colormaps()


#: The states each brain is read in: as opened, then with every tab built
#: and every row shown, in each mode, unturned and turned across the grid
#: and upside down.
STATES = ("3d_default", "2d_default", "3d_all", "2d_all", "2d_oblique", "3d_turned")
#: (spin, tilt, turn) of the turned states, entered in the View dock.
TURNED = (20.0, 30.0, -15.0)


def walk(viewer, spaces):
    """Yield (space, state, strings shown) for each brain, through the
    controls a user has: the Dataset menu, the tabs, 3D and Slice, the
    angle boxes and the flip, with napari's popups open. The viewer opened
    on `spaces[0]`."""
    from chrome_harness import close_popups
    from viewer_harness import pump, session, switch_to, switcher

    sw = switcher(viewer)
    for space in spaces:
        if session(viewer).space != space:
            switch_to(viewer, space)
            pump(300)
        sess = session(viewer)
        assert sess.space == space
        for state in STATES:
            if state == "3d_all":
                for name in list(sess.parts):
                    tab = sess.panel.tab(name)
                    if tab is not None:
                        tab.select(range(tab.surface.meshset.n_compartments))
                        tab.table.selectRow(0)
            if state == "2d_oblique":
                for angle, value in zip(("spin", "tilt", "turn"), TURNED, strict=True):
                    sw.rotation.box[angle].setValue(value)
                # Turned states are read upside down, which a switch undoes.
                sw.flip.setChecked(True)
            (sw.three_d if state.startswith("3d") else sw.slice_view).click()
            pump(300)
            shown = collect(viewer)
            if state.endswith(("all", "oblique", "turned")):
                shown += hover_all(viewer, sess)
            open_popups(viewer)
            shown += collect(viewer)
            close_popups(viewer)
            yield space, state, shown
        sw.rotation.reset.click()
        pump(300)
