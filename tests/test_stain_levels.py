"""Which pyramid level of the stain is drawn, and that it is the store's.

3D pins the finest level that fits a texture; 2D lets napari pick by zoom.
Checked on the arrays napari hands to vispy, against the store read
directly, so a cache that served the wrong chunk or the wrong level fails.
"""

from __future__ import annotations

import numpy as np
import pytest
from viewer_harness import launched, pump

pytestmark = [pytest.mark.requires_data, pytest.mark.requires_data("fafb_stain")]
pytest.importorskip("napari")


def _stain(viewer):
    return next(layer for layer in viewer.layers
                if layer.metadata.get("lobemap", {}).get("asset") == "fafb_stain")


def _store(asset="fafb_stain"):
    from viewer_harness import data_root

    from lobemap.core.zarrfmt import load_zarr

    return load_zarr(data_root() / f"{asset}.zarr").levels


def _draw(viewer) -> None:
    """What a visible canvas does on every frame: napari re-picks the level."""
    viewer.window._qt_viewer.canvas.on_draw()
    pump()


def test_3d_draws_the_pinned_level_whole(monkeypatch):
    with launched(monkeypatch, "view", "FAFB14") as (code, viewer):
        assert code == 0
        layer = _stain(viewer)
        pinned = layer.metadata["lobemap"]["level_3d"]
        assert layer.locked_data_level == pinned == 1
        shown = np.asarray(layer._slice.image.raw)
        level = _store()[pinned]
        assert shown.shape == tuple(level.shape)
        k = level.shape[2] // 2
        assert np.array_equal(shown[:, :, k], np.asarray(level[:, :, k]))


def test_2d_zoom_picks_a_finer_level_and_draws_its_tile(monkeypatch):
    with launched(monkeypatch, "view", "FAFB14", "--ndisplay", "2") as (code, viewer):
        layer = _stain(viewer)
        assert layer.locked_data_level is None
        _draw(viewer)
        before = layer.data_level
        viewer.camera.zoom *= 8
        _draw(viewer)
        assert layer.data_level < before
        _assert_shows_store_tile(viewer, layer)
        axis = int(viewer.dims.order[0])
        viewer.dims.set_current_step(axis, viewer.dims.current_step[axis] + 3)
        pump()
        _assert_shows_store_tile(viewer, layer)


def _assert_shows_store_tile(viewer, layer) -> None:
    level = layer.data_level
    arr = _store()[level]
    axis = int(viewer.dims.order[0])
    corners = layer.corner_pixels
    region = [slice(corners[0, d], corners[1, d] + 1) for d in range(3)]
    k = layer._data_slice.point[axis] / layer.downsample_factors[level][axis]
    region[axis] = int(np.round(k))
    want = np.asarray(arr[tuple(region)])
    displayed = list(layer._slice_input.displayed)
    if displayed != sorted(displayed):
        want = want.T
    assert np.array_equal(np.asarray(layer._slice.image.raw), want), level
