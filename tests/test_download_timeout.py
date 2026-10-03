"""A stalled server must fail a download, not hang it.

`lobemap` fetches what a scene needs before it opens a window, so a
connection that never answers left the user with no window and no message.
The server here accepts the connection and never replies.
"""

from __future__ import annotations

import socket
import time

import pytest

from lobemap import build as B
from lobemap.core import manifest as mf


@pytest.fixture
def stalled_url(monkeypatch):
    monkeypatch.setenv("no_proxy", "*")      # talk to the stub, not a proxy
    with socket.socket() as srv:
        srv.bind(("127.0.0.1", 0))
        srv.listen(8)            # connections queue; none is ever answered
        yield f"http://127.0.0.1:{srv.getsockname()[1]}"


def test_fetch_gives_up_on_a_stalled_server(tmp_path, stalled_url):
    art = mf.Artifact("mesh", "mesh.npz", "file", "0" * 64, 10)
    t0 = time.monotonic()
    (status,) = mf.fetch([art], tmp_path, stalled_url, timeout=0.5)
    assert time.monotonic() - t0 < 10
    assert status.state == "missing"
    assert "timed out" in status.detail.lower()
    assert not (tmp_path / "mesh.npz").exists()


def test_a_build_source_download_gives_up_on_a_stalled_server(tmp_path, stalled_url,
                                                            monkeypatch):
    monkeypatch.setattr(B, "TIMEOUT_S", 0.5)
    recipe = B.Recipe(asset="toy", pipeline="obj_archive", url=f"{stalled_url}/a.zip")
    t0 = time.monotonic()
    with pytest.raises(OSError):
        B.resolve_source(recipe, tmp_path, tmp_path / "cache")
    assert time.monotonic() - t0 < 10
    assert list((tmp_path / "cache").iterdir()) == []
