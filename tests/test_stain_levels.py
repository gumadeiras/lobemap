"""In 2D, the stain level napari picks by zoom is drawn from the store's voxels.

Checked on the arrays napari hands to vispy, against the store read
directly, so a cache that served the wrong chunk or the wrong level fails.
3D's levels are checked in `test_deferred_parts.py`.
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


def test_2d_zoom_picks_a_finer_level_and_draws_its_tile(monkeypatch):
    with launched(monkeypatch, "view", "FAFB14", "--ndisplay", "2") as (code, viewer):
        layer = _stain(viewer)
        assert layer.locked_data_level is None
        _draw(viewer)
        before = layer.data_level
        viewer.scene.camera.zoom *= 8
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
