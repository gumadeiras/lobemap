"""A space picker that swaps the scene without restarting the viewer.

Rebuilding in place rather than relaunching is the whole point: the process,
the Qt window and the GPU context survive, so a switch costs only the data.
Tearing the window down and putting a new one up would also lose the
maximized geometry and put a fresh window wherever the window manager felt
like, which for a viewer whose default view is carefully fitted is a
regression, not a neutral implementation detail.

The next scene is built beside the open one, which is torn down only once
that build has succeeded, so a failed switch leaves the user's scene as it
was. `SceneSession.teardown` does the unloading; this is only the control.
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
from .view import capture_view, restore_view

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
            "the anatomical one still names the side you are looking at. "
            "Switching space clears it."
        )
        self.mirror.toggled.connect(self._on_mirror)

        #: The slice axis, by the anatomical name of each choice.
        self.slice = QComboBox()
        self.slice.setToolTip(SLICE_TIP)
        self.slice.currentIndexChanged.connect(self._on_slice)
        self._fill_slices()
        # The switcher outlives every scene, so it is connected once.
        viewer.dims.events.ndisplay.connect(self._on_mode)
        viewer.dims.events.order.connect(self._on_order)
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

    def _on_order(self, event=None) -> None:
        """Keep napari's own roll-dims button in step with the menu.

        In 2D a roll picks another slice axis behind the menu's back: the
        menu kept its old name and the contours showed an empty plane. It is
        taken as a choice made in the menu. In 3D the order must stay the
        identity (see `app.install_display_mode`), so a roll there is undone.
        """
        if self._busy:
            return
        order = tuple(self.viewer.dims.order)
        if self.viewer.dims.ndisplay == 3:
            identity = tuple(range(len(order)))
            if order != identity:
                self.viewer.dims.order = identity
            return
        index = self.slice.findData(order[0])
        if index >= 0 and order[0] != self.session.slice_axis:
            self.slice.setCurrentIndex(index)

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
        try:
            self._switch(want)
        finally:
            self._busy = False

    def _switch(self, want: str) -> None:
        """Build `want` beside the open scene, and only then drop the open one.

        A failed build is undone and the open scene was never touched, so the
        user gets back exactly what they had: every tab's checked rows,
        labels, fills, filter and driver line, the open tab, the mirror.
        What the build did move belongs to the viewer -- the slice axis and
        plane, the camera, the selected layer, the title, the axis triads
        and the home button -- and is put back from what was captured before
        it started. Rebuilding the previous space instead, as this used to,
        gave its defaults back rather than the user's scene.
        """
        old = self.session
        anatomy = self._anatomy.get(old.slice_axis)
        before = capture_view(self.viewer)
        self.status.setText(f"loading {want}...")
        new = None
        try:
            new = self._load(want)
            self.session = new
            self._fill_slices(keep=anatomy)
        except Exception as exc:                      # noqa: BLE001
            self.session = old
            steps = [self._fill_slices, lambda: restore_view(self.viewer, before),
                     old.reassert]
            if new is not None:
                steps.insert(0, new.teardown)
            # Each step on its own: this runs inside a Qt slot, where an
            # exception aborts the process, and every step that can still
            # run gives back more of the user's scene.
            for step in steps:
                with contextlib.suppress(Exception):
                    step()
            self.status.setText(f"{want} failed: {exc}")
            index = self.combo.findData(old.space)
            if index >= 0:
                self.combo.setCurrentIndex(index)
            return
        old.teardown()
        # The new space comes up unmirrored and the control follows it. The
        # mirror is how one space is being looked at, not a preference:
        # carried across, it would hand back a reflected scene nobody
        # reflected, and the reflection is the one thing here that can make
        # left read as right. `_busy` keeps `_on_mirror` out of it. A failed
        # switch keeps the open scene, mirror and all, and never gets here.
        self.mirror.setChecked(False)
        try:
            new.settle_view()
            self.settle()
            self.status.setText("")
        except Exception as exc:                      # noqa: BLE001
            # The new scene is complete and the old one gone; only framing
            # it failed, which is worth saying but not undoing.
            self.status.setText(f"{want}: {exc}")


__all__ = ["SpaceSwitcher"]
