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

The meshes are read by a thread started before the rest of the scene is
built, in two passes. The first reads each part's corners (`mesh_bounds`),
and `hold` waits for that pass alone. The second reads each mesh whole,
into the registry, so opening a part's tab only builds its layers: a tab
opened soon after the space used to read its mesh first, 78 ms for the
hemibrain neuropils. A tab opened while its mesh is read waits for that
read (`wait`), so each mesh is read once, by the thread. One the thread
could not read is read again when its tab opens, which then says why.

On a cold open both passes are over before `hold`. A switch builds the
rest of its scene faster, and `hold` used to wait for the meshes as well:
a median of about 100 ms for the hemibrain's, in 2D. It waits for the
corners alone, a median of 7 ms there, and the meshes are read while the
switch goes on: done by its end, or at most 45 ms after it.

The thread only reads files, and touches no layer. A teardown stops it
after the file it is reading, and waits for that file.
"""

from __future__ import annotations

import contextlib
import threading

import numpy as np

#: What a stand-in is called: its part's name, and that it is not built.
STANDIN_NAME = "{name} (not opened)"


def mesh_bounds(registry, part) -> tuple[np.ndarray, np.ndarray]:
    """The lowest and highest vertex of a part's mesh, per axis.

    An atlas's mesh is in memory already: the registry reads it for its
    compartment names. A neuropil set's corners are read from its file's
    vertices alone, 30 of the 78 ms its mesh takes for the hemibrain.
    Taken column by column: NumPy reduces an (n, 3) array along its first
    axis far slower, 19 ms against 1 for those vertices.
    """
    if part.reference:
        with np.load(part.asset.path, allow_pickle=False) as z:
            vertices = z["vertices"]
    else:
        vertices = registry.mesh(part.asset.id).vertices
    if not len(vertices):
        raise ValueError(f"{part.name} has no vertices")
    return (np.array([column.min() for column in vertices.T]),
            np.array([column.max() for column in vertices.T]))


class Deferred:
    """The parts one scene left for later, their meshes and their stand-ins.

    `parts` is every deferred part by scene key. Their corners, then their
    meshes, are read from the moment this is made: `hold` waits for the
    corners and adds the stand-ins, `wait` waits for one part's mesh, and
    `adopt` hands the part being built its stand-in. `stop` ends the reads.
    `show` is called with a part's name when its stand-in is switched on.
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
        #: Set once every part's corners are read: `hold` waits for this.
        self._bounded = threading.Event()
        #: Part name -> set once the thread is done with its mesh; see `wait`.
        self._read = {name: threading.Event() for name in self.parts}
        self._stopped = False
        # The parts as made: `adopt` takes them out of `parts` meanwhile.
        self._reader = threading.Thread(target=self._run, args=(list(self.parts.items()),),
                                        name="lobemap-meshes", daemon=True)
        self._reader.start()

    def _run(self, parts) -> None:
        """Read every part's corners, then every part's mesh into the registry."""
        try:
            for name, part in parts:
                if self._stopped:
                    return
                # Unreadable: no stand-in, and its tab says why when it opens.
                with contextlib.suppress(Exception):
                    self._bounds[name] = mesh_bounds(self.registry, part)
            self._bounded.set()
            for name, part in parts:
                if self._stopped:
                    return
                # Unreadable: read again when its tab opens, which says why.
                with contextlib.suppress(Exception):
                    self.registry.mesh(part.asset.id)
                self._read[name].set()
        finally:
            # Stopped or failed, nothing waits for it forever.
            self._bounded.set()
            for done in self._read.values():
                done.set()

    def layers(self) -> list:
        """The stand-ins still in the viewer: one deleted by hand holds nothing."""
        return [layer for layer in self.standins.values() if layer in self.viewer.layers]

    def hold(self, built) -> None:
        """Add a stand-in for each part reaching outside the layers `built`.

        A part inside them moves nothing when it is built, and gets none.
        Added under every layer, and the layer selection is left as it was.
        Waits for the corners, and not for the meshes.
        """
        self._bounded.wait()
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

    def bounds(self, name: str):
        """The lowest and highest vertex of a part's mesh, per axis, or None if
        it could not be read. After `hold`."""
        return self._bounds.get(name)

    def wait(self, name: str) -> None:
        """Wait until the thread is done with the mesh of `name`.

        It is then in the registry, unless it could not be read, so the
        caller takes it from there instead of reading it beside the thread.
        """
        done = self._read.get(name)
        if done is not None:
            done.wait()

    def stop(self) -> None:
        """The scene is being torn down: read no further file, and wait for the
        one being read, so that the thread does not outlive the scene."""
        self._stopped = True
        self._reader.join()

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

        None if it has none, or if it was deleted from the layer list by
        hand: the part then gets a layer of its own. From now on it is the
        part's, not a stand-in.
        """
        self.parts.pop(name, None)
        layer = self.standins.pop(name, None)
        if layer is not None:
            with contextlib.suppress(Exception):
                layer.events.visible.disconnect(self._eyes.pop(name))
        return layer if layer is not None and layer in self.viewer.layers else None


__all__ = ["STANDIN_NAME", "Deferred", "mesh_bounds"]
