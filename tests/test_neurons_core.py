"""Your neurons before any window: what names one, SWC files, thinning, tubes,
and the side of the brain they land on.

No network and no navis bridge is run: FlyWire's fetch is the ingest
extra's and the network's, and the bridge is `resolve`'s, tested there;
what is checked here is what is asked of them.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from lobemap.core import neurons as nr

ROOT = 720575940623636701


@pytest.mark.parametrize("text, root, version", [
    (str(ROOT), ROOT, nr.FLYWIRE_VERSION),
    (f" {ROOT}\n", ROOT, nr.FLYWIRE_VERSION),
    ((f"https://codex.flywire.ai/app/cell_details?data_version=630&root_id={ROOT}"
      "&dataset=fafb"), ROOT, 630),
    (f"https://codex.flywire.ai/app/cell_details?root_id={ROOT}", ROOT, nr.FLYWIRE_VERSION),
])
def test_a_root_id_or_a_codex_link_names_a_flywire_neuron(text, root, version):
    spec = nr.parse_spec(text)
    assert (spec.root_id, spec.version, spec.path) == (root, version, None)
    assert spec.name == str(root)


@pytest.mark.parametrize("text, words", [
    (f"https://codex.flywire.ai/app/cell_details?root_id={ROOT}&dataset=banc", "banc"),
    ("https://codex.flywire.ai/app/cell_details?data_version=783", "no root ID"),
    (f"https://codex.flywire.ai/app/cell_details?root_id={ROOT}&data_version=x",
     "not a number"),
    ("DA1 projection neuron", "not a FlyWire root ID"),
    ("missing.swc", "not a file"),
])
def test_what_names_no_neuron_says_why(text, words):
    with pytest.raises(nr.NeuronError, match=words):
        nr.parse_spec(text)


SWC = """# a comment
# id type x y z radius parent
10 1 0 0 0 1 -1
12 3 2 0 0 1 10
11 3 1 0 0 1 10
13 3 2 1 0 1 12   # trailing comment
"""


def test_an_swc_file_gives_points_and_each_point_its_parent(tmp_path):
    path = tmp_path / "n.swc"
    path.write_text(SWC)
    assert nr.parse_spec(str(path)).path == path
    points, parents = nr.read_swc(path)
    assert points.tolist() == [[0, 0, 0], [2, 0, 0], [1, 0, 0], [2, 1, 0]]
    assert parents.tolist() == [-1, 0, 0, 1]


@pytest.mark.parametrize("body, words", [
    ("1 1 0 0 0 1 -1\n2 3 1 0 0 1 7\n", "not there"),
    ("1 1 0 0 0 1 -1\n1 3 1 0 0 1 1\n", "repeated"),
    ("1 1 0 0\n", "seven numbers"),
    ("# nothing\n", "no points"),
])
def test_a_broken_swc_file_says_why(tmp_path, body, words):
    path = tmp_path / "n.swc"
    path.write_text(body)
    with pytest.raises(nr.NeuronError, match=words):
        nr.read_swc(path)


def _tree(seed: int = 0):
    """A root, a long unbranched run that forks, and two runs after the fork."""
    rng = np.random.default_rng(seed)
    trunk = np.cumsum(np.c_[rng.uniform(0.1, 0.4, 40), np.zeros(40), np.zeros(40)], axis=0)
    left = trunk[-1] + np.cumsum(np.c_[np.zeros(30), rng.uniform(0.1, 0.4, 30),
                                       np.zeros(30)], axis=0)
    right = trunk[-1] + np.cumsum(np.c_[np.zeros(30), np.zeros(30),
                                        rng.uniform(0.1, 0.4, 30)], axis=0)
    points = np.vstack([trunk, left, right])
    parents = np.r_[-1, np.arange(39), 39, np.arange(40, 69), 39, np.arange(70, 99)]
    return points, parents


def test_thinning_keeps_the_tree_and_a_point_every_spacing():
    points, parents = _tree()
    kept, up = nr.thinned(points, parents, spacing=1.0)
    # The root, the fork and both ends are kept, and the tree is one tree.
    for point in (points[0], points[39], points[69], points[99]):
        assert np.any(np.all(kept == point, axis=1))
    assert (up < 0).sum() == 1
    assert np.all(up[up >= 0] < np.arange(len(kept))[up >= 0])
    steps = np.linalg.norm(kept[up >= 0] - kept[up[up >= 0]], axis=1)
    assert steps.max() < 1.0 + 0.4 + 1e-9         # a spacing and a step at most
    assert len(kept) < len(points) / 2


def test_a_tube_is_wound_outward_along_every_edge():
    points, parents = _tree()
    vertices, faces = nr.tube(points, parents, radius=0.4, sides=6)
    assert len(faces) == 99 * 12
    triangles = vertices[faces].astype(float)
    normals = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
    # Each edge's prism: its faces' normals point away from its axis.
    edge = np.repeat(np.arange(99), 12)
    child = np.flatnonzero(parents >= 0)
    a, b = points[child][edge], points[parents[child]][edge]
    centers = triangles.mean(axis=1)
    along = (b - a) / np.linalg.norm(b - a, axis=1, keepdims=True)
    away = centers - a - ((centers - a) * along).sum(axis=1, keepdims=True) * along
    assert np.all((normals * away).sum(axis=1) > 0)


SPACE = SimpleNamespace(id="X", title="X", flybrains_template="TX",
                        lateral_convention="biological", is_island=False)
ISLAND = SimpleNamespace(id="I", title="Island", flybrains_template=None,
                         lateral_convention="biological", is_island=True)


def test_points_in_the_brain_s_own_coordinates_are_not_bridged():
    points = np.random.default_rng(1).normal(size=(5, 3))
    assert nr.into_space(points, None, None, ISLAND) is not None
    assert np.array_equal(nr.into_space(points, None, None, SPACE), points)
    assert np.array_equal(nr.into_space(points, "TX", "biological", SPACE), points)


def test_an_island_brain_takes_no_bridged_neuron():
    with pytest.raises(nr.NeuronError, match="no link"):
        nr.into_space(np.zeros((2, 3)), "FLYWIRE", "mirrored", ISLAND)


@pytest.mark.parametrize("lateral, mirrored", [("mirrored", True), ("biological", False)])
def test_a_bridged_neuron_lands_on_its_own_side_of_the_animal(monkeypatch, lateral, mirrored):
    """Mirrored where the two brains disagree about laterality, as `resolve`
    aligns atlases by biology."""
    from lobemap.core import resolve

    asked = {}

    def resolve_points(points, source, target, mirror=False, allow_binary=None):
        asked.update(source=source, target=target, mirror=mirror)
        return np.asarray(points) + 1.0, {}

    monkeypatch.setattr(resolve, "resolve_points", resolve_points)
    out = nr.into_space(np.zeros((2, 3)), "TY", lateral, SPACE)
    assert asked == {"source": "TY", "target": "TX", "mirror": mirrored}
    assert np.array_equal(out, np.ones((2, 3)))


def test_an_swc_neuron_is_loaded_in_its_units_and_thinned(tmp_path):
    path = tmp_path / "n.swc"
    path.write_text("".join(f"{i + 1} 3 {i * 200.0} 0 0 1 {i if i else -1}\n"
                            for i in range(20)))
    points, parents, source = nr.load(nr.parse_spec(str(path)), SPACE, units="nm")
    assert source == "n.swc"
    assert points[:, 0].max() == pytest.approx(3.8)          # 3800 nm
    assert np.all(np.diff(points[:, 0]) <= 1.0 + 0.2 + 1e-9)
    assert parents[0] == -1 and np.all(parents[1:] == np.arange(len(points) - 1))


def test_a_missing_bridge_says_what_to_download(monkeypatch):
    """The hemibrain is reached only through Janelia's registrations, which a
    new installation does not have."""
    from lobemap.core import resolve

    def no_path(*args, **kwargs):
        raise ValueError("No bridging path connecting FLYWIRE and TX found.")

    monkeypatch.setattr(resolve, "resolve_points", no_path)
    with pytest.raises(nr.NeuronError, match="download_jrc_transforms"):
        nr.into_space(np.zeros((2, 3)), "TY", "biological", SPACE)
