"""Mesh containers must not require pickle to read.

They are the things M7 plans to fetch rather than ship, and `allow_pickle`
turns a download into arbitrary code execution. Legacy files stay readable,
but only by an explicit opt-in path.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from lobemap.core.meshfmt import MeshSet


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


def test_legacy_object_array_still_reads(tmp_path):
    """Files already on disk must not become unreadable."""
    ms = _meshset()
    path = tmp_path / "legacy.npz"
    np.savez_compressed(
        path, vertices=ms.vertices, faces=ms.faces,
        vertex_offsets=ms.vertex_offsets, face_offsets=ms.face_offsets,
        names=np.asarray(ms.names, dtype=object),
        meta=np.asarray(json.dumps({"source": "test"})),
    )
    back = MeshSet.load(path)
    assert back.names == ms.names
    assert back.meta["legacy_names_container"] is True


def test_resaving_migrates_a_legacy_file(tmp_path):
    ms = _meshset()
    path = tmp_path / "legacy.npz"
    np.savez_compressed(
        path, vertices=ms.vertices, faces=ms.faces,
        vertex_offsets=ms.vertex_offsets, face_offsets=ms.face_offsets,
        names=np.asarray(ms.names, dtype=object),
        meta=np.asarray(json.dumps({"source": "test"})),
    )
    MeshSet.load(path).save(path)
    with np.load(path, allow_pickle=False) as z:
        assert "names_json" in z.files


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
