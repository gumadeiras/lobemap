"""Shared test setup: no test reaches the network.

The `lobemap view` tests ran the real autofetch, which on a fresh clone
downloads 76 MB into the checkout, and passed whether or not it worked.
Nothing noticed, because autofetch is built to swallow a failed download.

No network
----------

Python's sockets are guarded for the whole session. Resolving any name but
`localhost`, or connecting anywhere but loopback, is refused and fails the
test that tried -- also when the code under test swallows the error, as
autofetch does. A local server on loopback is fine. A proxy is not, even on
loopback, because a connection to a proxy is a connection to the network.
"""

from __future__ import annotations

import ipaddress
import socket
import urllib.parse
import urllib.request

import pytest

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
