"""Image and label layers: the reference imagery under the meshes.

The LM template, the virtual synapse stains and the Grabe label volume, with
the display defaults each role needs and the pyramid level 3D pins.
"""

from __future__ import annotations

import contextlib
import threading
import warnings
import weakref

import numpy as np

from .chunkcache import cached_levels, read_whole
from .napari_private import keep_extent_while_slicing

#: Per-role display defaults for image layers.
#:
#: Gray for the stains and the Grabe stack: they are reference imagery under
#: colored glomeruli, and additive blending composites gray over them cleanly.
#:
#: `gamma` below 1 lifts the dim end, which a synapse-density map needs: the
#: distribution is long-tailed, so a linear ramp leaves most of the neuropil
#: near black while a few bright spots hold the top of the range.
#:
#: `attenuation` only does anything under `attenuated_mip`, where it fades
#: contributions by depth. Plain MIP through a whole brain is a flat wash of
#: whichever voxel happens to be brightest along each ray; attenuation
#: restores the sense of depth that makes the structure legible.
ROLE_DISPLAY = {
    "template_image": {"colormap": "gray"},
    "virtual_stain": {
        # Gray, not a hue. These are reference imagery under colored
        # glomeruli, and a magenta wash tinted every mesh drawn over it.
        "colormap": "gray",
        "gamma": 0.7,
        "rendering": "attenuated_mip",
        "attenuation": 0.1,
    },
}
DEFAULT_DISPLAY = {"colormap": "magma"}

#: Applied to every image layer unless a role overrides it.
BASE_DISPLAY = {
    "colormap": "magma",
    "blending": "additive",
    "rendering": "attenuated_mip",
}


def display_for(role: str, colormap: str | None = None,
                overrides=None) -> dict:
    """napari keyword arguments for an image layer of this role."""
    out = dict(BASE_DISPLAY)
    out.update(ROLE_DISPLAY.get(role, DEFAULT_DISPLAY))
    out.update(dict(overrides or {}))
    if colormap:
        out["colormap"] = colormap
    return out


ROLE_COLORMAP = {role: spec["colormap"] for role, spec in ROLE_DISPLAY.items()}
DEFAULT_COLORMAP = DEFAULT_DISPLAY["colormap"]

#: In 3D napari renders ONE multiscale level and, left to itself, picks the
#: coarsest -- 83x41x34 for the FAFB stain, which is unreadable. These bound
#: the level it is pinned to instead. 700 M voxels is just above the ~537 M of
#: a 2048x2048x128 confocal stack, which renders comfortably; 2048 is the 3D
#: texture limit a GPU is allowed to impose, and level 0 exceeds it at 2818.
VIEW3D_MAX_VOXELS = 700_000_000
VIEW3D_MAX_AXIS = 2048


def level_for_3d(levels, max_voxels=VIEW3D_MAX_VOXELS, max_axis=VIEW3D_MAX_AXIS):
    """Finest pyramid level that will render as a single 3D texture."""
    for i, arr in enumerate(levels):
        shape = tuple(arr.shape)
        if np.prod(shape, dtype=np.int64) <= max_voxels and max(shape) <= max_axis:
            return i
    return len(levels) - 1


#: A pinned 3D level larger than this is read in the background, and the
#: finest level within it is shown until it arrives. The pinned levels of
#: the EM stains hold 254-612 M voxels and take 0.4-1.0 s to read -- most of
#: what opening one of them in 3D cost -- while their next levels, 32-76 M,
#: take about 0.1 s.
VIEW3D_WAIT_VOXELS = 100_000_000


def coarse_level_for_3d(levels, level: int, max_voxels=VIEW3D_WAIT_VOXELS) -> int:
    """The level 3D shows while `level` is read: the finest within `max_voxels`.

    `level` itself when it is that small already.
    """
    for i in range(level, len(levels)):
        if np.prod(tuple(levels[i].shape), dtype=np.int64) <= max_voxels:
            return i
    return len(levels) - 1


class FineLevel:
    """The pyramid level an image is pinned to in 3D, read off the UI thread.

    napari reads a pinned level whole, on the UI thread, through dask: the
    finest one that fits a texture is a 0.4-1.0 s stall in the EM spaces,
    on every entry into 3D. So 3D is first pinned to a coarser level, the
    fine one is read in a thread straight from its chunk files, by the
    reader 2D uses (`chunkcache`), and swapped in when it arrives.
    Both are kept for the layer's life, so the next entry into 3D pins the
    fine one at once; the price is their memory, 0.3-0.7 GB, which 3D held
    anyway. While the fine one is read, the UI thread shares the chunk
    reader's threads and the interpreter with it: the read hands the pool a
    batch of chunks at a time, so a chunk the UI thread needs meanwhile
    waits behind one batch, not behind the level (`chunkcache.read_whole`).

    A daemon thread, polled from the UI thread, rather than a Qt worker:
    the thread only stores its result, so no Qt object is touched off the
    UI thread. A read still running when the process exits decodes the
    batch it has queued, a few milliseconds, and is then dropped.
    A Qt pool worker is waited for when the application object is
    destroyed, which happens with the interpreter lock held, and a worker
    needing that lock to finish hung the process at exit.
    """

    #: How often the UI thread looks for the result, in milliseconds.
    POLL_MS = 30

    def __init__(self, viewer, layer, level: int, coarse: int, sources) -> None:
        self._layer = weakref.ref(layer)
        self.level = level
        self.coarse = coarse
        #: The layer's levels as it was given them, read whole by the chunk
        #: reader 2D uses (`chunkcache.read_whole`), which keeps none of it.
        self._sources = sources
        #: The level's voxels, once read and swapped in.
        self.array = None
        self._coarse_in = False
        self._thread = None
        self._result = None
        self._timer = None
        self._three_d = False
        self._stopped = False
        #: Set to end the read at its next batch of chunks.
        self._stop = threading.Event()
        # A scene torn down, or a viewer closed, removes the layer: the read
        # stops there, rather than swap a level into a layer nothing shows.
        self._removed = viewer.layers.events.removed
        self._removed.connect(self._on_removed)

    def pin(self, three_d: bool) -> None:
        """Pin the level 3D renders, reading the fine one if it is not in yet."""
        layer = self._layer()
        if layer is None:
            return
        self._three_d = three_d
        if not three_d:
            layer.locked_data_level = None
            return
        if self.array is not None or self._stopped:
            layer.locked_data_level = self.level
            return
        if not self._coarse_in:
            # The coarse level is read now, and also by the chunk reader.
            self._coarse_in = True
            self._swap_in(layer, self.coarse, read_whole(self._sources[self.coarse]))
        layer.locked_data_level = self.coarse
        if self._thread is None:
            self._start()

    @staticmethod
    def _swap_in(layer, level: int, array) -> None:
        """Hand napari the voxels of one level from memory. Releases the lock.

        As the numpy array itself, not wrapped in dask: napari slices it as
        views, while dask hashed all of it for a name and then copied it
        twice, 0.5 s of the UI thread for the male CNS level. Unlike a store
        read eagerly, an array already in memory costs nothing to slice.
        """
        levels = list(layer.data)
        levels[level] = array
        layer.data = levels

    def _start(self) -> None:
        from qtpy.QtCore import QTimer

        source = self._sources[self.level]

        def read() -> None:
            try:
                self._result = ("ok", read_whole(source, stop=self._stop))
            except Exception as exc:              # noqa: BLE001 - reported below
                self._result = ("failed", exc)

        self._thread = threading.Thread(target=read, name="lobemap-3d-level",
                                        daemon=True)
        self._timer = QTimer()
        self._timer.setInterval(self.POLL_MS)
        self._timer.timeout.connect(self._poll)
        self._thread.start()
        self._timer.start()

    def _on_removed(self, event=None) -> None:
        if getattr(event, "value", None) is self._layer():
            self.stop()

    def stop(self) -> None:
        """End a read still running, for good: its layer is gone or going."""
        self._stopped = True
        self._stop.set()
        if self._timer is not None:
            self._timer.stop()
        with contextlib.suppress(Exception):          # already disconnected
            self._removed.disconnect(self._on_removed)

    def _poll(self) -> None:
        result = self._result
        if result is None:
            return
        self._timer.stop()
        self._result = None
        layer = self._layer()
        if layer is None or self._stopped:
            return
        status, value = result
        if status != "ok":
            # Pin the fine level after all, the way it always was pinned.
            self._stopped = True
            if self._three_d:
                layer.locked_data_level = self.level
            return
        try:
            self._swap_in(layer, self.level, value)
            if self._three_d:
                layer.locked_data_level = self.level
        except Exception as exc:                  # noqa: BLE001 - a timer slot
            # A layer whose viewer has gone; never worth a crash.
            self._stopped = True
            warnings.warn(f"3D level not swapped in: {exc!r}", RuntimeWarning,
                          stacklevel=1)
            return
        self.array = value


#: Each multiscale image layer's `FineLevel`, if its 3D level is read late.
_FINE: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()


def pin_level(layer, three_d: bool) -> None:
    """Pin an image's pyramid in 3D, or release it for zoom-driven 2D.

    napari's own choice in 3D is the coarsest level; `level_for_3d` picks
    the finest one that fits a texture, and a large one is read in the
    background (`FineLevel`). Labels carry no pyramid and are left alone.
    """
    info = layer.metadata.get("lobemap", {})
    if "level_3d" not in info:
        return
    fine = _FINE.get(layer)
    if fine is not None:
        fine.pin(three_d)
    else:
        layer.locked_data_level = info["level_3d"] if three_d else None


def stop_levels(layers) -> None:
    """Drop any background level read of these layers."""
    for layer in layers:
        fine = _FINE.get(layer)
        if fine is not None:
            fine.stop()


def default_colormap(role: str) -> str:
    return ROLE_COLORMAP.get(role, DEFAULT_COLORMAP)


def add_images(viewer, registry, space: str) -> list:
    """Reference images: the LM template, and the virtual synapse stain.

    scale and translate come from the Volume itself, so the image sits in the
    same micrometer world as the meshes. Getting either wrong yields a
    plausible picture that is simply in the wrong place, which is why the
    stain has its own alignment validator.

    Every layer is added hidden, with the visibility it opens with recorded
    in its metadata; `show_images` applies it. napari does not slice a
    hidden layer, so a scene that first moves the plane onto its atlas (2D)
    or pins the pyramid level (3D) reads the image once, where it ends up,
    rather than once where napari put the slider and again there.
    """
    layers = []
    for asset in registry.assets_in_space(space):
        if asset.kind not in ("image", "labels") or not asset.path.exists():
            continue
        volume = registry.volume(asset.id)

        if asset.kind == "labels":
            # A segmentation, not an intensity image: napari colors it by id
            # and picks values rather than interpolating them, so none of the
            # colormap/gamma/rendering defaults apply.
            layer = viewer.add_labels(
                np.asarray(volume.data),
                name=asset.id,
                visible=False,
                opacity=0.6,
                **volume.napari_kwargs(),
            )
            keep_extent_while_slicing(layer)
            layer.metadata["lobemap"] = {
                "kind": "labels",
                "asset": asset.id,
                "role": asset.role,
                # Off, unlike the images below: this is a segmentation of
                # the same glomeruli the meshes already draw, so showing
                # both by default draws each one twice.
                "opens_visible": False,
                # Written at ingest: voxel value -> the name the matching
                # mesh carries, which is what lets the two be colored alike.
                "label_names": {
                    int(k): v
                    for k, v in (volume.meta.get("label_names") or {}).items()
                },
            }
            layers.append(layer)
            continue

        # A pyramid is read through a cache of decoded chunks, so a slice
        # step decodes nothing the step before it already did; see chunkcache.
        data = cached_levels(volume.levels) if volume.is_multiscale else volume.napari_data()
        layer = viewer.add_image(
            data,
            multiscale=volume.is_multiscale,
            name=asset.id,
            visible=False,
            **display_for(asset.role, asset.colormap, asset.display),
            **volume.napari_kwargs(),
        )
        keep_extent_while_slicing(layer)
        level = level_for_3d(data) if volume.is_multiscale else 0
        if volume.is_multiscale:
            coarse = coarse_level_for_3d(data, level)
            if coarse != level:
                # Read by the same chunk reader as 2D, without caching:
                # FineLevel keeps both levels itself.
                _FINE[layer] = FineLevel(viewer, layer, level, coarse, data)
        layer.metadata["lobemap"] = {
            "kind": "image",
            "asset": asset.id,
            "role": asset.role,
            "level_3d": level,
            # Visible if it is here at all. These are backdrops -- the
            # confocal channel, the synapse-density stain -- and a scene
            # reads as incomplete without one. They used to be created
            # hidden and turned on again by every default scene preset,
            # so the default only ever applied to a scene that forgot to
            # mention its own image: `hemibrain_three_ways` opened with
            # the stain off for no reason anyone chose. A preset that
            # wants one off can still say `visible = false`.
            #
            # Nothing here is conditional on the asset being built: this
            # loop skips what is not on disk, so an absent stain is an
            # absent layer rather than an invisible one.
            "opens_visible": True,
        }
        layers.append(layer)
    return layers


def show_images(layers) -> None:
    """Give each layer from `add_images` the visibility it opens with."""
    for layer in layers:
        if layer.metadata.get("lobemap", {}).get("opens_visible"):
            layer.visible = True


__all__ = [
    "BASE_DISPLAY",
    "DEFAULT_COLORMAP",
    "ROLE_DISPLAY",
    "VIEW3D_MAX_AXIS",
    "VIEW3D_MAX_VOXELS",
    "VIEW3D_WAIT_VOXELS",
    "FineLevel",
    "add_images",
    "coarse_level_for_3d",
    "default_colormap",
    "display_for",
    "level_for_3d",
    "pin_level",
    "show_images",
    "stop_levels",
]
