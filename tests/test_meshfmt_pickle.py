"""Mesh containers must not require pickle to read.

They are fetched rather than shipped, and `allow_pickle` turns a download
into arbitrary code execution. Legacy files stay readable, but only when the
caller opts in for a file it trusts.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from lobemap.core import resolve as R
from lobemap.core.meshfmt import LegacyContainerError, MeshSet


def _meshset():
    v = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]], np.float32)
    f = np.array([[0, 1, 2], [0, 1, 3]], np.int32)
    return MeshSet(vertices=np.vstack([v, v]), faces=np.vstack([f, f + 4]),
                   vertex_offsets=np.array([0, 4, 8]),
                   face_offsets=np.array([0, 2, 4]),
                   names=["DA1(L)", "VM6v(R)"], meta={"source": "test"})


def test_saved_container_loads_without_pickle(tmp_path):
    ms = _meshset()
    path = ms.save(tmp_path / "m.npz")
    with np.load(path, allow_pickle=False) as z:
        assert "names_json" in z.files
        assert "names" not in z.files
        assert json.loads(str(z["names_json"])) == ["DA1(L)", "VM6v(R)"]
    assert MeshSet.load(path).names == ms.names


def _legacy(path, names):
    """A container in the pre-JSON layout: names as a pickled object array."""
    ms = _meshset()
    np.savez_compressed(
        path, vertices=ms.vertices, faces=ms.faces,
        vertex_offsets=ms.vertex_offsets, face_offsets=ms.face_offsets,
        names=np.asarray(names, dtype=object),
        meta=np.asarray(json.dumps({"source": "test"})),
    )
    return path


class _TouchOnUnpickle:
    """Unpickling this opens `marker` for writing, which creates it."""

    def __init__(self, marker):
        self.marker = str(marker)

    def __reduce__(self):
        return (open, (self.marker, "w"))


def test_legacy_object_array_is_refused_by_default(tmp_path):
    path = _legacy(tmp_path / "legacy.npz", _meshset().names)
    with pytest.raises(LegacyContainerError, match="pickle"):
        MeshSet.load(path)


def test_legacy_object_array_reads_when_the_caller_opts_in(tmp_path):
    """A trusted file already on disk must not become unreadable."""
    ms = _meshset()
    back = MeshSet.load(_legacy(tmp_path / "legacy.npz", ms.names),
                        allow_legacy_pickle=True)
    assert back.names == ms.names
    assert back.meta["legacy_names_container"] is True


def test_a_pickle_payload_in_legacy_names_never_runs(tmp_path):
    """The payload creates a file when unpickled; loading must not create it."""
    marker = tmp_path / "payload-ran"
    path = _legacy(tmp_path / "crafted.npz",
                   [_TouchOnUnpickle(marker), _TouchOnUnpickle(marker)])
    with pytest.raises(LegacyContainerError):
        MeshSet.load(path)
    assert not marker.exists()
    # The same file does run the payload once pickle is allowed, so the
    # assertion above is not vacuous.
    with np.load(path, allow_pickle=True) as z:
        z["names"]
    assert marker.exists()


def test_a_pickled_bridge_cache_entry_is_rebuilt_not_read(tmp_path, monkeypatch):
    """The bridge cache is a directory anyone on the machine may write to."""
    monkeypatch.setattr(R, "cache_root", lambda: tmp_path / "cache")
    monkeypatch.setattr(R.sp, "tool_versions", lambda: {"navis": "test"})
    monkeypatch.setattr(R.sp, "choose_path",
                        lambda s, t, allow_binary=None: {"path": [s, t]})
    monkeypatch.setattr(R, "resolve_points",
                        lambda pts, s, t, **kw: (pts + 1.0, {"path": [s, t]}))
    ms = _meshset()
    first = R.resolve_meshset(ms, "A", "B", "TA", "TB")
    (entry,) = (tmp_path / "cache").glob("*.npz")

    marker = tmp_path / "payload-ran"
    _legacy(entry, [_TouchOnUnpickle(marker), _TouchOnUnpickle(marker)])
    again = R.resolve_meshset(ms, "A", "B", "TA", "TB")
    assert not marker.exists()
    np.testing.assert_array_equal(again.vertices, first.vertices)
    with np.load(entry, allow_pickle=False) as z:
        assert "names_json" in z.files, "the entry is rewritten without pickle"


def test_resaving_migrates_a_legacy_file(tmp_path):
    path = _legacy(tmp_path / "legacy.npz", _meshset().names)
    MeshSet.load(path, allow_legacy_pickle=True).save(path)
    with np.load(path, allow_pickle=False) as z:
        assert "names_json" in z.files
    assert MeshSet.load(path).names == _meshset().names


def test_migration_preserves_the_content_hash(tmp_path):
    """Or every cached bridge silently invalidates."""
    ms = _meshset()
    before = ms.content_hash()
    path = ms.save(tmp_path / "m.npz")
    assert MeshSet.load(path).content_hash() == before


def test_names_with_awkward_characters_survive_json(tmp_path):
    ms = _meshset()
    ms.names = ['VC3l"(L)', "VM6\v", "AL-DA1(R)", "unicode-µm"]
    ms.vertex_offsets = np.array([0, 2, 4, 6, 8])
    ms.face_offsets = np.array([0, 1, 2, 3, 4])
    path = ms.save(tmp_path / "m.npz")
    assert MeshSet.load(path).names == ms.names


@pytest.mark.parametrize("bad", [b"cos\nsystem\n(S'echo pwned'\ntR.", b"\x80\x04N."])
def test_pickle_payload_in_names_is_not_executed(tmp_path, bad):
    """A hostile container must fail to load, not run."""
    ms = _meshset()
    path = ms.save(tmp_path / "m.npz")
    with np.load(path, allow_pickle=False) as z:
        fields = {k: z[k] for k in z.files}
    fields["names_json"] = np.frombuffer(bad, dtype=np.uint8)
    np.savez_compressed(path, **fields)
    with pytest.raises((ValueError, UnicodeDecodeError, TypeError)):
        MeshSet.load(path)
