"""Make the README's screenshots and animations of the viewer.

Every picture and animation in `docs/images` is made here, from the data on
disk, by driving the real viewer in a shown window through its own controls:
the View dock's Brain menu, 3D and Slice buttons, Sections menu, Zoom box and
Rotate around boxes; the Brain regions panel's tabs, rows and header
checkboxes; the layer list's eye; and mouse moves and clicks on the canvas.
The camera is panned by setting its center, as a drag would. Each frame is
taken once nothing it shows is still loading -- the 3D stain's fine level,
the 2D chunks, the resampled oblique planes -- and ffmpeg assembles the
animations.

Usage, from the repository root, with the full data on disk, stains included
(`lobemap fetch`), and the screen awake:

    caffeinate -di uv run --no-sync python docs/make_media.py
    caffeinate -di uv run --no-sync python docs/make_media.py turntable slice-sweep
    uv run --no-sync python docs/make_media.py --list

With no names it makes every asset, in about four minutes. Options:

    --out DIR      write the assets there instead of docs/images
    --frames DIR   keep each animation's frames there, one folder each
    --no-optimize  leave the PNGs as Qt wrote them; by default `imageoptim`
                   optimizes them losslessly when it is installed

What it writes, all in `docs/images`:

    hemibrain-3d.png      the hemibrain in 3D: stain, glomeruli, neuropils, DA1 picked
    slice-outlines.png    a FAFB section: outlines, fills and names over the stain
    oblique-section.png   a true oblique section through the male CNS
    grabe-confocal.png    GRABE: the confocal image and the Grabe 2015 glomeruli
    turntable.gif/.mp4    the male CNS lobes turned about the vertical axis
    slice-sweep.gif/.mp4  sections stepped through FAFB's antennal lobe
    oblique-sweep.gif/.mp4  the vertical-axis angle swept, the plane recut
    brain-switch.gif/.mp4   the four brains, one after another

It needs a Retina display (a device pixel ratio of 2) with room for a 1440 x
900 window, and ffmpeg on the PATH. The window is a user's: napari's default
dark theme, from a settings file of its own in a temporary folder so neither
your napari settings nor anything else of yours changes it, and the docks as
lobemap lays them out. It ignores the mouse and the keyboard while it runs,
so the pictures do not depend on where the pointer is. Every brain, mode,
plane, angle, zoom, row and pointer position is fixed here, so a run on the
same data gives the same pictures.

Not a test: it lives outside `tests/` and pytest never collects it.
"""

from __future__ import annotations

import argparse
import contextlib
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from dataclasses import dataclass
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "registry"
OUT = ROOT / "docs" / "images"

#: The window, in screen points; captured at twice that.
WINDOW = (1440, 900)
SCALE = 2

#: A frame is taken once two grabs this far apart agree.
SETTLE_MS = 80
SETTLE_TRIES = 200

#: The olfactory neuropils shown for context: the antennal lobe, the
#: mushroom body's calyx, pedunculus and lobes, and the lateral horn.
OLFACTORY = ("AL", "CA", "PED", "aL", "a'L", "bL", "b'L", "gL", "LH")

#: Each brain's other brain, switched to first when a scene is reopened.
SPARE = {"GRABE": "FAFB14"}


def pump(ms: float = 0) -> None:
    """Let Qt run: queued signals, timers and repaints, for `ms` at least."""
    from qtpy.QtWidgets import QApplication

    end = time.perf_counter() + ms / 1000
    while True:
        QApplication.processEvents()
        if time.perf_counter() >= end:
            return
        time.sleep(0.005)


@dataclass(frozen=True)
class Gif:
    """How an animation's GIF trades size for detail: the stains are grain
    that a GIF's palette compresses badly, so each GIF keeps its width and
    colors as low as reads well, under about 5 MB."""

    width: int
    colors: int = 128
    dither: str = "none"


class Studio:
    """The shown viewer, driven through its own controls, and its pictures."""

    def __init__(self, viewer, out: Path, frames: Path) -> None:
        from lobemap.viewer.switcher import SpaceSwitcher

        self.viewer = viewer
        self.window = viewer.window._qt_window
        self.canvas = viewer.window._qt_viewer.canvas
        self.view = self.window.findChildren(SpaceSwitcher)[0]
        self.out, self.frames = out, frames
        self.written: list[Path] = []

    # -- the scene ----------------------------------------------------------

    @property
    def session(self):
        return self.view.session

    @property
    def camera(self):
        return self.viewer.scene.camera

    def open(self, space: str) -> None:
        """Open `space` afresh in the Brain menu, unturned and unaligned.

        A brain already open is left for another and opened again, so every
        asset starts from the same scene whatever came before it.
        """
        if self.session.space == space:
            self._choose(SPARE.get(space, "GRABE"))
        self._choose(space)
        self.view.align.setChecked(False)
        self.view.rotation.reset.click()
        pump(100)

    def _choose(self, space: str) -> None:
        combo = self.view.combo
        combo.setCurrentIndex(combo.findData(space))
        pump(200)
        if self.session.space != space:
            raise RuntimeError(f"could not open {space}: {self.view.status.text()}")

    def mode(self, three_d: bool) -> None:
        (self.view.three_d if three_d else self.view.slice_view).click()
        pump(200)

    def sections(self, plane: str) -> None:
        """Choose the Sections entry for `plane`: Frontal, Horizontal, Sagittal."""
        menu = self.view.slice
        for i in range(menu.count()):
            if menu.itemText(i).startswith(plane):
                menu.setCurrentIndex(i)
                pump(100)
                return
        raise ValueError(f"no {plane} sections")

    def angles(self, spin: float = 0.0, tilt: float = 0.0, turn: float = 0.0) -> None:
        """Type the Rotate around angles: line of sight, horizontal, vertical."""
        for name, value in (("spin", spin), ("tilt", tilt), ("turn", turn)):
            box = self.view.rotation.box[name]
            if box.value() != round(value, 1):
                box.setValue(round(value, 1))
        pump(20)

    def zoom(self, value: float) -> None:
        self.view.camera.zoom.setValue(value)

    def look_at(self, point, up: float = 0.0) -> None:
        """Pan the view's middle onto `point`, a world position, or `up`
        micrometers above it on screen, which no turn about the vertical
        axis moves."""
        point = np.asarray(point, float)
        if self.viewer.dims.ndisplay == 3:
            self.camera.center = tuple(point + up * np.asarray(self.camera.up_direction))
        else:
            self.camera.center = tuple(point[list(self.viewer.dims.displayed)])

    def pan(self, right: float = 0.0, down: float = 0.0) -> None:
        """Move the Slice view's middle `right` and `down` micrometers on
        screen, as dragging the picture the other way does."""
        center = list(self.camera.center)
        center[-1] += right
        center[-2] += down
        self.camera.center = tuple(center)

    @property
    def slice_axis(self) -> int:
        return int(self.viewer.dims.order[0])

    def plane(self, position: float) -> None:
        """Move the slider to the plane nearest `position`."""
        start, _stop, step = self.viewer.dims.range[self.slice_axis]
        self.viewer.dims.set_current_step(self.slice_axis, round((position - start) / step))
        pump(20)

    def step_plane(self, steps: int) -> None:
        """Move the slider by whole steps, as its arrows do."""
        current = self.viewer.dims.current_step[self.slice_axis]
        self.viewer.dims.set_current_step(self.slice_axis, current + steps)

    # -- the panel ------------------------------------------------------------

    def table(self, kind: str = "Glomeruli"):
        """Open the panel's `kind` tab; return the table its Source shows."""
        panel = self.session.panel
        page = panel.pages[kind]
        panel.setCurrentWidget(page)
        pump(100)
        return panel.tabs[page.chosen]

    def tick(self, tab, names, column=None) -> None:
        """Tick the boxes of the rows named `names` in `column`, Show by default."""
        from qtpy.QtCore import Qt

        from lobemap.viewer.panel_tab import NAME_COL, VISIBLE_COL

        column = VISIBLE_COL if column is None else column
        found = set()
        for r in range(tab.table.rowCount()):
            name = tab.table.item(r, NAME_COL).text()
            if name in names:
                tab.table.item(r, column).setCheckState(Qt.CheckState.Checked)
                found.add(name)
        if found != set(names):
            raise ValueError(f"no rows {sorted(set(names) - found)}")
        pump(50)

    def header(self, tab, column: int) -> None:
        """Click the checkbox in a column's header: every listed row."""
        tab.header.toggled.emit(column)
        pump(50)

    def hide(self, prefix: str) -> None:
        """Close the eye of the layer named `prefix` in the layer list."""
        for layer in self.viewer.layers:
            if layer.name.startswith(prefix):
                layer.visible = False
        pump(50)

    @staticmethod
    def index(tab, name: str) -> int:
        return tab.surface.meshset.names.index(name)

    @staticmethod
    def middle(meshes, indices=None):
        """The middle of the box around these compartments, in world units."""
        indices = range(meshes.n_compartments) if indices is None else indices
        vertices = np.concatenate([meshes.compartment(i)[0] for i in indices])
        return (vertices.min(axis=0) + vertices.max(axis=0)) / 2

    # -- the pointer ----------------------------------------------------------

    def on_screen(self, world) -> tuple[float, float]:
        """Where a point of napari's world is drawn on the canvas, in its pixels."""
        shown = np.asarray(world, float)[list(self.viewer.dims.displayed)][::-1]
        mapped = self.canvas.view.scene.transform.map(np.r_[shown, [0.0] * (3 - len(shown)), 1.0])
        return mapped[0] / mapped[3], mapped[1] / mapped[3]

    def inside(self, tab, name: str):
        """A world point deep inside `name`'s outline on the section shown:
        of a grid over each of its loops, the point farthest from the loop
        that the panel's own picking (`slicing.polygon_at`) finds in it."""
        from lobemap.viewer.slicing import polygon_at

        overlay, shown = tab.contour, list(self.viewer.dims.displayed)
        loops = [np.asarray(path, float) for path in overlay.paths]
        flat = [loop[:, shown] for loop in loops]
        best, depth = None, -1.0
        for i in (i for i in range(len(loops)) if overlay.name_at_shape(i) == name):
            lo, hi = flat[i].min(axis=0), flat[i].max(axis=0)
            for u in np.linspace(lo[0], hi[0], 17)[1:-1]:
                for v in np.linspace(lo[1], hi[1], 17)[1:-1]:
                    here = np.array([u, v])
                    if polygon_at(flat, here) != i:
                        continue
                    clear = float(np.min(np.hypot(*(flat[i] - here).T)))
                    if clear > depth:
                        point = loops[i][0].copy()
                        point[shown] = here
                        best, depth = point, clear
        if best is None:
            here = sorted({overlay.name_at_shape(i) for i in range(len(loops))})
            raise RuntimeError(f"{name} is not on this section, which cuts {here}")
        return overlay.layer.data_to_world(best)

    def _mouse(self, kind, xy, button=None, buttons=None) -> None:
        from qtpy.QtCore import QEvent, QPointF, Qt
        from qtpy.QtGui import QMouseEvent
        from qtpy.QtWidgets import QApplication

        widget = self.canvas.native
        local = QPointF(*xy)
        event = QMouseEvent(
            getattr(QEvent.Type, kind), local, QPointF(widget.mapToGlobal(local.toPoint())),
            button or Qt.MouseButton.NoButton, buttons or Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(widget, event)
        pump(50)

    def touch(self) -> None:
        """Click an empty corner of the canvas, as a user's first click.

        Until the canvas is first touched lobemap refits the brain whenever
        the canvas changes size (`view.install_initial_fit`), which would
        undo a zoom set here when Slice view's slider appears.
        """
        from qtpy.QtCore import Qt

        left = Qt.MouseButton.LeftButton
        self._mouse("MouseButtonPress", (2.0, 2.0), left, left)
        self._mouse("MouseButtonRelease", (2.0, 2.0), left)

    def point_at(self, tab, name: str, click: bool = False) -> None:
        """Rest the pointer on a compartment, or click it, and check the
        status bar names it as lobemap does: 'DA1 (right) — neuPrint'.

        In 3D on the middle of its mesh, which must face the viewer; in Slice
        view inside its outline.
        """
        from qtpy.QtCore import Qt

        index = self.index(tab, name)
        if self.viewer.dims.ndisplay == 3:
            xy = self.on_screen(tab.surface.meshset.centroid(index))
        else:
            xy = self.on_screen(self.inside(tab, name))
        self._mouse("MouseMove", xy)
        if click:
            left = Qt.MouseButton.LeftButton
            self._mouse("MouseButtonPress", xy, left, left)
            self._mouse("MouseButtonRelease", xy, left)
        pump(200)
        said = tab.describe(index)
        if self.viewer.status != said:
            raise RuntimeError(f"pointing at {name} says {self.viewer.status!r}, not {said!r}")

    # -- pictures -------------------------------------------------------------

    def rect(self, widget, top=0, bottom=0):
        """A widget's rectangle in the window, in captured pixels, less `top`
        and `bottom` screen points."""
        from qtpy.QtCore import QRect

        corner = widget.mapTo(self.window, widget.rect().topLeft())
        return QRect(corner.x() * SCALE, (corner.y() + top) * SCALE, widget.width() * SCALE,
                     (widget.height() - top - bottom) * SCALE)

    def _fine_levels_in(self) -> None:
        """Wait for the 3D stain's fine level, read in the background."""
        if self.viewer.dims.ndisplay != 3:
            return
        deadline = time.monotonic() + 60
        for layer in self.viewer.layers:
            level = layer.metadata.get("lobemap", {}).get("level_3d")
            while (level is not None and layer.visible
                   and layer.locked_data_level != level):
                if time.monotonic() > deadline:
                    raise RuntimeError(f"{layer.name} never reached its 3D level")
                pump(30)

    def still(self, rect=None):
        """The window as drawn once nothing in it is still loading: two grabs
        `SETTLE_MS` apart agree. Cropped to `rect`."""
        self._fine_levels_in()
        previous = None
        for _ in range(SETTLE_TRIES):
            pump(SETTLE_MS)
            image = self.window.grab().toImage()
            if rect is not None:
                image = image.copy(rect)
            if image == previous:
                return image
            previous = image
        raise RuntimeError("the picture kept changing")

    def picture(self, name: str) -> None:
        """Save the whole window as `name`.png."""
        path = self.out / f"{name}.png"
        if not self.still().save(str(path)):
            raise OSError(f"could not write {path}")
        self.written.append(path)
        print(f"  {path.name}", flush=True)

    def animate(self, name: str, poses, fps: int, gif: Gif, rect=None) -> None:
        """Take one frame after each pose, then write `name`.gif and .mp4.

        `poses` is an iterable whose every step leaves the viewer as the next
        frame shows it; a step that yields a number repeats the last frame
        that many times more.
        """
        folder = self.frames / name
        if folder.exists():
            shutil.rmtree(folder)
        folder.mkdir(parents=True)
        count, last = 0, None
        for repeat in poses:
            if repeat:
                for _ in range(int(repeat)):
                    shutil.copyfile(last, folder / f"{count:04d}.png")
                    count += 1
                continue
            last = folder / f"{count:04d}.png"
            if not self.still(rect).save(str(last)):
                raise OSError(f"could not write {last}")
            count += 1
        print(f"  {name}: {count} frames", flush=True)
        self.written += encode(folder, self.out / name, fps, gif)


def ffmpeg(*args) -> None:
    subprocess.run([shutil.which("ffmpeg") or "ffmpeg", "-v", "error", "-y", *args],
                   check=True)


def encode(frames: Path, stem: Path, fps: int, gif: Gif) -> list[Path]:
    """The frames as a looping GIF, on a palette of their own, and an H.264
    MP4 at their full size."""
    source = ["-framerate", str(fps), "-i", str(frames / "%04d.png")]
    mp4, out = stem.with_suffix(".mp4"), stem.with_suffix(".gif")
    ffmpeg(*source, "-c:v", "libx264", "-preset", "slow", "-crf", "18",
           "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(mp4))
    ffmpeg(*source, "-vf",
           f"scale={gif.width}:-2:flags=area,split[a][b];"
           f"[a]palettegen=max_colors={gif.colors}:stats_mode=diff[p];"
           f"[b][p]paletteuse=dither={gif.dither}:diff_mode=rectangle",
           "-loop", "0", str(out))
    return [out, mp4]


# -- the assets -----------------------------------------------------------------


def hemibrain_3d(studio: Studio) -> None:
    """The hemibrain in 3D: the stain, neuPrint's glomeruli and the olfactory
    neuropils, all translucent, turned a little, with DA1 clicked so the
    panel shows its details."""
    studio.open("JRCFIB2018F")
    studio.mode(True)
    neuropils = studio.table("Neuropils")
    studio.tick(neuropils, OLFACTORY)
    glomeruli = studio.table("Glomeruli")
    right = [i for i, n in enumerate(neuropils.surface.meshset.names) if n.endswith("(R)")
             and i in neuropils.surface.selection]
    lobe = [i for i, n in enumerate(glomeruli.surface.meshset.names) if n.endswith("(R)")]
    middle = (studio.middle(neuropils.surface.meshset, right)
              + studio.middle(glomeruli.surface.meshset, lobe)) / 2
    studio.angles(tilt=15, turn=-25)
    studio.look_at(middle)
    studio.zoom(1.9)
    studio.point_at(glomeruli, "DA1(R)", click=True)
    studio.picture("hemibrain-3d")


def fafb_lobe(studio: Studio):
    """FAFB in Slice view, frontal sections, every glomerulus named and
    filled, zoomed onto Benton 2025's antennal lobe. Its table and middle."""
    from lobemap.viewer.panel_tab import FILL_COL, LABEL_COL

    studio.open("FAFB14")
    studio.mode(False)
    studio.sections("Frontal")
    glomeruli = studio.table("Glomeruli")
    studio.header(glomeruli, LABEL_COL)
    studio.header(glomeruli, FILL_COL)
    middle = studio.middle(glomeruli.surface.meshset)
    studio.zoom(4.0)
    studio.look_at(middle)
    return glomeruli, middle


def slice_outlines(studio: Studio) -> None:
    """A frontal section of FAFB's left antennal lobe: the outlines, fills and
    names of Benton 2025's glomeruli over the stain, and the corner arrows."""
    glomeruli, middle = fafb_lobe(studio)
    studio.plane(middle[studio.slice_axis] - 8)
    studio.point_at(glomeruli, "DA1")
    studio.picture("slice-outlines")


def male_cns_lobe(studio: Studio, zoom: float):
    """The male CNS in Slice view, frontal sections, every glomerulus filled,
    centered on the right antennal lobe. Its table."""
    from lobemap.viewer.panel_tab import FILL_COL

    studio.open("JRCFIB2022M")
    studio.mode(False)
    studio.sections("Frontal")
    glomeruli = studio.table("Glomeruli")
    studio.header(glomeruli, FILL_COL)
    meshes = glomeruli.surface.meshset
    middle = studio.middle(meshes, [i for i, n in enumerate(meshes.names) if n.endswith("(R)")])
    studio.zoom(zoom)
    studio.look_at(middle)
    studio.plane(middle[studio.slice_axis])
    return glomeruli


def oblique_section(studio: Studio) -> None:
    """A true oblique section of the male CNS: turned about the vertical and
    the horizontal axis, the stain resampled on the plane and the
    glomeruli cut exactly on it; the slider reads depth."""
    glomeruli = male_cns_lobe(studio, zoom=1.5)
    studio.angles(tilt=-20, turn=35)
    # The lobe to the right, the optic lobe the plane reaches to the left.
    studio.pan(right=-45)
    studio.point_at(glomeruli, "DC1(R)")
    studio.picture("oblique-section")


def grabe_confocal(studio: Studio) -> None:
    """GRABE in 3D: the in vivo confocal stack and Grabe 2015's glomeruli."""
    studio.open("GRABE")
    studio.mode(True)
    studio.view.home.click()
    glomeruli = studio.table("Glomeruli")
    studio.point_at(glomeruli, "DA1(L)")
    studio.picture("grabe-confocal")


def turntable(studio: Studio) -> None:
    """The male CNS lobes and the olfactory neuropils, turned all the way
    round the screen's vertical axis by the Vertical axis box, 3 degrees a
    frame. The stain is switched off: its grain made each GIF frame five
    times larger."""
    studio.open("JRCFIB2022M")
    studio.mode(True)
    neuropils = studio.table("Neuropils")
    studio.tick(neuropils, [n for n in OLFACTORY if n != "AL"])
    glomeruli = studio.table("Glomeruli")
    studio.hide("Neuropil stain")
    shown = sorted(neuropils.surface.selection)
    pivot = (studio.middle(neuropils.surface.meshset, shown)
             + studio.middle(glomeruli.surface.meshset)) / 2
    zoom, height = 1.4, 540
    canvas = studio.canvas.native
    # The bottom of the canvas, arrows included, with the brain above them.
    rect = studio.rect(canvas, top=canvas.height() - height)
    up = (canvas.height() - height + 0.36 * height - canvas.height() / 2) / zoom

    def poses():
        for k in range(120):
            studio.angles(turn=-180 + 3 * k)
            studio.zoom(zoom)
            studio.look_at(pivot, up=up)
            yield 0

    studio.animate("turntable", poses(), fps=15, gif=Gif(width=720, dither="bayer:bayer_scale=3"),
                   rect=rect)


def slice_sweep(studio: Studio) -> None:
    """Frontal sections of FAFB's left lobe, front to back and back again,
    2 micrometers a frame: the outlines, fills and names follow the stain."""
    glomeruli, _middle = fafb_lobe(studio)
    meshes = glomeruli.surface.meshset
    axis = studio.slice_axis
    first, last = meshes.vertices[:, axis].min() + 4, meshes.vertices[:, axis].max() - 4
    planes = np.arange(first, last, 2.0)
    canvas = studio.canvas.native
    rect = studio.rect(canvas, top=220, bottom=185)

    def poses():
        for position in [*planes, *planes[-2:0:-1]]:
            studio.plane(position)
            yield 0

    studio.animate("slice-sweep", poses(), fps=15, gif=Gif(width=600, colors=64), rect=rect)


def oblique_sweep(studio: Studio) -> None:
    """The male CNS in Slice view, the Vertical axis angle swept from -40 to
    40 degrees and back: the stain resampled and the glomeruli recut on each
    plane. The View dock is in the picture, so the angle can be read."""
    male_cns_lobe(studio, zoom=2.4)
    from qtpy.QtCore import QRect

    canvas = studio.rect(studio.canvas.native)
    slider = studio.rect(studio.viewer.window._qt_viewer.dims)
    rect = QRect(0, 0, canvas.right() + 1, slider.bottom() + 1)
    frames = 76

    def poses():
        for k in range(frames):
            # Half a frame off, so no frame is at 0 degrees: there the view
            # is at rest, unturned, and its slider read z for that one frame.
            studio.angles(turn=-40 * math.cos(2 * math.pi * (k + 0.5) / frames))
            yield 0

    studio.animate("oblique-sweep", poses(), fps=12, gif=Gif(width=680, colors=48), rect=rect)


def brain_switch(studio: Studio) -> None:
    """The four brains in 3D, each opened from the Brain menu and held for two
    seconds, with the pointer on one of its glomeruli."""
    order = ("FAFB14", "JRCFIB2018F", "JRCFIB2022M", "GRABE")
    pointed = {"FAFB14": "DA1", "JRCFIB2018F": "DA1(R)", "JRCFIB2022M": "DA1(L)",
               "GRABE": "DA1(L)"}
    studio.open(order[0])
    studio.mode(True)
    fps, hold = 15, 2

    def poses():
        for space in order:
            if studio.session.space != space:
                studio._choose(space)
            studio.view.home.click()
            studio.point_at(studio.table("Glomeruli"), pointed[space])
            yield 0
            yield fps * hold - 1

    studio.animate("brain-switch", poses(), fps=fps, gif=Gif(width=960))


ASSETS = {
    "hemibrain-3d": hemibrain_3d,
    "slice-outlines": slice_outlines,
    "oblique-section": oblique_section,
    "grabe-confocal": grabe_confocal,
    "turntable": turntable,
    "slice-sweep": slice_sweep,
    "oblique-sweep": oblique_sweep,
    "brain-switch": brain_switch,
}


# -- running ----------------------------------------------------------------------


def place(viewer) -> None:
    """Show the window at `WINDOW`, unmaximized, ignoring the pointer and the
    keyboard, and check it is drawn at `SCALE`."""
    from qtpy.QtCore import Qt

    window = viewer.window._qt_window
    pump(300)                   # lobemap's own maximize, which runs late
    window.showNormal()
    window.setWindowFlag(Qt.WindowType.WindowTransparentForInput, True)
    window.setWindowFlag(Qt.WindowType.WindowDoesNotAcceptFocus, True)
    window.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
    room = window.screen().availableGeometry()
    window.resize(*WINDOW)
    window.move(room.topLeft())
    window.show()
    pump(1500)
    if (window.width(), window.height()) != WINDOW:
        raise RuntimeError(f"the window is {window.width()}x{window.height()}, not "
                           f"{WINDOW[0]}x{WINDOW[1]}: the screen is too small")
    if window.devicePixelRatio() != SCALE:
        raise RuntimeError(f"the screen draws at {window.devicePixelRatio()}x, not {SCALE}x")


def optimize(paths: list[Path]) -> None:
    """Optimize the PNGs losslessly with imageoptim, and say what it saved."""
    pngs = [p for p in paths if p.suffix == ".png"]
    tool = shutil.which("imageoptim")
    if not pngs or tool is None:
        return
    before = {p: p.stat().st_size for p in pngs}
    subprocess.run([tool, "--no-stats", *map(str, pngs)], check=True)
    for p in pngs:
        print(f"  {p.name}: {before[p]:,} -> {p.stat().st_size:,} bytes")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("names", nargs="*", help="assets to make (default: all)")
    parser.add_argument("--list", action="store_true", help="list the assets and exit")
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--frames", type=Path, default=None,
                        help="keep the animations' frames here")
    parser.add_argument("--no-optimize", action="store_true")
    args = parser.parse_args(argv)
    if args.list:
        print("\n".join(ASSETS))
        return 0
    unknown = [n for n in args.names if n not in ASSETS]
    if unknown:
        parser.error(f"unknown assets: {', '.join(unknown)}; --list names them")
    if shutil.which("ffmpeg") is None:
        parser.error("ffmpeg is not on the PATH")
    names = args.names or list(ASSETS)
    args.out.mkdir(parents=True, exist_ok=True)

    scratch = Path(tempfile.mkdtemp(prefix="lobemap-media-"))
    # napari's settings from a file of its own: its defaults, and nothing
    # written to the user's. Set before napari is imported.
    os.environ["NAPARI_CONFIG"] = str(scratch / "napari.yaml")
    frames = args.frames or scratch / "frames"

    from napari.qt import get_qapp
    from qtpy.QtCore import QTimer

    from lobemap.viewer import app

    failure: list[BaseException] = []
    written: list[Path] = []

    def drive() -> None:
        # A Qt slot: an exception escaping it aborts the process.
        import napari

        viewer = napari.current_viewer()
        try:
            place(viewer)
            studio = Studio(viewer, args.out, frames)
            studio.touch()
            started = time.perf_counter()
            for name in names:
                print(f"{name}:", flush=True)
                ASSETS[name](studio)
            written.extend(studio.written)
            if not args.no_optimize:
                optimize(written)
            print(f"done in {time.perf_counter() - started:.0f} s", flush=True)
        except BaseException as exc:        # noqa: BLE001 - re-raised after the loop
            traceback.print_exc()
            failure.append(exc)
        finally:
            viewer.close()
            get_qapp().quit()

    get_qapp()
    QTimer.singleShot(0, drive)
    try:
        app.run(REGISTRY, "JRCFIB2018F", ndisplay=3)
    finally:
        with contextlib.suppress(OSError):
            shutil.rmtree(scratch)
    if failure:
        return 1
    for path in written:
        print(f"{path.relative_to(ROOT) if path.is_relative_to(ROOT) else path}: "
              f"{path.stat().st_size:,} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
