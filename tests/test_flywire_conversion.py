"""Real neuron loading and navis transforms, with only HTTP replaced.

Neuron display uses MIP 7 without changing atlas transforms, units, mirrors,
or the skeleton tree. No request leaves this process.
"""

from __future__ import annotations

import warnings
from types import SimpleNamespace

import numpy as np
import pytest

from lobemap.core import neurons as nr
from lobemap.core import resolve, spaces

ROOT = 720575940632403986
FAFB = SimpleNamespace(id="FAFB14", title="FAFB", flybrains_template="FAFB14",
                       lateral_convention="mirrored", is_island=False)


@pytest.fixture
def flywire_http(monkeypatch):
    pytest.importorskip("navis")
    requests = pytest.importorskip("requests")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        fafbseg = pytest.importorskip("fafbseg")
    state = SimpleNamespace(
        points=np.array([[40000, 80000, 120000], [44000, 80000, 120000],
                         [48000, 80000, 120000], [44000, 84000, 120000]], np.float32),
        parents=np.array([-1, 0, 1, 1]), calls=[], status=200, nonfinite=False,
    )
    monkeypatch.delattr(fafbseg.spine.transform, "_info", raising=False)

    def request(self, method, url, **kwargs):
        response = requests.Response()
        response.status_code = 200
        response.url = url
        state.calls.append((method, url, kwargs))
        if url.endswith(f"flywire_skeletons_783/{ROOT}"):
            edges = np.array([[0, 1], [1, 2], [1, 3]], np.uint32)
            response._content = (np.array([4, 3], np.uint32).tobytes()
                                 + state.points.tobytes() + edges.tobytes()
                                 + np.ones(4, np.float32).tobytes())
        elif url.endswith("transform-service/info"):
            response._content = (
                b'{"flywire_v1":{"scales":[2,3,4,5,6,7],"voxel_size":[4,4,40]},'
                b'"flywire_v1_inverse":{"scales":[4],"voxel_size":[4,4,40]}}')
        elif method == "POST" and "transform/dataset/flywire_v1" in url:
            response.status_code = state.status
            count = len(kwargs["data"]) // 12
            offset = [3, 5] if "/s/7/" in url else [1, 2]
            offsets = np.tile(offset, (count, 1)).astype(np.float32)
            if state.nonfinite:
                offsets[1] = np.nan
            response._content = offsets.tobytes()
        else:
            pytest.fail(f"unexpected request: {method} {url}")
        return response

    monkeypatch.setattr(requests.Session, "request", request)
    return state


@pytest.mark.parametrize("input_kind", ["root", "link", "swc"])
def test_neuron_conversion_uses_mip7_without_changing_atlas_transforms(
        flywire_http, tmp_path, input_kind):
    state = flywire_http
    text = str(ROOT)
    if input_kind == "link":
        text = f"https://codex.flywire.ai/app/cell_details?root_id={ROOT}&data_version=783"
    elif input_kind == "swc":
        path = tmp_path / "flywire.swc"
        path.write_text("".join(
            f"{i} 3 {x} {y} {z} 1 {parent}\n"
            for i, ((x, y, z), parent) in enumerate(zip(state.points, state.parents))))
        text = str(path)

    points, parents, _source = nr.load(nr.parse_spec(text), FAFB,
                                      template="FLYWIRE", lateral="mirrored")
    expected = state.points.astype(float) * 1e-3 + [0.012, 0.020, 0.0]
    np.testing.assert_allclose(points, expected)
    np.testing.assert_array_equal(parents, state.parents)
    posts = [call for call in state.calls if call[0] == "POST"]
    assert len(posts) == 1
    assert "/flywire_v1/s/7/" in posts[0][1]
    np.testing.assert_allclose(
        np.frombuffer(posts[0][2]["data"], np.float32).reshape(-1, 3),
        state.points / [4, 4, 40])

    # A later atlas conversion must still use the registered full resolution.
    atlas, record = resolve.resolve_points(state.points * 1e-3, "FLYWIRE", "FAFB14")
    np.testing.assert_allclose(atlas, state.points.astype(float) * 1e-3 + [0.004, 0.008, 0.0])
    assert "/flywire_v1/s/2/" in state.calls[-1][1]
    assert "flywire_mip" not in record


@pytest.mark.parametrize("mirror", [False, True])
def test_mip7_preserves_mirror_order_and_uncovered_points(flywire_http, monkeypatch, mirror):
    state = flywire_http
    state.nonfinite = True
    points = state.points.astype(float) * 1e-3
    before = points.copy()

    def reflect(native, template):
        assert template == "FLYWIRE"
        np.testing.assert_allclose(native, points * 1000)
        out = native.copy()
        out[:, 0] = 1_000_000 - out[:, 0]
        return out

    monkeypatch.setattr(spaces, "mirror", reflect)
    if mirror:
        before[:, 0] = 1000 - before[:, 0]
    with pytest.warns(UserWarning, match="1 points failed to transform"):
        out, record = resolve.resolve_points(points, "FLYWIRE", "FAFB14",
                                             mirror=mirror, flywire_mip=7)
    expected = before + [0.012, 0.020, 0.0]
    expected[1] = before[1]
    np.testing.assert_allclose(out, expected)
    np.testing.assert_array_equal(points, state.points.astype(float) * 1e-3)
    assert record["flywire_mip"] == 7
    assert record["n_nonfinite"] == 1


def test_inverse_flywire_transform_keeps_its_supported_resolution(flywire_http):
    points = flywire_http.points.astype(float) * 1e-3
    out, record = resolve.resolve_points(points, "FAFB14", "FLYWIRE", flywire_mip=7)
    np.testing.assert_allclose(out, points + [0.004, 0.008, 0.0])
    assert "/flywire_v1_inverse/s/4/" in flywire_http.calls[-1][1]
    assert "flywire_mip" not in record


def test_mip7_keeps_network_errors_visible(flywire_http):
    flywire_http.status = 503
    with pytest.raises(nr.NeuronError, match="could not be bridged.*503"):
        nr.load(nr.parse_spec(str(ROOT)), FAFB)


def test_male_cns_conversion_does_not_request_the_offset_field(flywire_http):
    target = SimpleNamespace(id="JRCFIB2022M", flybrains_template="JRCFIB2022M",
                             lateral_convention="biological", is_island=False)
    points = flywire_http.points.astype(float) * 1e-3
    out = nr.into_space(points, "FLYWIRE", "mirrored", target)
    expected, _record = resolve.resolve_points(points, "FLYWIRE", "JRCFIB2022M", mirror=True)
    np.testing.assert_array_equal(out, expected)
    assert not flywire_http.calls
