"""Right-dock compartment panel: one tab per atlas, then one per neuropil set.

Visibility is per-compartment ACROSS atlases (design section 1), so each atlas
gets its own tab driving its own layer, and nothing assumes a single active
atlas. Each tab is a `panel_tab.AtlasTab`; what its rows say comes from
`rows`, so every tab of a kind reads the same.

A tab is named by its asset's `title` in `registry/assets.toml`, and its
tooltip is that asset's `about` line: the one place either is written.
"""

from __future__ import annotations

from qtpy.QtCore import QSize
from qtpy.QtWidgets import QLabel, QTabWidget, QVBoxLayout, QWidget

from ..core import reference
from .panel_tab import (
    CHECK_COLUMNS,
    CHECK_WIDTH,
    FILL_COL,
    GLOMERULUS_COLUMNS,
    INDEX_ROLE,
    LABEL_COL,
    NAME_COL,
    NEUROPIL_COLUMNS,
    RECEPTOR_COL,
    SIDE_COL,
    VISIBLE_COL,
    AtlasTab,
)
from .rows import natural_key

#: The width the panel asks for, which sets the right-hand column's. Every
#: tab's table fits it without scrolling sideways.
WIDTH = 440


def plain_reason(exc: BaseException) -> str:
    """Why a tab could not be opened, in words rather than a traceback.

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
    """The panel's built tabs by name; asking for one not built yet builds it."""

    def __init__(self, panel) -> None:
        super().__init__()
        self._panel = panel

    def __missing__(self, name):
        tab = self._panel.tab(name)
        if tab is None:
            raise KeyError(name)
        return tab


class CompartmentPanel(QTabWidget):
    """One tab per atlas, then one per neuropil set.

    `names` is every part of the scene in scene order; those without a
    surface in `surfaces` were left for later (`SceneSession.realize`) and
    get a tab that builds them when it is first opened, through `realize`.
    `tabs` holds the built ones, and indexing it builds one on demand.
    """

    def __init__(self, viewer, surfaces: dict, registry=None, contours=None,
                 space: str | None = None, names=None, realize=None) -> None:
        super().__init__()
        self.viewer = viewer
        self.registry = registry
        self.tabs: dict[str, AtlasTab] = _Tabs(self)
        #: Tabs not built yet: name -> the placeholder page standing in.
        self._pages: dict[str, QWidget] = {}
        self._realize = realize
        #: Why each tab that could not be built failed, for whoever debugs
        #: it; the tab itself says so in words (`plain_reason`).
        self.failures: dict[str, BaseException] = {}
        self._three_d: bool | None = None
        contours = contours or {}
        # Read once for the whole panel: every tab joins against the same
        # small tables.
        root = registry.root if registry else None
        self._annotation = reference.load(root) if root else {}
        self._lines = reference.lines(root) if root else {}
        self._neuropil_names = reference.neuropil_names(root) if root else {}
        # Atlases first, reference geometry last. `build_scene` adds the
        # neuropil and brain shells before the atlases so they sit UNDER
        # the glomeruli, but that is a stacking order and this is a reading
        # order: the tabs with glomeruli in them come first. Sorting on a
        # bool is stable, so each group keeps its scene order.
        def is_reference(name: str) -> bool:
            return registry is None or name not in registry.atlases

        for name in sorted(list(surfaces) if names is None else names,
                           key=is_reference):
            if name in surfaces:
                page = self._make_tab(name, surfaces[name], contours.get(name))
                dict.__setitem__(self.tabs, name, page)
            else:
                page = QWidget()
                self._pages[name] = page
            self.setTabToolTip(self.addTab(page, self.title(name)), self._about(name))
        self._open_default_tab(registry, space)
        self.currentChanged.connect(self._on_current)
        self._on_current(self.currentIndex())
        if viewer is not None:
            self.set_mode(viewer.dims.ndisplay == 3)

    def sizeHint(self) -> QSize:
        return QSize(WIDTH, super().sizeHint().height())

    def title(self, name: str) -> str:
        """The plain title of a part's tab, from its asset."""
        asset = self.registry.asset_of(name) if self.registry else None
        return asset.title if asset is not None and asset.title else name

    def _about(self, name: str) -> str:
        asset = self.registry.asset_of(name) if self.registry else None
        return asset.about if asset is not None else ""

    def index_of(self, name: str) -> int:
        """The tab index of a part, built or not; -1 if it has no tab."""
        page = dict.get(self.tabs, name) or self._pages.get(name)
        return -1 if page is None else self.indexOf(page)

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
        """The tab of `name`, built now if it was left for later.

        None if there is no such tab, or if building it failed; the failure
        is then written on the tab, which is where the user looks.
        """
        if name in self.tabs:
            return dict.__getitem__(self.tabs, name)
        page = self._pages.get(name)
        if page is None or self._realize is None:
            return None
        try:
            surface, contour = self._realize(name)
        except Exception as exc:                      # noqa: BLE001
            self.failures[name] = exc
            if page.layout() is None:
                layout = QVBoxLayout(page)
                label = QLabel(f"{self.title(name)} could not be opened: "
                               f"{plain_reason(exc)}")
                label.setWordWrap(True)
                layout.addWidget(label)
                layout.addStretch(1)
            return None
        tab = self._make_tab(name, surface, contour)
        del self._pages[name]
        index = self.indexOf(page)
        current = index == self.currentIndex()
        blocked = self.blockSignals(True)
        try:
            self.removeTab(index)
            self.insertTab(index, tab, self.title(name))
            self.setTabToolTip(index, self._about(name))
            if current:
                self.setCurrentIndex(index)
        finally:
            self.blockSignals(blocked)
        page.deleteLater()
        dict.__setitem__(self.tabs, name, tab)
        if self._three_d is not None:
            tab.set_mode(self._three_d)
        return tab

    def _on_current(self, index: int) -> None:
        """Opening a tab not built yet builds it."""
        page = self.widget(index)
        name = next((n for n, p in self._pages.items() if p is page), None)
        if name is not None:
            self.tab(name)

    def set_mode(self, three_d: bool) -> None:
        self._three_d = three_d
        for tab in self.tabs.values():
            tab.set_mode(three_d)

    def _open_default_tab(self, registry, space: str | None) -> None:
        """Open on an atlas, never on the reference geometry.

        Neuropil and brain shells are added to the scene first so they sit
        underneath the glomeruli, which also made one of them tab 0. That
        tab lists whole neuropils, so the panel opened on the one tab that
        says nothing about glomeruli.

        Which atlas is the space's own choice, `primary_atlas`, so the open
        tab matches the atlas `show_primary_atlas` leaves drawn. It matters
        only for JRCFIB2018F, the one space carrying several: it opens on
        the neuPrint parcellation the Schlegel pair are compared against.
        """
        atlases = [name for name, tab in self.tabs.items() if tab.is_atlas]
        if not atlases:
            return              # a space with reference geometry only
        target = atlases[0]
        if registry is not None:
            # Derivable from any atlas tab, so a caller that did not name
            # the space still gets the declared choice rather than
            # whichever atlas happens to be built first.
            space = space or registry.atlases[target].native_space
            primary = registry.primary_atlas(space)
            if primary is not None and primary.id in self.tabs:
                target = primary.id
        self.setCurrentWidget(self.tabs[target])

    def highlight(self, layer_name: str, index: int) -> None:
        tab = self.tabs.get(layer_name)
        if tab is None:
            return
        self.setCurrentWidget(tab)
        tab.highlight(index)


__all__ = [
    "CHECK_COLUMNS",
    "CHECK_WIDTH",
    "FILL_COL",
    "GLOMERULUS_COLUMNS",
    "INDEX_ROLE",
    "LABEL_COL",
    "NAME_COL",
    "NEUROPIL_COLUMNS",
    "RECEPTOR_COL",
    "SIDE_COL",
    "VISIBLE_COL",
    "WIDTH",
    "AtlasTab",
    "CompartmentPanel",
    "natural_key",
    "plain_reason",
]
