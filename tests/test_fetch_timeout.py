"""A download that stalls fails instead of hanging.

The server here accepts every connection and never answers, which is what
a stalled connection looks like from the client. Without a timeout, urllib
waited on it forever: `fetch` never returned, and bare `lobemap`, which
fetches missing data before it opens a window, never opened one.

Everything is local: the server is a socket on 127.0.0.1.
"""

from __future__ import annotations

import socket
import threading
import time

import pytest

from lobemap import cli
from lobemap.core import manifest as mf

LIMIT_S = 0.5


@pytest.fixture
def silent_server():
    server = socket.create_server(("127.0.0.1", 0))
    server.settimeout(0.1)
    held, stop = [], threading.Event()

    def serve():
        while not stop.is_set():
            try:
                held.append(server.accept()[0])
            except TimeoutError:
                continue

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.getsockname()[1]}"
    stop.set()
    thread.join()
    for conn in held:
        conn.close()
    server.close()


@pytest.fixture
def published(tmp_path, silent_server, monkeypatch):
    """A one-artifact manifest whose base_url is the silent server."""
    monkeypatch.setattr(mf, "TIMEOUT_S", LIMIT_S)
    # urllib sends even 127.0.0.1 through an `http_proxy` from the
    # environment, and a dead one refuses at once instead of stalling.
    monkeypatch.setenv("no_proxy", "127.0.0.1")
    (tmp_path / "mesh.npz").write_bytes(b"mesh" * 10)

    class Asset:
        id, path = "mesh", tmp_path / "mesh.npz"

    registry = tmp_path / "registry"
    registry.mkdir()
    (registry / "spaces.toml").write_text('[S1]\ntitle = "S"\nunits = "um"\n')
    arts = mf.build(tmp_path, [Asset])
    (registry / "manifest.toml").write_text(mf.dump(arts, silent_server))
    return registry, tmp_path / "data"


def test_fetch_fails_on_a_silent_server(published, capsys):
    registry, data = published
    start = time.monotonic()
    rc = cli.main(["--registry", str(registry), "--data-root", str(data), "fetch"])
    elapsed = time.monotonic() - start
    assert rc == 1
    assert elapsed < 10 * LIMIT_S
    assert "timed out" in capsys.readouterr().out
    assert not (data / "mesh.npz").exists()


def test_the_viewer_still_opens_after_a_silent_server(published, monkeypatch):
    calls = []
    monkeypatch.setattr("lobemap.viewer.app.run",
                        lambda *a, **k: calls.append(time.monotonic()))
    registry, data = published
    start = time.monotonic()
    rc = cli.main(["--registry", str(registry), "--data-root", str(data),
                   "view", "S1"])
    assert rc == 0
    assert calls, "the viewer was never started"
    assert calls[0] - start < 10 * LIMIT_S


def test_an_unreachable_host_costs_one_timeout_not_one_per_artifact(
        tmp_path, silent_server, monkeypatch):
    monkeypatch.setenv("no_proxy", "127.0.0.1")
    arts = [mf.Artifact(f"a{i}", f"a{i}.npz", "file", "0" * 64, 10) for i in range(3)]
    start = time.monotonic()
    results = mf.fetch(arts, tmp_path / "data", silent_server, timeout=LIMIT_S)
    elapsed = time.monotonic() - start
    assert [s.state for s in results] == ["missing"] * 3
    assert "timed out" in results[0].detail
    assert all(s.detail.startswith("not tried:") for s in results[1:])
    assert elapsed < 2 * LIMIT_S + 1


def test_a_missing_file_does_not_stop_the_others(tmp_path):
    pub = tmp_path / "pub"
    pub.mkdir()
    (pub / "b.npz").write_bytes(b"payload")
    good = mf.build(pub, [type("A", (), {"id": "b", "path": pub / "b.npz"})])[0]
    absent = mf.Artifact("a", "a.npz", "file", "0" * 64, 10)
    results = mf.fetch([absent, good], tmp_path / "data", pub.as_uri())
    assert [s.state for s in results] == ["missing", "ok"]
