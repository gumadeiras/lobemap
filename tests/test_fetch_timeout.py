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
    # raising=False so the test also runs, and hangs, where there is no limit.
    monkeypatch.setattr(cli, "NETWORK_TIMEOUT_S", LIMIT_S, raising=False)
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


def test_main_leaves_the_process_default_as_it_found_it(published):
    registry, data = published
    before = socket.getdefaulttimeout()
    cli.main(["--registry", str(registry), "--data-root", str(data), "fetch"])
    assert socket.getdefaulttimeout() == before
