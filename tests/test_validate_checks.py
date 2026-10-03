"""The validation checks, each shown to fail on the mistake it exists for.

Synthetic data throughout: nothing here needs the published assets, the
network or navis. `test_check_real_data.py` runs the same checks on the
shipped data.
"""

from __future__ import annotations

import numpy as np
import pytest

from lobemap.core.imagefmt import Volume
from lobemap.core.meshfmt import MeshSet
from lobemap.core.model import Space
from lobemap.core.registry import Registry
from lobemap.validate import geometry as G
from lobemap.validate import harness as H
from lobemap.validate import images as GI
from lobemap.validate import laterality as GL

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


# -- laterality and chirality (SCI-3) -----------------------------------

#: Identity rotation: A = +x, D = +y, and +z the fly's right (biological).
BIOLOGICAL = Space("S", "S", "um", "T", "biological", "+x", 0.0)


def _lobe(side: str, z: float):
    """Twelve glomeruli whose names encode their position, as real ones do."""
    parts = []
    for k, (letters, x, y) in enumerate(
        [("DA", 10, 10), ("VP", -10, -10), ("DP", -10, 10), ("VA", 10, -10)]
    ):
        for n in range(3):
            parts.append((f"{letters}{n + 1}({side})", (x, y + 3 * n, z + 3 * k), 3))
    return parts


def _brain(flip_z=False, swap_labels=False):
    """Two lobes and an asymmetric body larger on the fly's right (+z)."""
    glom = meshset(_lobe("L", -50) + _lobe("R", 50))
    npl = meshset([("AL(L)", (0, 0, -50), 40), ("AL(R)", (0, 0, 50), 40),
                   ("AB(L)", (0, -40, -5), 3), ("AB(R)", (0, -40, 5), 6)])
    if flip_z:
        glom = glom.transformed(glom.vertices * np.array([1, 1, -1]))
        npl = npl.transformed(npl.vertices * np.array([1, 1, -1]))
    if swap_labels:
        def swap(name):
            return name.replace("(L)", "(x)").replace("(R)", "(L)").replace("(x)", "(R)")
        glom = MeshSet(glom.vertices, glom.faces, glom.vertex_offsets,
                       glom.face_offsets, [swap(n) for n in glom.names], {})
        npl = MeshSet(npl.vertices, npl.faces, npl.vertex_offsets,
                      npl.face_offsets, [swap(n) for n in npl.names], {})
    return glom, npl


def test_a_correct_brain_passes_both_left_right_checks():
    glom, npl = _brain()
    assert GL.check_lateral_sides(BIOLOGICAL, [("g", glom), ("n", npl)]).passed
    chk = GL.check_chirality(BIOLOGICAL, glom, npl)
    assert chk.passed, chk.detail
    assert "det[A, D, R] +" in chk.detail


def test_a_whole_space_reflection_fails_both():
    """Every other check is symmetric and passes this; these two may not."""
    glom, npl = _brain(flip_z=True)
    sides = GL.check_lateral_sides(BIOLOGICAL, [("g", glom), ("n", npl)])
    assert not sides.passed
    assert len(sides.offenders) == 12 + 2
    chk = GL.check_chirality(BIOLOGICAL, glom, npl)
    assert not chk.passed and "det[A, D, R] -" in chk.detail


def test_swapped_side_labels_are_caught_by_the_asymmetric_body():
    glom, npl = _brain(swap_labels=True)
    assert not GL.check_lateral_sides(BIOLOGICAL, [("g", glom), ("n", npl)]).passed
    chk = GL.check_chirality(BIOLOGICAL, glom, npl)
    assert not chk.passed and "labels are swapped" in chk.detail


def test_a_mirrored_space_expects_the_other_handedness():
    """FAFB's image is left-right inverted, so its real data has det -1."""
    mirrored = Space("S", "S", "um", "T", "mirrored", "+x", 0.0)
    glom, npl = _brain(flip_z=True)
    assert GL.check_chirality(mirrored, glom, npl).passed


def test_no_asymmetric_body_means_no_chirality_check():
    glom, _ = _brain()
    assert GL.check_chirality(BIOLOGICAL, glom, meshset([("AL(L)", (0, 0, 0), 5)])) is None


# -- compartment size floor (SCI-3, SCI-4) --------------------------------


def _atlas_with(sizes):
    return meshset([(f"G{i}", (30 * i, 0, 0), s) for i, s in enumerate(sizes)])


def test_a_collapsed_compartment_fails_the_size_floor():
    ms = _atlas_with([10] * 9 + [10])
    v = ms.vertices.copy()
    last = slice(int(ms.vertex_offsets[-2]), int(ms.vertex_offsets[-1]))
    v[last, 2] = v[last, 2].mean()          # flattened into a plane
    flat = ms.transformed(v)
    assert G.check_scale(flat).passed, "the median check cannot see one bad mesh"
    chk = G.check_compartment_sizes(flat)
    assert not chk.passed
    assert chk.offenders == ["G9 (0 um3)"]


def test_a_known_defect_is_listed_without_failing():
    ms = _atlas_with([10] * 9 + [1])
    chk = G.check_compartment_sizes(ms, known={"G9": "fragment in the source"})
    assert chk.passed
    assert chk.offenders == ["G9 (1 um3, known: fragment in the source)"]
    assert "1 of them known" in chk.detail


def test_known_defects_are_read_from_the_registry(tmp_path):
    (tmp_path / "checks.toml").write_text(
        '[known_defects.atlas."VM2(R)"]\ncheck = "compartment size"\nreason = "tiny"\n'
    )
    assert H.known_defects(tmp_path) == {"atlas": {"VM2(R)": "tiny"}}
    assert H.known_defects(tmp_path / "nowhere") == {}


# -- image orientation (SCI-3) ------------------------------------------


def _stain_and_shell():
    """A 'stain' bright exactly inside a lopsided pair of shells."""
    shape = (60, 40, 40)
    data = np.zeros(shape, dtype=np.uint8)
    data[5:20, 10:30, 10:30] = 200          # big lobe, near the low-x edge
    data[35:45, 15:25, 15:25] = 200         # small lobe
    shell = meshset([("AL(L)", (12.0, 20.0, 20.0), 15), ("AL(R)", (40.0, 20.0, 20.0), 10)])
    return Volume(data=data, voxel_um=(1.0, 1.0, 1.0)), shell


def test_a_flipped_stain_fails_orientation():
    """The contrast checks pass a flipped stain; orientation may not."""
    volume, shell = _stain_and_shell()
    flipped = Volume(data=np.flip(volume.data, axis=0).copy(), voxel_um=volume.voxel_um)
    samples = GI.shell_samples(volume, shell, n_samples=4000)

    assert GI.check_image_orientation(volume, samples, axis=0).passed
    assert GI.check_image_inside_shell(flipped, shell, samples=samples).passed
    assert not GI.check_image_orientation(flipped, samples, axis=0).passed


def test_mirrored_sampling_reads_like_np_flip():
    volume, _ = _stain_and_shell()
    points = np.random.default_rng(0).uniform((0, 0, 0), (59, 39, 39), size=(500, 3))
    flipped = Volume(data=np.flip(volume.data, axis=0).copy(), voxel_um=volume.voxel_um)
    mirrored = GI.mirror_points(points, volume, axis=0)
    assert np.array_equal(volume.sample(mirrored), flipped.sample(points))


# -- label containment (SCI-3: GRABE has no shell) ----------------------


def test_meshes_must_sit_on_their_own_labels():
    data = np.zeros((40, 20, 20), dtype=np.uint8)
    data[2:12, 5:15, 5:15] = 1
    data[28:38, 5:15, 5:15] = 2
    labels = Volume(data=data, voxel_um=(1.0, 1.0, 1.0),
                    meta={"label_names": {"1": "DA1(L)", "2": "DA1(R)"}})
    right = meshset([("DA1(L)", (6.5, 9.5, 9.5), 6), ("DA1(R)", (32.5, 9.5, 9.5), 6)])
    swapped = meshset([("DA1(R)", (6.5, 9.5, 9.5), 6), ("DA1(L)", (32.5, 9.5, 9.5), 6)])

    assert GI.check_label_containment(right, labels).passed
    bad = GI.check_label_containment(swapped, labels)
    assert not bad.passed and len(bad.offenders) == 2
    assert GI.check_label_containment(right, Volume(data=data, voxel_um=(1, 1, 1))) is None
