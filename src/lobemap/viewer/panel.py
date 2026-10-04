"""Right-dock compartment panel: a Glomeruli tab and a Neuropils tab.

Each tab names what it holds. A source menu at its top picks which of the
brain's atlases of that kind its table shows -- neuPrint or either Schlegel
definition in the hemibrain, Benton 2025 in FAFB -- with the source's
citation under it, in the same place and at the same size in every brain,
one source or several.

Visibility is per-compartment ACROSS atlases (design section 1), so each
source keeps a table of its own, driving its own layer: choosing one in the
menu changes which table is shown, never which atlases are drawn. Each table
is a `panel_tab.AtlasTab`; what its rows say comes from `rows`, so every
table of a kind reads the same.

A source is named by its asset's `origin` in `registry/assets.toml` when it
has one, else by its `title`: "FlyWire", "neuPrint", "Benton 2025". Its
citation is the asset's `about` line. Each is written there and nowhere else.
"""

from __future__ import annotations

from qtpy.QtCore import QSize, Qt
from qtpy.QtWidgets import (
    QComboBox,
    QFormLayout,
    QLabel,
    QStackedLayout,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..core import reference
from .chrome import tidy_tab_bar
from .panel_tab import (
    CHECK_COLUMNS,
    FILL_COL,
    GAP,
    GLOMERULUS_COLUMNS,
    GROUP_GAP,
    INDEX_ROLE,
    LABEL_COL,
    MARGIN,
    NAME_COL,
    NEUROPIL_COLUMNS,
    RECEPTOR_COL,
    SOURCE,
    VISIBLE_COL,
    AtlasTab,
    ColumnLabel,
    SteadyLabel,
)
from .rows import natural_key
from .wheel import guard_wheel

#: The width the panel asks for, which sets the right-hand column's. Every
#: tab's table fits it without scrolling sideways.
WIDTH = 440

#: The two tabs, by what they hold, in the order they are shown.
GLOMERULI, NEUROPILS = "Glomeruli", "Neuropils"


def plain_reason(exc: BaseException) -> str:
    """Why a source could not be opened, in words rather than a traceback.

    The exception itself names files and asset ids, which mean nothing to
    the reader; it stays on the exception.
    """
    if isinstance(exc, FileNotFoundError):
        return "its data is not on this computer (lobemap fetch gets it)"
    if isinstance(exc, OSError):
        return "its data could not be read"
    if isinstance(exc, MemoryError):
        return "there was not enough memory"
    return "it could not be built"


class _Tabs(dict):
    """The panel's built tables by name; asking for one not built yet builds it."""

    def __init__(self, panel) -> None:
        super().__init__()
        self._panel = panel

    def __missing__(self, name):
        tab = self._panel.tab(name)
        if tab is None:
            raise KeyError(name)
        return tab


class SourcePage(QWidget):
    """One tab: its source menu and the citation under it, over one table
    per source, of which the menu's choice is shown.

    A source not built yet has a blank page standing in until it is chosen
    with its tab open (`CompartmentPanel.tab`). The tables are stacked in a
    plain widget, which napari's style gives no padding: a stacked widget is
    a frame, and its pixel of padding put every table off the menu's edge.
    """

    def __init__(self, panel, names, citations) -> None:
        super().__init__()
        self._panel = panel
        #: The sources, by scene key, in the menu's order.
        self.names = list(names)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(MARGIN, MARGIN, MARGIN, MARGIN)
        layout.setSpacing(0)

        head = QFormLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setHorizontalSpacing(2 * GAP)
        head.setVerticalSpacing(GAP)
        # Left and full width, whatever the texts: macOS centres a form and
        # sizes its fields to their contents, so each brain and each choice
        # put the menu somewhere else.
        head.setFormAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        head.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        #: Which source's table the tab shows.
        self.menu = QComboBox()
        guard_wheel(self.menu)
        for i, name in enumerate(self.names):
            self.menu.addItem(panel.source_title(name), name)
            self.menu.setItemData(i, panel.about(name), Qt.ItemDataRole.ToolTipRole)
        #: The chosen source's citation, as tall as the longest of
        #: `citations` needs, so no choice and no brain moves the table.
        self.citation = SteadyLabel(lambda: citations)
        if panel.viewer is not None:
            # Smaller than the menu, as the source's metadata: the theme's
            # base size, which the tab titles have too. As a style, because
            # napari's style sheet puts back a font set in code.
            from napari.utils.theme import get_theme

            size = get_theme(panel.viewer.theme).font_size
            self.citation.setStyleSheet(f"font-size: {size};")
        head.addRow(ColumnLabel(SOURCE), self.menu)
        head.addRow(ColumnLabel(), self.citation)
        layout.addLayout(head)
        layout.addSpacing(GROUP_GAP)

        #: Holds the tables, one shown at a time by `stack`.
        self.body = QWidget()
        #: One page per source, in the menu's order.
        self.stack = QStackedLayout(self.body)
        for name in self.names:
            self.stack.addWidget(dict.get(panel.tabs, name) or QWidget())
        layout.addWidget(self.body, stretch=1)
        self.menu.currentIndexChanged.connect(self._chosen)
        self._chosen(self.menu.currentIndex())

    @property
    def chosen(self) -> str:
        """The scene key of the source the menu shows."""
        return self.names[self.menu.currentIndex()]

    def choose(self, name: str) -> None:
        """Show `name`'s table, as picking it in the menu does."""
        self.menu.setCurrentIndex(self.names.index(name))

    def _chosen(self, index: int) -> None:
        """Show the table of the source picked; build it if its tab is open,
        as opening a source's own tab built it."""
        self.stack.setCurrentIndex(index)
        self.citation.setText(self._panel.about(self.names[index]))
        if self._panel.currentWidget() is self:
            self._panel.tab(self.names[index])

    def put(self, name: str, page: QWidget) -> QWidget:
        """Put `page` where `name`'s page is, chosen if that one was; return
        the page it replaced."""
        index = self.names.index(name)
        old = self.stack.widget(index)
        self.stack.insertWidget(index, page)
        self.stack.removeWidget(old)
        self.stack.setCurrentIndex(self.menu.currentIndex())
        return old


class CompartmentPanel(QTabWidget):
    """A Glomeruli tab of the brain's atlases and a Neuropils tab of its
    neuropil sets, each choosing one source's table to show.

    `names` is every part of the scene in scene order; those without a
    surface in `surfaces` were left for later (`SceneSession.realize`) and
    are built when first chosen with their tab open, through `realize`.
    `tabs` holds the built tables, and indexing it builds one on demand.
    """

    def __init__(self, viewer, surfaces: dict, registry=None, contours=None,
                 space: str | None = None, names=None, realize=None) -> None:
        super().__init__()
        tidy_tab_bar(self.tabBar())
        self.viewer = viewer
        self.registry = registry
        self.tabs: dict[str, AtlasTab] = _Tabs(self)
        #: Each tab's page, by its title.
        self.pages: dict[str, SourcePage] = {}
        self._realize = realize
        #: Why each source that could not be built failed, for whoever
        #: debugs it; its page says so in words (`plain_reason`).
        self.failures: dict[str, BaseException] = {}
        self._three_d: bool | None = None
        contours = contours or {}
        # Read once for the whole panel: every table joins against the same
        # small tables.
        root = registry.root if registry else None
        self._annotation = reference.load(root) if root else {}
        self._lines = reference.lines(root) if root else {}
        self._neuropil_names = reference.neuropil_names(root) if root else {}

        kinds: dict[str, list[str]] = {GLOMERULI: [], NEUROPILS: []}
        for name in list(surfaces) if names is None else names:
            if name in surfaces:
                tab = self._make_tab(name, surfaces[name], contours.get(name))
                dict.__setitem__(self.tabs, name, tab)
            kinds[self.kind(name)].append(name)
        # Every citation a source menu can show, so the citation is as tall
        # in every brain and every tab.
        if registry is not None:
            citations = sorted({asset.about for asset in registry.assets.values()
                                if asset.kind == "meshset" and asset.about})
        else:
            citations = [self.about(name) for found in kinds.values() for name in found]
        for kind, found in kinds.items():
            if found:
                self.pages[kind] = SourcePage(self, found, citations)
                self.addTab(self.pages[kind], kind)
        self._open_default(registry, space)
        self.currentChanged.connect(self._on_current)
        self._on_current(self.currentIndex())
        if viewer is not None:
            self.set_mode(viewer.dims.ndisplay == 3)

    def sizeHint(self) -> QSize:
        return QSize(WIDTH, super().sizeHint().height())

    def kind(self, name: str) -> str:
        """Which tab a part's table is in: an atlas's is in Glomeruli."""
        atlases = self.registry.atlases if self.registry else {}
        return GLOMERULI if name in atlases else NEUROPILS

    def source_title(self, name: str) -> str:
        """The plain name of a part's source, from its asset."""
        asset = self.registry.asset_of(name) if self.registry else None
        if asset is None:
            return name
        return asset.origin or asset.title or name

    def about(self, name: str) -> str:
        """The citation of a part's source, from its asset."""
        asset = self.registry.asset_of(name) if self.registry else None
        return asset.about if asset is not None else ""

    def page_of(self, name: str) -> SourcePage | None:
        """The tab whose menu lists `name`, or None."""
        return next((p for p in self.pages.values() if name in p.names), None)

    def current(self) -> str | None:
        """The scene key of the source whose table is on show."""
        page = self.currentWidget()
        return page.chosen if isinstance(page, SourcePage) else None

    def open(self, name: str) -> AtlasTab | None:
        """Show `name`'s table: its tab open, chosen in the menu, and built.

        None if there is no such source or it could not be built.
        """
        page = self.page_of(name)
        if page is None:
            return None
        page.choose(name)
        self.setCurrentWidget(page)
        return self.tab(name)

    def _make_tab(self, name: str, surface, contour) -> AtlasTab:
        atlas = self.registry.atlases.get(name) if self.registry else None
        return AtlasTab(
            surface,
            compartments=atlas.compartments if atlas else None,
            contour=contour,
            annotation=self._annotation,
            is_atlas=atlas is not None,
            lines=self._lines,
            neuropil_names=self._neuropil_names,
        )

    def tab(self, name: str) -> AtlasTab | None:
        """The table of `name`, built now if it was left for later.

        None if there is no such table, or if building it failed; the
        failure is then written where the table would be, which is where
        the user looks.
        """
        if name in self.tabs:
            return dict.__getitem__(self.tabs, name)
        page = self.page_of(name)
        if page is None or self._realize is None:
            return None
        blank = page.stack.widget(page.names.index(name))
        try:
            surface, contour = self._realize(name)
        except Exception as exc:                      # noqa: BLE001
            self.failures[name] = exc
            if blank.layout() is None:
                layout = QVBoxLayout(blank)
                label = QLabel(f"{self.source_title(name)} could not be opened: "
                               f"{plain_reason(exc)}")
                label.setWordWrap(True)
                layout.addWidget(label)
                layout.addStretch(1)
            return None
        tab = self._make_tab(name, surface, contour)
        page.put(name, tab).deleteLater()
        dict.__setitem__(self.tabs, name, tab)
        if self._three_d is not None:
            tab.set_mode(self._three_d)
        return tab

    def _on_current(self, index: int) -> None:
        """Opening a tab builds the source its menu shows, if not built yet."""
        page = self.widget(index)
        if isinstance(page, SourcePage):
            self.tab(page.chosen)

    def set_mode(self, three_d: bool) -> None:
        self._three_d = three_d
        for tab in self.tabs.values():
            tab.set_mode(three_d)

    def _open_default(self, registry, space: str | None) -> None:
        """Open on the glomeruli, showing the brain's own atlas.

        Which atlas is the space's own choice, `primary_atlas`, so the table
        on show matches the atlas `show_primary_atlas` leaves drawn. It
        matters only for JRCFIB2018F, the one space carrying several: it
        opens on the neuPrint parcellation the Schlegel pair are compared
        against. A brain with no atlas opens on its neuropils.
        """
        page = self.pages.get(GLOMERULI) or next(iter(self.pages.values()), None)
        if page is None:
            return
        if registry is not None and page is self.pages.get(GLOMERULI):
            # Derivable from any atlas, so a caller that did not name the
            # space still gets the declared choice rather than whichever
            # atlas comes first.
            space = space or registry.atlases[page.names[0]].native_space
            primary = registry.primary_atlas(space)
            if primary is not None and primary.id in page.names:
                page.choose(primary.id)
        self.setCurrentWidget(page)

    def highlight(self, layer_name: str, index: int) -> None:
        """Show the row of a compartment clicked in the canvas: its tab
        opened and its source chosen, if another was, then the row selected."""
        tab = dict.get(self.tabs, layer_name)
        if tab is None:
            return
        self.open(layer_name)
        tab.highlight(index)


__all__ = [
    "CHECK_COLUMNS",
    "FILL_COL",
    "GLOMERULI",
    "GLOMERULUS_COLUMNS",
    "INDEX_ROLE",
    "LABEL_COL",
    "NAME_COL",
    "NEUROPILS",
    "NEUROPIL_COLUMNS",
    "RECEPTOR_COL",
    "SOURCE",
    "VISIBLE_COL",
    "WIDTH",
    "AtlasTab",
    "CompartmentPanel",
    "SourcePage",
    "natural_key",
    "plain_reason",
]
