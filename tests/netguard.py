"""No test ever reaches the network (Phase 5 hard rule: no test calls a real LLM provider).

``install`` (autouse, tests/conftest.py) replaces ``socket.getaddrinfo`` with a guard that
refuses every host except loopback. Name resolution is where an HTTP client (httpx2 via
httpcore2/anyio, asyncio's ``loop.getaddrinfo``) must pass before it can open a connection,
so any provider call fails the test before a byte leaves the machine. Sockets themselves are
not blocked: asyncio's Windows event loop uses a socketpair self-pipe, and the proxy talks
to twins over pipes.
"""

from __future__ import annotations

import socket
from collections.abc import Callable
from typing import Any

LOOPBACK = frozenset({None, "localhost", "127.0.0.1", "::1", b"localhost", b"127.0.0.1"})
_REAL = socket.getaddrinfo


class NetworkRefused(AssertionError):
    pass


def guarded(underlying: Callable[..., Any]) -> Callable[..., Any]:
    def getaddrinfo(host: Any, *args: Any, **kwargs: Any) -> Any:
        if host not in LOOPBACK:
            raise NetworkRefused(f"tests must not reach the network: getaddrinfo({host!r})")
        return underlying(host, *args, **kwargs)

    return getaddrinfo


def install(monkeypatch: Any) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", guarded(_REAL))


def assert_provider_hosts_are_refused(make_guard: Callable[..., Any] = guarded) -> None:
    """Named check: the guard refuses every provider host BEFORE the real resolver runs.
    The underlying resolver here is a spy, so this check itself never touches the network."""
    reached: list[Any] = []

    def spy(host: Any, *args: Any, **kwargs: Any) -> Any:
        reached.append(host)
        raise OSError("spy: no real resolution in tests")

    guard = make_guard(spy)
    for host in ("api.groq.com", "generativelanguage.googleapis.com", "ollama.com", "8.8.8.8"):
        try:
            guard(host, 443)
        except NetworkRefused:
            continue
        except OSError:
            pass
        raise AssertionError(f"network guard let {host} through")
    if reached:
        raise AssertionError(f"network guard reached the resolver for {reached}")
