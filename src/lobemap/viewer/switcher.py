"""The View dock: which brain is open, and how it is shown.

Brain, 3D or Slice, Fit to window, the zoom and the perspective, the sections a
slice steps through and their alignment, the mirror, the flip and the rotation:
the controls that belong to the scene rather than to one atlas, whose controls
are the compartment panel's. Every control is in view in both modes; one that
applies to one mode stays visible in the other, disabled, and its tooltip says
when it works. A box or menu changes under the mouse wheel only once it has
focus (`wheel`), so a scroll over the dock changes nothing. The
mirror and the flip stand alone, with no row label to repeat their words, and
are worded apart: the mirror reflects the brain, and the flip turns the picture
upside down.

napari's own buttons do some of the same (`buttons`). Each control here follows
the viewer's state rather than its own clicks -- the display mode, the axis
order, the camera -- so it stays in step whichever of the two is used.

Picking another brain rebuilds the scene in place rather than relaunching:
the process, the Qt window and the GPU context survive, so a switch costs
only the data. Tearing the window down and putting a new one up would also
lose the maximized geometry and put a fresh window wherever the window
manager felt like, which for a viewer whose default view is carefully
fitted is a regression, not a neutral implementation detail.

The next scene is built beside the open one, which is torn down only once
that build has succeeded, so a failed switch leaves the user's scene as it
was. `SceneSession.teardown` does the unloading; this is only the control.
"""

from __future__ import annotations

import contextlib
import re
import sys
import traceback

from qtpy.QtCore import Qt
from qtpy.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .buttons import take_action
from .camera_rows import PERSPECTIVE, ZOOM, CameraRows
from .chrome import CONTROL_HEIGHT, GRID
from .request import MissingAssets, loadable_spaces
from .rotation_rows import RotationRows
from .slicing import AXIS_LETTERS, order_for, slice_axes
from .view import capture_view, restore_view, upside_down
from .wheel import guard_wheel

#: The plane a section lies in, and the axis the slider steps along across
#: it, by that anatomical axis.
PLANES = {"Anterior-Posterior": ("Frontal", "anterior–posterior"),
          "Dorsal-Ventral": ("Horizontal", "dorsal–ventral"),
          "Left-Right": ("Sagittal", "medial–lateral")}

SECTIONS_TIP = (
    "Which sections the slider steps through, and the axis it steps along. "
    "Unless aligned below, the sections follow the image's own grid, at the "
    "angle shown from that axis. Slice view only."
)
ALIGN = "Align to the anatomical axes"
ALIGN_TIP = (
    "Cut the sections square to the brain's anterior–posterior, dorsal–ventral "
    "and medial–lateral axes, not along the image's grid. Slice view only."
)
MIRROR = "Mirror the brain left to right"
MIRROR_TIP = (
    "Show the brain as its mirror image, to compare a left lobe with a right "
    "one. Display only; the data do not change. The corner arrows follow. "
    "Opening another brain turns it off."
)
FLIP = "Flip the picture upside down"
FLIP_TIP = (
    "Show the picture upside down. Display only; the data do not change. With "
    "the mirror, a front view turns 180°. Opening another brain turns it off."
)
THREE_D_TIP = "Show the brain in 3D. Drag to turn it."
SLICE_TIP = "Show one section at a time. The slider under the image steps through them."
HOME = "Fit to window"
HOME_TIP = (
    "Fit the brain to the window. In 3D, also turn back to the front view, "
    "dorsal side up, with your rotation applied."
)
#: What the corner arrows mean, in both views. Each letter is bound to its
#: word, so a line never breaks between them.
ARROWS = "Arrows: " + ", ".join(
    f"{letter}\N{NO-BREAK SPACE}{word}" for letter, word in (
        ("A", "anterior"), ("P", "posterior"), ("D", "dorsal"), ("V", "ventral"),
        ("L", "left"), ("R", "right"))
) + ". In 3D, x, y and z are the image's own axes."

#: Said when a swap of the two shown axes is undone (`_on_order`).
SWAPPED = (
    "The two axes on screen keep their order: swapping them would show the "
    "brain mirrored, with no control to say so. To mirror the brain, use "
    "Mirror the brain left to right; to slice along another axis, use Sections."
)

OPENING = "Opening {title}…"
FAILED = "Could not open {title}: {reason}. Your view is unchanged."
UNFITTED = "Opened {title}, but could not fit it to the window."
UNTURNED = "Opened {title}, but could not turn it to the angles shown."


def section_label(choice, aligned: bool = False) -> str:
    """'Frontal (17.5° off anterior–posterior)': the plane, and the angle
    between the slider's steps and the anatomical axis they step along.

    Aligned, the steps are along that axis: 'Frontal (anterior–posterior)'.
    """
    if choice.anatomy is None:
        return f"Image axis {AXIS_LETTERS[choice.axis]}"
    plane, axis = PLANES[choice.anatomy]
    if aligned:
        return f"{plane} ({axis})"
    return f"{plane} ({choice.degrees:.1f}° off {axis})"


#: The abbreviations in the brains' titles, and what each stands for.
SPELLED = {
    "EM": "electron microscopy",
    "CNS": "central nervous system",
    "FAFB": "full adult fly brain",
}


def brain_tip(space) -> str:
    """The brain's title with its abbreviations spelled out, and the template
    it is shown in.

    'Male CNS (EM)' gives 'Male CNS (central nervous system): electron
    microscopy. Shown in the JRCFIB2022M template.' A space with no bridging
    template is its own template, named as the brain is: 'the Grabe 2015
    template'.
    """
    title = space.title or space.id
    name, _, details = title.partition(" (")
    details = details.rstrip(")")
    spelled = [SPELLED[w] for w in re.findall(r"\b[A-Z]{2,}\b", name) if w in SPELLED]
    lead = f"{name} ({', '.join(spelled)})" if spelled else name
    for short, long in SPELLED.items():
        details = re.sub(rf"\b{short}\b", long, details)
    lead = f"{lead}: {details}" if details else lead
    return f"{lead}. Shown in the {space.flybrains_template or name} template."


def plain_reason(exc: BaseException) -> str:
    """Why a brain did not open, in words; the details go to the terminal."""
    if isinstance(exc, (MissingAssets, FileNotFoundError)):
        return "its data are not downloaded; run lobemap fetch"
    if isinstance(exc, MemoryError):
        return "there is not enough memory"
    if isinstance(exc, OSError):
        return "a data file could not be read; the terminal has the details"
    return "an unexpected error; the terminal has the details"


class SpaceSwitcher(QWidget):
    """The View dock: choose the brain, and how it is shown.

    Only brains that actually have something to show are listed. A space
    with no ingested assets raises from `build_scene`, and offering a choice
    that cannot be honoured is worse than not offering it.
    """

    loadable_spaces = staticmethod(loadable_spaces)

    def __init__(self, viewer, registry, session, load, parent=None) -> None:
        super().__init__(parent)
        self.viewer = viewer
        self.registry = registry
        self.session = session
        self._load = load
        self._busy = False

        self.combo = QComboBox()
        for space_id in self.loadable_spaces(registry):
            space = registry.spaces[space_id]
            self.combo.addItem(space.title or space_id, space_id)
            self.combo.setItemData(self.combo.count() - 1, brain_tip(space),
                                   Qt.ItemDataRole.ToolTipRole)
        index = self.combo.findData(session.space)
        if index >= 0:
            self.combo.setCurrentIndex(index)
        # As wide as the longest title, which the column then makes room
        # for: cut short, "Grabe 2015 (live brain, light micro" was shown.
        self.combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self._on_brain_shown()
        self.combo.currentIndexChanged.connect(self._on_change)

        self.three_d = self._mode_button("3D", THREE_D_TIP, 3)
        self.slice_view = self._mode_button("Slice", SLICE_TIP, 2)
        group = QButtonGroup(self)
        group.addButton(self.three_d)
        group.addButton(self.slice_view)
        self.home = QPushButton(HOME)
        self.home.setToolTip(HOME_TIP)
        self.home.clicked.connect(lambda: self.session.home())

        #: The sections the slider steps through, by array axis.
        self.slice = QComboBox()
        self.slice.setToolTip(SECTIONS_TIP)
        self._size_sections()
        self.slice.currentIndexChanged.connect(self._on_slice)
        self.align = QCheckBox(ALIGN)
        self.align.setToolTip(ALIGN_TIP)
        self.align.toggled.connect(self._on_align)
        self._fill_slices()

        self.mirror = QCheckBox(MIRROR)
        self.mirror.setToolTip(MIRROR_TIP)
        self.mirror.toggled.connect(self._on_mirror)
        #: The picture upside down, after the turn and the mirror. The
        #: camera's, which napari's camera popup can turn over too.
        self.flip = QCheckBox(FLIP)
        self.flip.setToolTip(FLIP_TIP)
        self.flip.setChecked(upside_down(viewer))
        self.flip.toggled.connect(self._on_flip)
        #: How the picture is shown: the anatomical mirror, and the screen
        #: flip under it.
        self.picture = QVBoxLayout()
        self.picture.addWidget(self.mirror)
        self.picture.addWidget(self.flip)

        #: The camera's zoom and perspective; see `camera_rows`.
        self.camera = CameraRows(viewer)

        #: The angles about the screen's axes; they carry across a switch,
        #: as the alignment does.
        self.rotation = RotationRows(self)
        self.rotation.changed.connect(self._on_rotation)

        self.legend = QLabel(ARROWS)
        self.legend.setWordWrap(True)
        self.status = QLabel("")
        self.status.setWordWrap(True)

        show = QHBoxLayout()
        show.addWidget(self.three_d)
        show.addWidget(self.slice_view)
        # Fit to window changes no mode: set apart from the two that do.
        show.addSpacing(GRID)
        show.addWidget(self.home)
        sections = QVBoxLayout()
        sections.addWidget(self.slice)
        sections.addWidget(self.align)
        arrows = QVBoxLayout()
        arrows.addWidget(self.legend)
        for row in (show, sections, self.picture, arrows):
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(GRID)

        # One grid (`chrome.GRID`): labels in one column and controls in
        # the next, a grid unit apart; rows a grid unit apart within a
        # group and two between groups; every control as wide as its
        # content, no wider, and as tall as the rest. Only the headings and
        # the text that wraps run across the dock.
        form = QFormLayout(self)
        form.setContentsMargins(GRID, GRID, GRID, GRID)
        form.setHorizontalSpacing(GRID)
        form.setVerticalSpacing(GRID)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint)
        form.addRow("Brain", self.combo)
        self._gap(form)
        form.addRow("Show", show)
        form.addRow(ZOOM, self.camera.zoom)
        form.addRow(PERSPECTIVE, self.camera.perspective)
        self._gap(form)
        form.addRow("Sections", sections)
        self._gap(form)
        form.addRow(None, self.picture)
        self._gap(form)
        self.rotation.add_to(form)
        self._gap(form)
        form.addRow(arrows)
        form.addRow(self.status)
        for control in (self.combo, self.three_d, self.slice_view, self.home, self.slice,
                        self.align, self.mirror, self.flip, self.camera.zoom,
                        self.camera.perspective, self.rotation.reset,
                        *self.rotation.box.values()):
            control.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            # One height: the boxes and checkboxes were 20 px, their text a
            # few pixels from their edges, and the Sections menu 26.
            control.setFixedHeight(CONTROL_HEIGHT)
        boxes = (self.camera.zoom, self.camera.perspective, *self.rotation.box.values())
        for row in range(form.rowCount()):
            label = form.itemAt(row, QFormLayout.ItemRole.LabelRole)
            if label is not None and label.widget() is not None:
                # As tall as a control, at the top of its row, so its text
                # sits on its control's baseline: "Sections", beside a menu
                # and a checkbox, sat 3 px below its menu's.
                label.widget().setFixedHeight(CONTROL_HEIGHT)
        guard_wheel(self.combo, self.slice, *boxes)
        # napari's theme pads a push button by half a grid unit all round,
        # which left its text touching the sides: a grid unit either side
        # instead. It pads a box's text by 1 px above and below, and holds
        # its height to its own: half a grid unit there too, as on a button.
        # And it draws a box's text a size smaller than the dock's other
        # text, a pixel off its label's baseline: one size throughout.
        pad = GRID // 2
        self.setStyleSheet(
            f"QPushButton {{ padding: {pad}px {GRID}px; }}"
            f"QAbstractSpinBox {{ padding: {pad}px 10px; "
            f"min-height: {CONTROL_HEIGHT - 2 * pad}px; "
            f"font-size: {self.font().pointSizeF():g}pt; }}")

        # The dock outlives every scene, so it is connected once.
        take_action(viewer, "napari:roll_axes", self.next_sections)
        viewer.dims.events.ndisplay.connect(self._on_mode)
        viewer.dims.events.order.connect(self._on_order)
        viewer.scene.camera.events.orientation.connect(self._on_orientation)
        self._on_mode()

    @staticmethod
    def _gap(form: QFormLayout) -> None:
        """Set two groups of rows apart: an empty row, which adds one more
        grid unit of the form's spacing between them."""
        gap = QWidget()
        gap.setFixedHeight(0)
        form.addRow(gap)

    def _mode_button(self, text: str, tip: str, ndisplay: int) -> QPushButton:
        button = QPushButton(text)
        button.setCheckable(True)
        button.setToolTip(tip)
        button.clicked.connect(lambda: setattr(self.viewer.dims, "ndisplay", ndisplay))
        return button

    def _title(self, space_id: str) -> str:
        space = self.registry.spaces.get(space_id)
        return (space.title if space is not None else "") or space_id

    def _on_brain_shown(self) -> None:
        self.combo.setToolTip(self.combo.currentData(Qt.ItemDataRole.ToolTipRole) or "")

    def _fill_slices(self, keep: str | None = None) -> None:
        """List the open brain's sections, keeping the anatomy chosen.

        The same anatomical axis is a different array axis in another space
        -- anterior-posterior is z in FAFB and y in the hemibrain -- so a
        switch keeps the plane the user picked and finds its axis anew.
        """
        space = self.registry.spaces.get(self.session.space)
        choices = slice_axes(space)
        self.slice.blockSignals(True)
        try:
            self.slice.clear()
            for choice in choices:
                self.slice.addItem(section_label(choice, self.align.isChecked()),
                                   choice.axis)
            wanted = next((c.axis for c in choices if keep and c.anatomy == keep),
                          self.session.slice_axis)
            self.slice.setCurrentIndex(max(0, self.slice.findData(wanted)))
        finally:
            self.slice.blockSignals(False)
        self._anatomy = {c.axis: c.anatomy for c in choices}
        self._choices = choices
        self.session.slice_axis = int(self.slice.currentData())

    def _size_sections(self) -> None:
        """Size the Sections menu once, for the longest choice it can hold.

        Every choice of every brain listed, aligned or not, so no choice is
        ever cut short and the menu never changes width. Sized to the names
        it held at each moment, it went from 260 to 205 px and back to 258
        when the alignment was turned on and off in FAFB14, and lost the
        closing parenthesis.
        """
        names = {section_label(choice, aligned)
                 for space_id in self.loadable_spaces(self.registry)
                 for choice in slice_axes(self.registry.spaces[space_id])
                 for aligned in (False, True)}
        self.slice.addItems(sorted(names))
        self.slice.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.slice.setFixedWidth(self.slice.sizeHint().width())
        self.slice.clear()

    def next_sections(self, viewer=None) -> None:
        """napari's roll, by its button or its key: the next choice of the
        Sections menu, in the menu's order, after the last the first.

        napari rolls the axis order instead, and its next slice axis was not
        the menu's next: the hemibrain went Horizontal, Sagittal, Frontal,
        Sagittal, and FAFB14 only between Sagittal and Horizontal. In 3D, as
        Sections is, it is off.
        """
        count = self.slice.count()
        if self.viewer.dims.ndisplay != 2 or count < 2:
            return
        self.slice.setCurrentIndex((self.slice.currentIndex() + 1) % count)

    def _on_slice(self, _index: int) -> None:
        axis = self.slice.currentData()
        if self._busy or axis is None:
            return
        with contextlib.suppress(Exception):
            self.session.set_slice_axis(int(axis))

    def _on_align(self, on: bool) -> None:
        """Cut along the anatomy or the grid; the menu says which."""
        for i, choice in enumerate(self._choices):
            self.slice.setItemText(i, section_label(choice, on))
        if self._busy:
            return
        try:
            self.session.set_aligned(on)
        except Exception as exc:                      # noqa: BLE001
            _report("could not align the sections", exc)

    def _on_rotation(self, spin: float, tilt: float, turn: float) -> None:
        if self._busy:
            return
        try:
            self.session.set_rotation(spin, tilt, turn)
        except Exception as exc:                      # noqa: BLE001
            _report("could not turn the view", exc)

    def _on_mode(self, event=None) -> None:
        three_d = self.viewer.dims.ndisplay == 3
        self.three_d.setChecked(three_d)
        self.slice_view.setChecked(not three_d)
        self.slice.setEnabled(not three_d)
        self.align.setEnabled(not three_d)

    def _on_order(self, event=None) -> None:
        """Keep napari's roll button, its key and its axis-order popup in
        step with the Sections menu.

        In 2D a roll picks another slice axis behind the menu's back: the
        menu kept its old name and the contours showed an empty plane. It is
        taken as a choice made in the menu, whose sections then show the
        axes in its own order (`slicing.order_for`). An order that keeps the
        slice axis but swaps the two axes on screen -- napari's transpose, or
        a drag in its popup -- shows the brain mirrored, with no control to
        say so: it is undone, and the user told why. In 3D the order must
        stay the identity (see `app.install_display_mode`), so a roll there
        is undone.
        """
        if self._busy:
            return
        order = tuple(self.viewer.dims.order)
        if self.viewer.dims.ndisplay == 3:
            identity = tuple(range(len(order)))
            if order != identity:
                self.viewer.dims.order = identity
            return
        if order[0] == self.session.slice_axis:
            want = order_for(order[0], len(order))
            if order != want:
                from napari.utils.notifications import show_info

                self.viewer.dims.order = want
                show_info(SWAPPED)
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

    def _on_orientation(self, event=None) -> None:
        """Show the flip as the camera has it, whoever turned it over."""
        flipped = upside_down(self.viewer)
        if self.flip.isChecked() != flipped:
            self.flip.blockSignals(True)
            self.flip.setChecked(flipped)
            self.flip.blockSignals(False)

    def _on_flip(self, on: bool) -> None:
        """Show the picture upside down, or upright."""
        if self._busy:
            return
        try:
            self.session.set_flip(on)
        except Exception as exc:                      # noqa: BLE001
            _report("could not flip the picture", exc)

    def _on_change(self, _index: int) -> None:
        self._on_brain_shown()
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
        """Build `want` beside the open scene, and only then drop the open
        one; the status bar holds its words meanwhile (`app.hold_status`)."""
        from .app import hold_status

        with hold_status(self.viewer):
            self._build(want)

    def _build(self, want: str) -> None:
        """Build `want` beside the open scene, and only then drop the open one.

        A failed build is undone and the open scene was never touched, so the
        user gets back exactly what they had: every tab's checked rows,
        labels, fills, filter and driver line, the open tab, the mirror, the
        flip, the angles and the alignment.
        What the build did move belongs to the viewer -- the slice axis and
        plane, the camera, the selected layer, the title, the axis triads
        and the home button -- and is put back from what was captured before
        it started. Rebuilding the previous space instead, as this used to,
        gave its defaults back rather than the user's scene.

        The status line says what happened in words; what went wrong in
        detail is printed to the terminal.
        """
        old = self.session
        anatomy = self._anatomy.get(old.slice_axis)
        before = capture_view(self.viewer)
        title = self._title(want)
        self.status.setText(OPENING.format(title=title))
        # Painted now: the build holds the event loop until it is done.
        self.status.repaint()
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
            _report(f"could not open {want}", exc)
            self.status.setText(FAILED.format(title=title, reason=plain_reason(exc)))
            index = self.combo.findData(old.space)
            if index >= 0:
                self.combo.setCurrentIndex(index)
            return
        old.teardown()
        new.take_names()
        # The new space comes up unmirrored and the control follows it. The
        # mirror is how one space is being looked at, not a preference:
        # carried across, it would hand back a reflected scene nobody
        # reflected, and the reflection is the one thing here that can make
        # left read as right. `_busy` keeps `_on_mirror` out of it. A failed
        # switch keeps the open scene, mirror and all, and never gets here.
        self.mirror.setChecked(False)
        # Upright too, for the same reason. The flip is the camera's, which
        # the new scene was built under: its Home faces the same way either
        # way (`view.show_upside_down`), so only the flip is undone.
        self.flip.setChecked(False)
        try:
            new.set_flip(False)
        except Exception as exc:                      # noqa: BLE001
            _report(f"opened {want} but could not turn the picture upright", exc)
        try:
            new.settle_view()
            self.status.setText("")
        except Exception as exc:                      # noqa: BLE001
            # The new scene is complete and the old one gone; only framing
            # it failed, which is worth saying but not undoing.
            _report(f"opened {want} but could not fit it", exc)
            self.status.setText(UNFITTED.format(title=title))
        self._carry_turn(new, title)

    def _carry_turn(self, new, title: str) -> None:
        """Turn the new scene as the controls say, once it is framed.

        Unlike the mirror, the angles and the alignment carry across: they
        mean the same on screen in every brain, and a switch keeps showing
        the new brain the way the old one was shown. The alignment first,
        since the angles turn from the base view it sets.
        """
        aligned, angles = self.align.isChecked(), self.rotation.angles()
        if not aligned and not any(angles):
            return
        try:
            new.set_aligned(aligned)
            new.set_rotation(*angles)
        except Exception as exc:                      # noqa: BLE001
            _report(f"opened {title} but could not turn it", exc)
            self.status.setText(UNTURNED.format(title=title))


def _report(what: str, exc: BaseException) -> None:
    """Print a failure in full to the terminal, where a bug report starts."""
    print(f"lobemap: {what}:", file=sys.stderr)
    traceback.print_exception(exc, file=sys.stderr)


__all__ = ["SpaceSwitcher", "brain_tip", "plain_reason", "section_label"]
