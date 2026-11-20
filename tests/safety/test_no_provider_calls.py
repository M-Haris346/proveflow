"""No test ever calls a real LLM provider (Phase 5 hard rule), enforced for every test by the
autouse network guard (tests/netguard.py, installed in tests/conftest.py)."""

from __future__ import annotations

import socket

import anyio
import httpx2
import pytest

from netguard import NetworkRefused, assert_provider_hosts_are_refused
from proveflow.config import ProviderConfig
from proveflow.runner.llm import HttpChatClient, ProviderError


def test_guard_refuses_provider_hosts_before_resolution() -> None:
    assert_provider_hosts_are_refused()


def test_guard_is_installed_for_every_test() -> None:
    with pytest.raises(NetworkRefused, match=r"api.groq.com"):
        socket.getaddrinfo("api.groq.com", 443)
    socket.getaddrinfo("localhost", 0)  # loopback still resolves


def test_a_real_http_client_call_fails_in_tests() -> None:
    """The runner's real client, with its real transport, cannot reach a provider here."""
    provider = ProviderConfig(
        name="groq", base_url="https://api.groq.com/openai/v1", model="m", api_key_env="K"
    )
    client = HttpChatClient(provider, environ={"K": "not-a-real-key"})
    with pytest.raises((ProviderError, NetworkRefused, httpx2.HTTPError)):
        anyio.run(client.complete, {"model": "m", "messages": []})
