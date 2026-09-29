"""A space picker that swaps the scene without restarting the viewer.

Rebuilding in place rather than relaunching is the whole point: the process,
the Qt window and the GPU context survive, so a switch costs only the data.
Tearing the window down and putting a new one up would also lose the
maximized geometry and put a fresh window wherever the window manager felt
like, which for a viewer whose default view is carefully fitted is a
regression, not a neutral implementation detail.

`SceneSession.teardown` does the unloading; this is only the control.
"""

from __future__ import annotations

import contextlib

from qtpy.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .request import loadable_spaces
from .slicing import slice_axes

#: What the slice-axis menu is for, and why its angles are shown.
SLICE_TIP = (
    "The array axis 2D steps along, named by the anatomical axis nearest it. "
    "A slice is cut along the voxel grid, and the angle is how far that grid "
    "is turned from the anatomy -- which is also why no anatomical arrows are "
    "drawn over a 2D slice. 2D only."
)


class SpaceSwitcher(QWidget):
    """Choose the coordinate space; rebuilds the scene on change.

    Only spaces that actually have something to show are listed. A space with
    no ingested assets raises from `build_scene`, and offering a choice that
    cannot be honoured is worse than not offering it.

    Also holds the two controls that belong to the scene rather than to one
    atlas: the mirror, and the axis a 2D slice steps along.
    """

    loadable_spaces = staticmethod(loadable_spaces)

    def __init__(self, viewer, registry, session, load, parent=None) -> None:
        super().__init__(parent)
        self.viewer = viewer
        self.registry = registry
        self.session = session
        self._load = load
        self._busy = False
        #: This widget's own QDockWidget, set by whoever docks it. Needed to
        #: re-assert the vertical order after a reload; see `settle`.
        self.dock = None

        self.combo = QComboBox()
        for space_id in self.loadable_spaces(registry):
            space = registry.spaces[space_id]
            self.combo.addItem(space.title or space_id, space_id)
        index = self.combo.findData(session.space)
        if index >= 0:
            self.combo.setCurrentIndex(index)
        self.combo.currentIndexChanged.connect(self._on_change)

        self.mirror = QCheckBox("Mirror")
        self.mirror.setToolTip(
            "Show this space reflected left-right, for display only. The "
            "data is untouched, and both axis triads follow the mirror, so "
            "the anatomical one still names the side you are looking at."
        )
        self.mirror.toggled.connect(self._on_mirror)

        #: The slice axis, by the anatomical name of each choice.
        self.slice = QComboBox()
        self.slice.setToolTip(SLICE_TIP)
        self.slice.currentIndexChanged.connect(self._on_slice)
        self._fill_slices()
        # The switcher outlives every scene, so it is connected once.
        viewer.dims.events.ndisplay.connect(self._on_mode)
        self._on_mode()

        self.status = QLabel("")
        self.status.setWordWrap(True)

        row = QHBoxLayout()
        row.addWidget(QLabel("Space:"))
        row.addWidget(self.combo, 1)
        row.addWidget(self.mirror)
        slicing = QHBoxLayout()
        slicing.addWidget(QLabel("Slice along:"))
        slicing.addWidget(self.slice, 1)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 4, 6, 4)
        outer.addLayout(row)
        outer.addLayout(slicing)
        outer.addWidget(self.status)
        # No trailing stretch: it made the widget claim any height it was
        # given, which is the opposite of what is wanted here.

    def settle(self) -> None:
        """Sit above the compartment panel, however it was just re-added.

        Which space is open is read before anything about it, so the picker
        heads the right column. Loading a scene creates a NEW compartment
        panel and docks it, and Qt places a newly added dock wherever its
        insertion lands, so the order is pinned by re-splitting rather than
        left to insertion order.
        """
        panel = getattr(self.session, "dock", None)
        if self.dock is None or panel is None:
            return
        window = getattr(self.viewer.window, "_qt_window", None)
        if window is None:
            return
        with contextlib.suppress(Exception):
            from qtpy.QtCore import Qt

            window.splitDockWidget(self.dock, panel, Qt.Vertical)
            # And give it as little of the column as it will take. This is a
            # one-line control; the compartment table beside it is the thing
            # worth the height. Qt distributes by RATIO, not pixels, so the
            # numbers only have to be lopsided -- and it will still respect
            # the widget's minimum, which is why `collapse` shrinks that too.
            self.collapse()

    def collapse(self) -> None:
        """Shrink to the height this widget actually needs."""
        window = getattr(self.viewer.window, "_qt_window", None)
        panel = getattr(self.session, "dock", None)
        if window is None or panel is None or self.dock is None:
            return
        with contextlib.suppress(Exception):
            from qtpy.QtCore import Qt

            self.dock.setSizePolicy(self.dock.sizePolicy().horizontalPolicy(),
                                    QSizePolicy.Policy.Minimum)
            wanted = max(self.dock.sizeHint().height(),
                         self.dock.minimumSizeHint().height())
            window.resizeDocks([self.dock, panel], [wanted, 10_000],
                               Qt.Vertical)

    def _fill_slices(self, keep: str | None = None) -> None:
        """List the open space's slice axes, keeping the anatomy chosen.

        The same anatomical axis is a different array axis in another space
        -- anterior-posterior is z in FAFB and y in the hemibrain -- so a
        switch keeps the name the user picked and finds its axis anew.
        """
        space = self.registry.spaces.get(self.session.space)
        choices = slice_axes(space)
        self.slice.blockSignals(True)
        try:
            self.slice.clear()
            for choice in choices:
                self.slice.addItem(choice.label, choice.axis)
            wanted = next((c.axis for c in choices if keep and c.anatomy == keep),
                          self.session.slice_axis)
            self.slice.setCurrentIndex(max(0, self.slice.findData(wanted)))
        finally:
            self.slice.blockSignals(False)
        self._anatomy = {c.axis: c.anatomy for c in choices}
        self.session.slice_axis = int(self.slice.currentData())

    def _on_slice(self, _index: int) -> None:
        axis = self.slice.currentData()
        if self._busy or axis is None:
            return
        with contextlib.suppress(Exception):
            self.session.set_slice_axis(int(axis))

    def _on_mode(self, event=None) -> None:
        self.slice.setEnabled(self.viewer.dims.ndisplay == 2)

    def _on_mirror(self, on: bool) -> None:
        """Reflect the loaded scene, or put it back."""
        if self._busy:
            return
        with contextlib.suppress(Exception):
            self.session.set_mirror(on)

    def _on_change(self, _index: int) -> None:
        want = self.combo.currentData()
        if self._busy or want is None or want == self.session.space:
            return
        # Reentrancy guard: restoring the combo on failure re-emits the
        # signal, which would try to load the failed space a second time.
        self._busy = True
        previous = self.session.space
        anatomy = self._anatomy.get(self.session.slice_axis)
        try:
            self.status.setText(f"loading {want}...")
            self.session.teardown()
            self.session = self._load(want)
            # A scene is built unmirrored, so the control has to re-assert
            # itself onto the new one rather than the state being implicit.
            if self.mirror.isChecked():
                self.session.set_mirror(True)
            self._fill_slices(keep=anatomy)
            self.session.set_slice_axis(self.session.slice_axis)
            self.settle()
            self.status.setText("")
        except Exception as exc:                      # noqa: BLE001
            # A failed switch must not leave an empty viewer, so fall back to
            # what was loaded before and say why.
            self.status.setText(f"{want} failed: {exc}")
            with contextlib.suppress(Exception):
                self.session = self._load(previous)
                if self.mirror.isChecked():
                    self.session.set_mirror(True)
                self._fill_slices(keep=anatomy)
                self.session.set_slice_axis(self.session.slice_axis)
                self.settle()
            index = self.combo.findData(self.session.space)
            if index >= 0:
                self.combo.setCurrentIndex(index)
        finally:
            self._busy = False


__all__ = ["SpaceSwitcher"]
