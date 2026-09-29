"""Validation checks, each shown to fail on the mistake it exists for.

Synthetic data throughout: nothing here needs the published assets, the
network or navis.
"""

from __future__ import annotations

import numpy as np
import pytest

from lobemap.core.meshfmt import MeshSet
from lobemap.core.registry import Registry
from lobemap.validate import geometry as G
from lobemap.validate import harness as H

trimesh = pytest.importorskip("trimesh")


def box(center, size=8.0):
    m = trimesh.creation.box(extents=(size, size, size))
    return np.asarray(m.vertices) + np.asarray(center, float), np.asarray(m.faces)


def meshset(parts):
    return MeshSet.from_parts([(name, *box(c, s)) for name, c, s in parts])


# -- correspondence by canonical name (SCI-1) ---------------------------


def test_correspondence_pairs_the_rename_chain_by_canonical_name():
    """hemibrain VC3l/VC3m/VC5 are S12 VC3/VC5/VM6, and must pair that way.

    Each hemibrain glomerulus sits on its renamed S12 counterpart, and the
    same-spelled S12 glomerulus is 30 um away -- as S12 VC5 is from
    hemibrain VC5(R), which is VM6.
    """
    hemibrain = meshset([("VC3l(R)", (0, 0, 0), 8), ("VC3m(R)", (30, 0, 0), 8),
                         ("VC5(R)", (60, 0, 0), 8)])
    s12 = meshset([("VC3", (0, 0, 0), 8), ("VC5", (30, 0, 0), 8), ("VM6", (60, 0, 0), 8)])
    canonical = {"VC3l(R)": ("VC3",), "VC3m(R)": ("VC5",), "VC5(R)": ("VM6",)}

    pairs, chk = G.correspondence_report(
        hemibrain, s12, "hemibrain", "s12", b_side="R", a_canonical=canonical
    )
    assert chk.passed
    assert {(p.a_name, p.b_name) for p in pairs} == {
        ("VC3l(R)", "VC3"), ("VC3m(R)", "VC5"), ("VC5(R)", "VM6")
    }
    assert all(p.distance_um < 1e-6 for p in pairs)
    assert "0 only in hemibrain, 0 only in s12" in chk.detail


def test_a_split_is_compared_as_one_body():
    """S11's VM6l/VM6m/VM6v all carry VM6; together they face one VM6."""
    s11 = meshset([("VM6l", (-10, 0, 0), 4), ("VM6m", (0, 0, 0), 4), ("VM6v", (10, 0, 0), 4)])
    hemibrain = meshset([("VC5(R)", (0, 0, 0), 20)])
    pairs, _ = G.correspondence_report(
        s11, hemibrain, a_side="R",
        a_canonical={"VM6l": ("VM6",), "VM6m": ("VM6",), "VM6v": ("VM6",)},
        b_canonical={"VC5(R)": ("VM6",)},
    )
    assert len(pairs) == 1
    assert pairs[0].a_name == "VM6l+VM6m+VM6v"
    assert pairs[0].canonical == "VM6"
    assert pairs[0].distance_um == pytest.approx(0.0, abs=1e-5)


# -- biological alignment across conventions (SCI-2) --------------------


def _write_two_space_registry(root):
    """A mirrored space and a biological one, one atlas each.

    Both declare the identity rotation, so +z is the fly's right in BIO and
    its LEFT in MIR (see `anatomical_axes`). MIR's atlas is a left lobe, so
    it sits at +z; BIO has both lobes, its left at -z.
    """
    (root / "atlases").mkdir(parents=True)
    (root / "spaces.toml").write_text(
        '[MIR]\ntitle = "MIR"\nunits = "um"\nflybrains_template = "TMIR"\n'
        'lateral_convention = "mirrored"\n'
        'anatomical_rotation = { axis = "+x", degrees = 0.0 }\n'
        '[BIO]\ntitle = "BIO"\nunits = "um"\nflybrains_template = "TBIO"\n'
        'lateral_convention = "biological"\n'
        'anatomical_rotation = { axis = "+x", degrees = 0.0 }\n'
    )
    (root / "assets.toml").write_text(
        '[mir_glomeruli]\nrole = "glomeruli"\nspace = "MIR"\nkind = "meshset"\n'
        'side = "L"\npath = "data/mir.npz"\n'
        '[bio_glomeruli]\nrole = "glomeruli"\nspace = "BIO"\nkind = "meshset"\n'
        'side = "both"\npath = "data/bio.npz"\n'
    )
    for aid, space, asset in (("mir", "MIR", "mir_glomeruli"), ("bio", "BIO", "bio_glomeruli")):
        (root / "atlases" / f"{aid}.toml").write_text(
            f'id = "{aid}"\ntitle = "{aid}"\nnative_space = "{space}"\nasset = "{asset}"\n'
        )
    meshset([("DA1", (0, 0, 50), 8), ("DM6", (30, 0, 50), 8)]).save(root / "data" / "mir.npz")
    meshset([
        ("DA1(L)", (0, 0, -50), 8), ("DM6(L)", (30, 0, -50), 8),
        ("DA1(R)", (0, 0, 50), 8), ("DM6(R)", (30, 0, 50), 8),
    ]).save(root / "data" / "bio.npz")
    return Registry.load(root, data_root=root / "data")


@pytest.fixture
def fake_bridge(monkeypatch, tmp_path):
    """A bridge that keeps APPARENT side, as the real registrations do.

    Points pass through unchanged, so MIR's left lobe lands on BIO's right
    one; the mirror reflects z. Records every mirror it is asked for.
    """
    from lobemap.core import resolve as R
    from lobemap.core import spaces as sp

    mirrored: list[str] = []

    def mirror(points, template):
        mirrored.append(template)
        out = np.array(points, dtype=float, copy=True)
        out[:, 2] *= -1
        return out

    monkeypatch.setattr(R, "template_scale_to_um", lambda template: 1.0)
    monkeypatch.setattr(R, "cache_root", lambda: tmp_path / "cache")
    monkeypatch.setattr(sp, "bridge", lambda pts, s, t, allow_binary=None: (
        np.array(pts, dtype=float), {"path": [s, t], "classes": [], "n_warps": 0}))
    monkeypatch.setattr(sp, "mirror", mirror)
    monkeypatch.setattr(sp, "has_mirror_registration", lambda template: True)
    monkeypatch.setattr(sp, "choose_path", lambda s, t, allow_binary=None: {"path": [s, t]})
    monkeypatch.setattr(sp, "tool_versions", lambda: {"fake": "1"})
    return mirrored


def test_comparison_across_conventions_aligns_biology(tmp_path, fake_bridge):
    """Regression: without a mirror, MIR's left lobe met BIO's left 100 um away."""
    reg = _write_two_space_registry(tmp_path / "registry")
    pairs, chk = H.compare_atlases(reg, "bio", "mir", "BIO")
    assert fake_bridge == ["TMIR"], "the mirror must be applied, in the source space"
    assert chk.passed
    assert {(p.a_name, p.b_name) for p in pairs} == {("DA1(L)", "DA1"), ("DM6(L)", "DM6")}
    assert max(p.distance_um for p in pairs) == pytest.approx(0.0, abs=1e-5)


def test_alignment_without_a_mirror_registration_is_refused(tmp_path, fake_bridge, monkeypatch):
    from lobemap.core import spaces as sp

    monkeypatch.setattr(sp, "has_mirror_registration", lambda template: False)
    reg = _write_two_space_registry(tmp_path / "registry")
    with pytest.raises(ValueError, match="no mirror registration"):
        H.compare_atlases(reg, "bio", "mir", "BIO")
