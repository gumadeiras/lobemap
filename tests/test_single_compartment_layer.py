"""A one-compartment mesh must not take the viewer down.

A reference shell with exactly one compartment makes a Surface layer from a
single color. vispy's GLSL step generator asserts `ncolors >= 2`, and the
resulting AssertionError surfaces deep inside vispy with nothing pointing
back at the mesh that caused it. The registry has no such asset today --
`bates2020_brain` had one compartment and has been superseded -- so this is
tested synthetically rather than against the catalog.
"""

from __future__ import annotations

import numpy as np
import pytest

from lobemap.viewer.layers import (
    categorical_colors,
    contrast_limits_for,
    step_colormap,
)


@pytest.mark.parametrize("n", [1, 2, 3, 58, 116])
def test_step_colormap_is_usable_by_vispy(n):
    from napari.utils.colormaps.colormap_utils import _napari_cmap_to_vispy

    cmap = step_colormap(categorical_colors(n))
    # The real assertion lives in vispy; call the same path napari does.
    vispy_cmap = _napari_cmap_to_vispy(cmap)
    assert vispy_cmap is not None
    assert len(cmap.colors) >= 2
    assert len(cmap.controls) == len(cmap.colors) + 1


def test_single_color_is_duplicated_not_invented():
    colors = categorical_colors(1)
    cmap = step_colormap(colors)
    assert len(cmap.colors) == 2
    assert np.allclose(cmap.colors[0], cmap.colors[1])
    assert np.allclose(cmap.colors[0], colors[0])


def test_contrast_limits_still_center_the_single_bin():
    """Duplicating the color must not shift where value 0 lands."""
    lo, hi = contrast_limits_for(1)
    assert lo == -0.5 and hi == 0.5
    cmap = step_colormap(categorical_colors(1))
    # Value 0 maps to the middle of the range, which is inside both bins --
    # and both bins are the same color, so the result is unambiguous.
    assert np.allclose(cmap.map(np.array([0.5]))[0], categorical_colors(1)[0])
