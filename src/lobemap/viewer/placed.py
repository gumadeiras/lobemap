"""An image of yours in a scene: drawn where its placement puts it, in 3D and
in Slice view, mirrored and turned with the brain.

Its placement is one matrix (`core.placement`), from its voxels to the
space's micrometers, and may turn it any way, so its voxel grid is at any
angle to the space's. napari draws such an image in 3D, but slices an
image only along its own grid: in 2D it showed the plane of the image's
grid nearest the section, not the section. So each channel is drawn by two
layers, as each atlas is (`scene`): its voxels with the placement in 3D,
and in Slice view a `PlacedVolume`, the image resampled on demand on a grid
square to the space. The second is one of the scene's images: the mirror
puts it on `affine`, a turn of the view in the plane turns it, and an
oblique section resamples it (`turned`) as it does the brain's own images.

The first carries the placement on its `affine`, with the mirror composed
in front of it (`set_mirror`): so it stays out of the scene's images, whose
`affine` is the mirror's alone.

Each layer is hidden in the mode that does not draw it, before napari
slices for the new mode (`_follow_mode`): napari would read a slice layer
whole for 3D, and slice the 3D layer along its tilted grid for 2D.
"""

from __future__ import annotations

import contextlib
import weakref

import numpy as np

from ..core.placement import apply, corners
from . import napari_private
from .view import mirror_matrix

#: The display settings of a channel's two layers that are one setting: a
#: contrast set in 3D holds in Slice view.
LINKED = ("contrast_limits", "colormap", "gamma", "opacity", "blending")

#: Colormaps of an image's channels, in order.
CHANNEL_COLORMAPS = ("green", "magenta", "cyan", "yellow")

#: A slice layer's name, and a 3D layer's: the image's name, and what it draws.
SLICE_NAME = "{} · slice"
VOLUME_NAME = "{} · 3D"


class PlacedVolume:
    """An image resampled, on demand, on a grid square to the space.

    The grid's step is `step` micrometers along each axis, its first voxel
    at `translate`, and it holds the box the placed image fills. A read
    samples the image trilinearly at the grid's voxels, so napari reading
    one plane samples one plane. Indexing with slices alone returns another
    lazy view, as `chunkcache.CachedLevel` does; an integer, or
    `np.asarray`, reads. A turned view samples the image itself (`resampled`).
    """

    def __init__(self, source: np.ndarray, matrix, step: float, box=None,
                 _grid=None) -> None:
        self.source = source
        self.step = float(step)
        if _grid is None:
            placed = apply(matrix, corners(source.shape))
            lo, hi = placed.min(axis=0), placed.max(axis=0)
            origin = np.floor(lo / self.step) * self.step
            size = np.floor((hi - origin) / self.step + 1e-9).astype(int) + 1
            inverse = np.linalg.inv(np.asarray(matrix, float))
            # Grid voxel g is the space point origin + step g, which is the
            # image's voxel inverse @ that.
            linear = inverse[:3, :3] * self.step
            offset = inverse[:3, :3] @ origin + inverse[:3, 3]
            _grid = (origin, tuple(int(n) for n in size), linear, offset)
        self._grid = _grid
        self.translate = np.asarray(_grid[0], float)
        self.scale = np.full(3, self.step)
        full = tuple((0, n) for n in _grid[1])
        self._box = full if box is None else box
        self.shape = tuple(b - a for a, b in self._box)
        self.dtype = np.dtype(source.dtype)

    @property
    def ndim(self) -> int:
        return 3

    @property
    def resampled(self) -> tuple:
        """(image, linear, offset): voxel `linear @ g + offset` of the image is
        the grid's voxel `g`, which a turned view samples it at
        (`resample.TurnedImage`)."""
        _origin, _size, linear, offset = self._grid
        return self.source, linear, offset

    @property
    def size(self) -> int:
        return int(np.prod(self.shape, dtype=np.int64))

    @property
    def nbytes(self) -> int:
        return self.size * self.dtype.itemsize

    def __repr__(self) -> str:
        return f"PlacedVolume(shape={self.shape}, dtype={self.dtype}, step={self.step})"

    def __array__(self, dtype=None, copy=None):
        out = self._read(*(np.array(v) for v in zip(*self._box, strict=True)))
        return out if dtype is None else out.astype(dtype, copy=False)

    def __getitem__(self, key):
        from .chunkcache import _box

        box = _box(key, self.shape)
        if box is None:
            return np.asarray(self)[key]
        origin = [a for a, _ in self._box]
        if all(not is_int and step == 1 for _, _, step, is_int in box):
            return PlacedVolume(self.source, None, self.step, tuple(
                (o + start, o + stop) for o, (start, stop, _, _) in zip(origin, box, strict=True)),
                self._grid)
        lo = np.array([o + b[0] for o, b in zip(origin, box, strict=True)])
        hi = np.array([o + b[1] for o, b in zip(origin, box, strict=True)])
        block = self._read(lo, hi)
        return block[tuple(0 if b[3] else slice(None, None, b[2]) for b in box)]

    def _read(self, lo, hi) -> np.ndarray:
        """The box [lo, hi) of the whole grid, sampled from the image."""
        from scipy.ndimage import affine_transform

        lo, hi = np.asarray(lo, int), np.asarray(hi, int)
        shape = tuple(int(n) for n in np.maximum(hi - lo, 0))
        out = np.zeros(shape, self.dtype)
        if not all(shape):
            return out
        _origin, _size, linear, offset = self._grid
        affine_transform(self.source, linear, offset=offset + linear @ lo, output=out,
                         order=1, mode="constant", cval=0, prefilter=False)
        return out


def grid_step(matrix) -> float:
    """The slice grid's step: the image's finest voxel, as placed."""
    return float(np.linalg.norm(np.asarray(matrix, float)[:3, :3], axis=0).min())


class PlacedImage:
    """One image of yours as a scene draws it: two layers per channel.

    Made hidden, and shown by `set_visible`. `session.add_placed` puts it in
    the scene, and `session.drop_placed` takes it out again.
    """

    def __init__(self, viewer, name: str, channels, matrix, contrast,
                 colormaps=CHANNEL_COLORMAPS) -> None:
        from napari.experimental import link_layers
        from napari.layers import Image

        from .yours import leave_out

        self.viewer = viewer
        self.name = name
        self.channels = list(channels)
        self.matrix = np.asarray(matrix, float)
        #: The scene's mirror, as `set_mirror` was last given it.
        self._mirror = np.eye(4)
        self.visible = False
        #: Called after napari's eye showed or hid the image, so the Your
        #: data tab can follow it.
        self.listeners: list = []
        self._syncing = False
        self.volumes, self.slices = [], []
        step = grid_step(self.matrix)
        for k, data in enumerate(self.channels):
            suffix = f" ({k + 1})" if len(self.channels) > 1 else ""
            settings = {"colormap": colormaps[k % len(colormaps)],
                        "contrast_limits": contrast[k], "blending": "additive",
                        "visible": False}
            volume = Image(data, name=VOLUME_NAME.format(name + suffix),
                           affine=self.matrix, rendering="mip", **settings)
            grid = PlacedVolume(data, self.matrix, step)
            plane = Image(grid, name=SLICE_NAME.format(name + suffix), scale=grid.scale,
                          translate=grid.translate, multiscale=False, **settings)
            # Out of the sliders before napari adds them (`yours.leave_out`).
            leave_out(viewer, (volume, plane))
            for layer in (volume, plane):
                viewer.add_layer(layer)
                layer.metadata["lobemap"] = {"kind": "image", "yours": name}
                napari_private.keep_extent_while_slicing(layer)
                layer.events.visible.connect(self._on_eye)
            napari_private.keep_volume_texture(viewer, volume)
            link_layers([volume, plane], LINKED)
            self.volumes.append(volume)
            self.slices.append(plane)
        _follow_mode(viewer, self)

    @property
    def layers(self) -> list:
        """Every layer, each channel's 3D layer and then its slice layer."""
        return [layer for pair in zip(self.volumes, self.slices, strict=True)
                for layer in pair]

    def _drawn(self) -> list:
        return self.volumes if self.viewer.dims.ndisplay == 3 else self.slices

    def place(self, matrix) -> None:
        """Put the image where `matrix` places it: unturned, as a turned view
        wants it changed (`turned.TurnedView.moved`)."""
        self.matrix = np.asarray(matrix, float)
        step = grid_step(self.matrix)
        for volume, plane, data in zip(self.volumes, self.slices, self.channels,
                                       strict=True):
            volume.affine = self._mirror @ self.matrix
            grid = PlacedVolume(data, self.matrix, step)
            with napari_private.shown_unsliced(plane):
                plane.data = grid
                plane.scale = grid.scale
                plane.translate = grid.translate
            napari_private.clear_extent(plane)
            napari_private.slice_now(self.viewer, plane)

    def set_mirror(self, axis: int | None, center: float = 0.0) -> None:
        """Reflect the 3D layers with the scene; the slice layers are the
        scene's images, which the scene reflects on their `affine`."""
        self._mirror = np.eye(4) if axis is None else mirror_matrix(3, center, axis)
        for volume in self.volumes:
            volume.affine = self._mirror @ self.matrix

    def set_visible(self, on: bool) -> None:
        """Show the image in the layers the mode draws, or hide it."""
        self.visible = bool(on)
        self.sync()

    def sync(self) -> None:
        """The layers the mode draws are shown with the image; the others hidden."""
        drawn = self._drawn()
        self._syncing = True
        try:
            for layer in self.layers:
                want = self.visible and layer in drawn
                if layer.visible != want:
                    layer.visible = want
        finally:
            self._syncing = False

    def hide_undrawn(self) -> None:
        """Hide what the new mode does not draw, before napari slices for it."""
        drawn = self._drawn()
        self._syncing = True
        try:
            for layer in self.layers:
                if layer.visible and layer not in drawn and layer in self.viewer.layers:
                    with napari_private.no_scene_update(self.viewer, layer):
                        layer.visible = False
        finally:
            self._syncing = False

    def _on_eye(self, event=None) -> None:
        """napari's eye, read as the image's own show or hide.

        The eye of a layer the mode draws shows or hides the image; the eye
        of one it does not draw is put back, as an atlas's is.
        """
        if self._syncing:
            return
        layer = getattr(event, "source", None)
        if layer in self._drawn():
            self.visible = bool(layer.visible)
            for listener in list(self.listeners):
                listener()
        self.sync()

    def stop(self) -> None:
        """The image is leaving the scene: stop following the mode."""
        _MODES.get(self.viewer, weakref.WeakSet()).discard(self)


#: Each viewer's placed images, held weakly; see `_follow_mode`.
_MODES: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()


def _follow_mode(viewer, image: PlacedImage) -> None:
    """Keep `image` drawn by the layers the mode draws, from now on.

    Before napari slices for a new mode its other layers are hidden
    (`napari_private.before_slicing`), and once the mode is set the ones it
    draws are shown. Installed once per viewer; the images are held weakly.
    """
    images = _MODES.get(viewer)
    if images is None:
        images = _MODES[viewer] = weakref.WeakSet()
        ref = weakref.ref(viewer)
        mode = [viewer.dims.ndisplay]

        def _before() -> None:
            live = ref()
            if live is None or live.dims.ndisplay == mode[0]:
                return
            mode[0] = live.dims.ndisplay
            for each in list(images):
                with contextlib.suppress(Exception):
                    each.hide_undrawn()

        def _after(event=None) -> None:
            for each in list(images):
                with contextlib.suppress(Exception):
                    each.sync()

        napari_private.before_slicing(viewer, _before)
        viewer.dims.events.ndisplay.connect(_after)
    images.add(image)


__all__ = [
    "CHANNEL_COLORMAPS",
    "LINKED",
    "SLICE_NAME",
    "VOLUME_NAME",
    "PlacedImage",
    "PlacedVolume",
    "grid_step",
]
