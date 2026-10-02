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


class SpaceSwitcher(QWidget):
    """Choose the coordinate space; rebuilds the scene on change.

    Only spaces that actually have something to show are listed. A space with
    no ingested assets raises from `build_scene`, and offering a choice that
    cannot be honoured is worse than not offering it.
    """

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

        self.status = QLabel("")
        self.status.setWordWrap(True)

        row = QHBoxLayout()
        row.addWidget(QLabel("Space:"))
        row.addWidget(self.combo, 1)
        row.addWidget(self.mirror)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 4, 6, 4)
        outer.addLayout(row)
        outer.addWidget(self.status)
        # No trailing stretch: it made the widget claim any height it was
        # given, which is the opposite of what is wanted here.

    @staticmethod
    def loadable_spaces(registry) -> list[str]:
        """Spaces with at least one ingested atlas or reference meshset."""
        out = []
        for space_id in registry.spaces:
            atlases = list(registry.atlases_in_space(space_id))
            has_atlas = False
            for atlas in atlases:
                try:
                    has_atlas = registry.assets[atlas.asset].path.exists()
                except KeyError:
                    has_atlas = False
                if has_atlas:
                    break
            if not has_atlas:
                has_atlas = any(
                    asset.role in ("neuropil", "brain") and asset.path.exists()
                    for asset in registry.assets_in_space(space_id)
                )
            if has_atlas:
                out.append(space_id)
        return out

    def settle(self) -> None:
        """Sit below the compartment panel, however it was just re-added.

        Loading a scene creates a NEW compartment panel and docks it, and Qt
        puts a newly added dock above an existing one in the same area -- so
        after one switch this control had jumped from the bottom of the right
        column to the top of it, and stayed there. Re-splitting pins the
        order rather than relying on insertion order.
        """
        panel = getattr(self.session, "dock", None)
        if self.dock is None or panel is None:
            return
        window = getattr(self.viewer.window, "_qt_window", None)
        if window is None:
            return
        with contextlib.suppress(Exception):
            from qtpy.QtCore import Qt

            window.splitDockWidget(panel, self.dock, Qt.Vertical)
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
            window.resizeDocks([panel, self.dock], [10_000, wanted],
                               Qt.Vertical)

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
        try:
            self.status.setText(f"loading {want}...")
            self.session.teardown()
            self.session = self._load(want)
            # A new space comes up unmirrored and the control follows it.
            # The mirror is a property of how one space is being looked
            # at, not a preference: carrying it across would hand back a
            # reflected scene without anything having been clicked, and
            # the reflection is the one thing here that can make left
            # read as right. Safe during the switch because `_busy` makes
            # `_on_mirror` a no-op, and the new scene is already plain.
            self.mirror.setChecked(False)
            self.settle()
            self.status.setText("")
        except Exception as exc:                      # noqa: BLE001
            # A failed switch must not leave an empty viewer, so fall back to
            # what was loaded before and say why.
            self.status.setText(f"{want} failed: {exc}")
            with contextlib.suppress(Exception):
                self.session = self._load(previous)
                self.mirror.setChecked(False)
            index = self.combo.findData(self.session.space)
            if index >= 0:
                self.combo.setCurrentIndex(index)
        finally:
            self._busy = False


__all__ = ["SpaceSwitcher"]
