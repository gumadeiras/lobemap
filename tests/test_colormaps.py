"""Display defaults live with the role, not scattered through the viewer."""

from __future__ import annotations

from lobemap.core.model import Asset
from lobemap.viewer.app import default_colormap


def test_stain_defaults_to_magenta():
    assert default_colormap("virtual_stain") == "gray"
    assert default_colormap("template_image") == "gray"
    assert default_colormap("anything_else") == "magma"


def test_magenta_is_a_real_napari_colormap():
    from napari.utils.colormaps import AVAILABLE_COLORMAPS

    for role in ("virtual_stain", "template_image", "other"):
        assert default_colormap(role) in AVAILABLE_COLORMAPS


def test_asset_can_override_the_role_default(tmp_path):
    a = Asset(id="x", role="virtual_stain", space="S", kind="image",
              path=tmp_path / "x.npz", colormap="cyan")
    assert (a.colormap or default_colormap(a.role)) == "cyan"
    b = Asset(id="y", role="virtual_stain", space="S", kind="image",
              path=tmp_path / "y.npz")
    assert (b.colormap or default_colormap(b.role)) == "gray"
