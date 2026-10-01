"""The parts of a scene not built yet, and the room they take in the view.

A space opens with its primary atlas built; its other atlases and its
neuropil sets are built the first time their tab opens
(`scene.SceneSession.realize`). napari's sliders and its fit span the
layers there are, so a part reaching outside them moved both when it was
built: the slider grid shifted, napari snapped the plane onto the new grid,
and the view had opened framed on less than the scene. In FAFB14 the
neuropils reach 100 um past the stain on x.

So such a part holds its place from the start with a stand-in: a hidden
Surface layer of two vertices, the corners of the part's mesh, which the
part's own layers replace when it is built. It is named for the part, and
switching it on in the layer list builds the part and shows it, as the
part's own layer did when every part was built at open.

The corners come from the mesh file's vertices alone, read in a thread
while the rest of the scene is built -- for an atlas, from the mesh the
registry already holds. That thread only reads files; it touches no layer
and no Qt object.
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
    """The parts one scene left for later, and their stand-ins.

    `parts` is every deferred part by scene key. Their bounds are read from
    the moment this is made; `hold` waits for them and adds the stand-ins,
    and `release` drops one once its part is built. `show` is called with a
    part's name when its stand-in is switched on.
    """

    def __init__(self, viewer, registry, parts: dict, show=None) -> None:
        self.viewer = viewer
        self.registry = registry
        self.parts = dict(parts)
        self.show = show
        #: Part name -> its stand-in layer, while it is not built.
        self.standins: dict = {}
        self._bounds: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        self._reader = threading.Thread(target=self._read_bounds, name="lobemap-bounds",
                                        daemon=True)
        self._reader.start()

    def _read_bounds(self) -> None:
        for name, part in self.parts.items():
            # Unreadable: no stand-in, and its tab says why when it opens.
            with contextlib.suppress(Exception):
                self._bounds[name] = mesh_bounds(self.registry, part)

    def layers(self) -> list:
        return list(self.standins.values())

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
            layer.events.visible.connect(lambda event, name=name: self._on_eye(name))
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

    def release(self, name: str) -> None:
        """Drop the stand-in of a part whose own layers are in now."""
        self.parts.pop(name, None)
        layer = self.standins.pop(name, None)
        if layer is not None:
            with contextlib.suppress(Exception):
                self.viewer.layers.remove(layer)


__all__ = ["STANDIN_NAME", "Deferred", "mesh_bounds"]
