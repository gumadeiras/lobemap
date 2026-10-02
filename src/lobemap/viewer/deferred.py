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

The meshes themselves are read whole, into the registry, by a thread
started before the rest of the scene is built, so opening a part's tab only
builds its layers; a tab opened soon after the space used to read its mesh
first, 74 ms for the hemibrain neuropils. `hold` waits for the thread, and
in every space it has long finished: the hemibrain's neuropils take 74 ms
to read, the male CNS's 37 and FAFB's 3, and `hold` comes after the primary
atlas, the images and their contours are built. An atlas's mesh is in
memory already, since the registry reads it for its compartment names. The
corners come from those meshes. The thread only reads files.
"""

from __future__ import annotations

import contextlib
import threading

import numpy as np

#: What a stand-in is called: its part's name, and that it is not built.
STANDIN_NAME = "{name} (not opened)"


class Deferred:
    """The parts one scene left for later, their meshes and their stand-ins.

    `parts` is every deferred part by scene key. Their meshes are read from
    the moment this is made; `hold` waits for them and adds the stand-ins,
    and `adopt` hands the part being built its stand-in. `show` is called
    with a part's name when its stand-in is switched on.
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
        self._reader = threading.Thread(target=self._read, name="lobemap-bounds",
                                        daemon=True)
        self._reader.start()

    def _read(self) -> None:
        """Read each part's mesh into the registry, and its lowest and highest
        vertex per axis."""
        for name, part in self.parts.items():
            # Unreadable: no stand-in, and its tab says why when it opens.
            with contextlib.suppress(Exception):
                vertices = self.registry.mesh(part.asset.id).vertices
                if len(vertices):
                    self._bounds[name] = vertices.min(axis=0), vertices.max(axis=0)

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

    def centre_on(self, name: str) -> None:
        """Put every slider where napari puts it when `name` is the first layer.

        napari opens each slider on the middle step of the first layer it is
        given, counted in that layer's own steps, a Surface's being 1 data
        unit (`Dims._go_to_center_step`). A space used to add its first
        neuropil set first; deferred, the first layer is the image, and a
        slice axis chosen right after the open landed on another plane, 26 um
        off on x in FAFB14. The point is then put on the scene's slider grid,
        as napari snapped it there once the other layers were added.
        """
        bounds = self._bounds.get(name)
        if bounds is None:
            return
        lo, hi = (np.asarray(b, float) for b in bounds)
        middle = lo + np.floor(np.floor(hi - lo) / 2)
        dims = self.viewer.dims
        dims.current_step = tuple(round((m - r.start) / (r.step or 1))
                                  for m, r in zip(middle, dims.range, strict=True))

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


__all__ = ["STANDIN_NAME", "Deferred"]
