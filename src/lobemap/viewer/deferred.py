"""The parts of a scene not built yet: the room they take, and their meshes.

A space opens with its primary atlas built; its other atlases and its
neuropil sets are built the first time their tab opens
(`scene.SceneSession.realize`). napari's sliders and its fit span the
layers there are, so a part reaching outside them moved both when it was
built: the slider grid shifted, napari snapped the plane onto the new grid,
and the view had opened framed on less than the scene. In FAFB14 the
neuropils reach 100 um past the stain on x.

So such a part holds its place from the start with a stand-in: a hidden
Surface layer of two vertices, the corners of the part's mesh, which
becomes the part's mesh layer when it is built -- taken over rather than
replaced, since napari charges a layer's removal a full garbage collection,
50-70 ms. It is named for the part, and switching it on in the layer list
builds the part and shows it, as the part's own layer did when every part
was built at open.

The corners come from the mesh file's vertices alone, read in a thread
while the rest of the scene is built -- for an atlas, from the mesh the
registry already holds.

Once the space is open, a second thread reads each deferred part's mesh, so
opening its tab only builds its layers: reading the hemibrain neuropils was
76 ms of the 180 their tab took. It follows the contour prefetch's rules
(`prefetch`): it gives way while the UI thread slices, starting no file
within `prefetch.QUIET_S` of a slice, and it touches no layer and no Qt
object. Each mesh is read once: a tab opened while its mesh is being read
waits for that read, and one opened before the thread reached it reads it
itself and the thread passes it by.

Both threads only read files and hand back arrays.
"""

from __future__ import annotations

import contextlib
import threading
import time

import numpy as np

from . import napari_private
from .prefetch import QUIET_S

#: What a stand-in is called: its part's name, and that it is not built.
STANDIN_NAME = "{name} (not opened)"

#: When napari last sliced on the UI thread; see `read_ahead`.
_last_slice = [0.0]

#: A mesh the read-ahead thread is reading now.
_READING = object()


def _sliced() -> None:
    _last_slice[0] = time.perf_counter()


def mesh_bounds(registry, part) -> tuple[np.ndarray, np.ndarray]:
    """The lowest and highest vertex of a part's mesh, per axis.

    An atlas's mesh is in memory already: the registry reads it for its
    compartment names. A neuropil set's is read only when it is built, and
    reading its vertices alone costs well under half of reading it: 29 ms
    of the 76 the hemibrain's takes.
    """
    if part.reference:
        with np.load(part.asset.path, allow_pickle=False) as z:
            vertices = z["vertices"]
    else:
        vertices = registry.mesh(part.asset.id).vertices
    if not len(vertices):
        raise ValueError(f"{part.name} has no vertices")
    return vertices.min(axis=0), vertices.max(axis=0)


class Deferred:
    """The parts one scene left for later, their stand-ins and their meshes.

    `parts` is every deferred part by scene key. Their bounds are read from
    the moment this is made; `hold` waits for them and adds the stand-ins,
    `read_ahead` reads their meshes once the space is open, and `take` and
    `adopt` hand the part being built its mesh and its stand-in. `show` is
    called with a part's name when its stand-in is switched on.
    """

    def __init__(self, viewer, registry, parts: dict, show=None) -> None:
        self.viewer = viewer
        self.registry = registry
        self.parts = dict(parts)
        self.show = show
        #: Part name -> its stand-in layer, while it is not built.
        self.standins: dict = {}
        #: Part name -> its stand-in's eye handler.
        self._eyes: dict = {}
        self._bounds: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        self._reader = threading.Thread(target=self._read_bounds, name="lobemap-bounds",
                                        daemon=True)
        self._reader.start()
        #: Part name -> its mesh read ahead, the error reading it raised, or
        #: `_READING`; see `take`.
        self._meshes: dict = {}
        #: Parts the UI thread has asked for: the read-ahead passes them by.
        self._taken: set[str] = set()
        self._done = threading.Condition()
        self._stopped = False

    def _read_bounds(self) -> None:
        for name, part in self.parts.items():
            # Unreadable: no stand-in, and its tab says why when it opens.
            with contextlib.suppress(Exception):
                self._bounds[name] = mesh_bounds(self.registry, part)

    def layers(self) -> list:
        """The stand-ins still in the viewer: one deleted by hand holds nothing."""
        return [layer for layer in self.standins.values() if layer in self.viewer.layers]

    def hold(self, built) -> None:
        """Add a stand-in for each part reaching outside the layers `built`.

        A part inside them moves nothing when it is built, and gets none.
        Added under every layer, and the layer selection is left as it was.
        """
        self._reader.join()
        layers = self.viewer.layers
        extent = layers.get_extent(built).world if built else None
        selected, active = list(layers.selection), layers.selection.active
        for name, (lo, hi) in self._bounds.items():
            if extent is not None and np.all(lo >= extent[0]) and np.all(hi <= extent[1]):
                continue
            layer = self.viewer.add_surface(
                (np.stack([lo, hi]), np.zeros((0, 3), dtype=int)),
                name=STANDIN_NAME.format(name=name), visible=False, shading="none",
            )
            layer.metadata["lobemap"] = {"kind": "stand-in", "part": name}
            layers.move(layers.index(layer), 0)
            self._eyes[name] = lambda event, name=name: self._on_eye(name)
            layer.events.visible.connect(self._eyes[name])
            self.standins[name] = layer
        if self.standins:
            layers.selection.clear()
            layers.selection.update(selected)
            if active in selected:
                layers.selection.active = active

    def _on_eye(self, name: str) -> None:
        """Switched on in the layer list: build the part and show it.

        After the click has been handled, since building it removes the
        layer whose eye was clicked.
        """
        layer = self.standins.get(name)
        if layer is None or not layer.visible or self.show is None:
            return
        from qtpy.QtCore import QTimer

        def _show() -> None:
            with contextlib.suppress(Exception):
                self.show(name)
            left = self.standins.get(name)
            if left is not None:            # not built: it draws nothing
                left.visible = False

        QTimer.singleShot(0, _show)

    def adopt(self, name: str):
        """Hand over the stand-in of a part being built, to become its mesh layer.

        None if it has none. From now on it is the part's, not a stand-in.
        """
        self.parts.pop(name, None)
        layer = self.standins.pop(name, None)
        if layer is not None:
            with contextlib.suppress(Exception):
                layer.events.visible.disconnect(self._eyes.pop(name))
        return layer

    # -- the meshes ---------------------------------------------------------

    def read_ahead(self) -> None:
        """Read the deferred meshes in a thread, from when the event loop next runs.

        Not before: the space is opened first, uncontested. It stops with
        the scene, or when the viewer closes and empties its layer list.
        """
        from qtpy.QtCore import QTimer

        napari_private.before_slicing(self.viewer, _sliced)
        self.viewer.layers.events.removed.connect(self._on_removed)
        QTimer.singleShot(0, self._start)

    def _on_removed(self, event=None) -> None:
        if not len(self.viewer.layers):
            self.stop()

    def _start(self) -> None:
        if self._stopped:
            return
        parts = list(self.parts.items())
        threading.Thread(target=self._read_meshes, args=(parts,), name="lobemap-meshes",
                         daemon=True).start()

    def _read_meshes(self, parts) -> None:
        for name, part in parts:
            # A file is read whole once started, so it waits for a pause.
            while not self._stopped and time.perf_counter() - _last_slice[0] < QUIET_S:
                time.sleep(0.01)
            with self._done:
                if self._stopped:
                    return
                if name in self._taken:
                    continue
                self._meshes[name] = _READING
            try:
                got = self.registry.mesh(part.asset.id)
            except Exception as exc:                  # noqa: BLE001 - its tab says why
                got = exc
            with self._done:
                self._meshes[name] = got
                self._done.notify_all()

    def take(self, name: str):
        """The mesh of `name` if it was read ahead, else None for the caller to read.

        A read under way is waited for rather than made twice, and from now
        on the read-ahead leaves this part alone. An error it met is raised
        here, once; asking again reads anew.
        """
        with self._done:
            self._taken.add(name)
            self._done.wait_for(lambda: self._meshes.get(name) is not _READING)
            got = self._meshes.pop(name, None)
        if isinstance(got, BaseException):
            raise got
        return got

    def stop(self) -> None:
        """No further mesh is read: the scene is being torn down."""
        with self._done:
            self._stopped = True
        with contextlib.suppress(Exception):          # never connected, or gone
            self.viewer.layers.events.removed.disconnect(self._on_removed)


__all__ = ["STANDIN_NAME", "Deferred", "mesh_bounds"]
