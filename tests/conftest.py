"""Shared test setup: the registry under test, its data, and no network.

Each module used to settle these for itself, and three ways of getting them
wrong made the suite's result depend on where and how it ran:

- `Registry.load("registry")` resolved against the working directory. Run
  from anywhere but the repository root it found no registry, loaded an
  empty one, and the tests that iterate it passed having checked nothing.
- Data was assumed present when `registry/data` existed. That directory is
  tracked -- it holds a README -- so on a fresh clone the guard always
  passed, and 96 tests failed or errored instead of skipping.
- The `lobemap view` tests ran the real autofetch, which on a fresh clone
  downloads 76 MB into the checkout, and passed whether or not it worked.

So the registry is found here, once; a test that reads fetched data says
which; and no test reaches the network.

Data-dependent tests
--------------------

Mark a test, a class or a module (`pytestmark = ...`) that reads fetched
data::

    @pytest.mark.requires_data                   # the core data
    @pytest.mark.requires_data("fafb_stain")     # exactly these assets

Bare, it asks for the core data: every asset `lobemap view` fetches by
itself, which is all of them but the recipes flagged `expensive` (the
virtual stains). With arguments it asks for exactly those assets, named by
their id in `registry/assets.toml`. The test is skipped, with the missing
ids in the reason, unless every one is on disk under the data root the
registry itself resolves -- so `LOBEMAP_DATA` pointing at an empty directory
skips them all. An id the registry does not declare stops the run instead,
so a typo cannot retire a test quietly.

Fixtures cannot carry marks. A fixture that needs the core data -- one that
builds a scene, say -- requests `core_data` instead, and every test using it
skips the same way.

Take the `registry` fixture rather than loading one: it is the registry the
CLI opens, with the data root the marker checks. `registry_root` is its
path, for a test that needs a private copy to change.

No network
----------

Python's sockets are guarded for the whole session. Resolving any name but
`localhost`, or connecting anywhere but loopback, is refused and fails the
test that tried -- also when the code under test swallows the error, as
autofetch does. A local server on loopback is fine. A proxy is not, even on
loopback, because a connection to a proxy is a connection to the network.
"""

from __future__ import annotations

import functools
import ipaddress
import socket
import tomllib
import urllib.parse
import urllib.request
from pathlib import Path

import pytest

from lobemap.cli import DEFAULT_REGISTRY
from lobemap.core.registry import Registry

#: The registry the CLI opens by default. Absolute, so no result depends on
#: the working directory.
REGISTRY = DEFAULT_REGISTRY


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "requires_data(*asset_ids): skip unless these assets are on disk "
        "(bare: the core data); see tests/conftest.py",
    )


# -- data --------------------------------------------------------------------


@functools.cache
def _declared_assets() -> tuple[Path, dict[str, Path]]:
    """The data root, and where each declared asset lives under it.

    Read from `assets.toml` and resolved by `Registry.asset_path`, the same
    call the registry makes, without loading any mesh to do it.
    """
    empty = Registry(REGISTRY)
    with (REGISTRY / "assets.toml").open("rb") as fh:
        declared = tomllib.load(fh)
    paths = {aid: empty.asset_path(body["path"]) for aid, body in declared.items()}
    return empty.data_root, paths


@functools.cache
def _core_assets() -> frozenset[str]:
    from lobemap.build import load_recipes

    expensive = {name for name, r in load_recipes(REGISTRY).items() if r.expensive}
    return frozenset(_declared_assets()[1]) - expensive


def _absent(wanted) -> str | None:
    """Why a test needing these assets cannot run, or None if it can."""
    data_root, paths = _declared_assets()
    missing = sorted(a for a in wanted if not paths[a].exists())
    if not missing:
        return None
    return f"data not on disk under {data_root}: {', '.join(missing)} (lobemap fetch)"


def pytest_collection_modifyitems(config, items):
    declared = _declared_assets()[1]
    for item in items:
        wanted: set[str] = set()
        for mark in item.iter_markers("requires_data"):
            wanted.update(mark.args or _core_assets())
        unknown = sorted(wanted - set(declared))
        if unknown:
            raise pytest.UsageError(
                f"{item.nodeid}: requires_data names assets the registry "
                f"does not declare: {', '.join(unknown)}"
            )
        reason = _absent(wanted)
        if reason:
            item.add_marker(pytest.mark.skip(reason=reason))


@pytest.fixture(scope="session")
def core_data() -> None:
    """A bare `requires_data` for fixtures, which cannot carry marks.

    A fixture that builds a scene requests this, and every test using that
    fixture skips without the core data.
    """
    reason = _absent(_core_assets())
    if reason:
        pytest.skip(reason)


@pytest.fixture(scope="session")
def registry_root() -> Path:
    return REGISTRY


@pytest.fixture(scope="module")
def registry(registry_root) -> Registry:
    return Registry.load(registry_root)


# -- network -----------------------------------------------------------------

_ATTEMPTS: list[str] = []


def _is_loopback(host) -> bool:
    if isinstance(host, bytes):
        host = host.decode()
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.split("%")[0]).is_loopback
    except ValueError:
        return False


def _is_address(host) -> bool:
    try:
        ipaddress.ip_address(str(host).split("%")[0])
    except ValueError:
        return False
    return True


def _loopback_proxy_ports() -> frozenset[int]:
    """Ports of proxies configured on loopback, where the guard cannot tell
    a proxied download from a local test server by address alone."""
    ports = set()
    for scheme, url in urllib.request.getproxies().items():
        if scheme == "no":
            continue
        parts = urllib.parse.urlsplit(url if "://" in url else f"http://{url}")
        if parts.hostname and _is_loopback(parts.hostname):
            ports.add(parts.port or (443 if parts.scheme == "https" else 80))
    return frozenset(ports)


@pytest.fixture(scope="session", autouse=True)
def _network_guard():
    real_getaddrinfo = socket.getaddrinfo
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    proxy_ports = _loopback_proxy_ports()

    def getaddrinfo(host, *args, **kwargs):
        if host and not _is_loopback(host) and not _is_address(host):
            _ATTEMPTS.append(f"resolve {host}")
            raise socket.gaierror(socket.EAI_NONAME, f"no network in tests: {host}")
        return real_getaddrinfo(host, *args, **kwargs)

    def check(sock, address) -> None:
        if sock.family not in (socket.AF_INET, socket.AF_INET6):
            return
        host, port = address[0], address[1]
        if _is_loopback(host) and port not in proxy_ports:
            return
        _ATTEMPTS.append(f"connect {host}:{port}")
        raise ConnectionRefusedError(f"no network in tests: {host}:{port}")

    def connect(self, address):
        check(self, address)
        return real_connect(self, address)

    def connect_ex(self, address):
        check(self, address)
        return real_connect_ex(self, address)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(socket, "getaddrinfo", getaddrinfo)
        mp.setattr(socket.socket, "connect", connect)
        mp.setattr(socket.socket, "connect_ex", connect_ex)
        yield


@pytest.fixture(autouse=True)
def _no_network(_network_guard):
    yield
    if _ATTEMPTS:
        tried = ", ".join(dict.fromkeys(_ATTEMPTS))
        _ATTEMPTS.clear()
        pytest.fail(f"tried to reach the network: {tried}", pytrace=False)
