"""runner/llm.py and the provider config: one request shape, the key read at call time and
never recorded, http only to loopback, usage parsing, strict replay. httpx2.MockTransport
(socket-free); no provider is ever called."""

from __future__ import annotations

import json
from typing import Any

import anyio
import httpx2
import pytest
from pydantic import ValidationError

from proveflow.config import ProviderConfig
from proveflow.runner.llm import (
    HttpChatClient,
    ProviderError,
    ReplayChatClient,
    ReplayMismatch,
    build_request,
    usage_of,
)
from proveflow.runner.transcript import load_transcript
from runnerchecks import write_minimal_transcript

KEY = "PLANTEDproviderKey0001"
PROVIDER = ProviderConfig(
    name="groq", base_url="https://api.groq.com/openai/v1", model="m", api_key_env="PF_TEST_KEY"
)
OK = {"choices": [{"message": {"role": "assistant", "content": "x"}}],
      "usage": {"prompt_tokens": 7, "completion_tokens": 2}}  # fmt: skip


def _client(handler: Any, environ: dict[str, str] | None = None) -> HttpChatClient:
    env = {"PF_TEST_KEY": KEY} if environ is None else environ
    return HttpChatClient(PROVIDER, environ=env, transport=httpx2.MockTransport(handler))


def test_request_body_is_the_same_for_every_provider() -> None:
    body = build_request(model="m", messages=[{"role": "user", "content": "q"}],
                         tools=[{"type": "function", "function": {"name": "t"}}],
                         temperature=0.0, max_tokens=64, seed=None)  # fmt: skip
    assert set(body) == {"model", "messages", "temperature", "max_tokens", "tools"}
    assert "tool_choice" not in body and "n" not in body and "seed" not in body
    assert all("name" not in m for m in body["messages"])
    assert build_request(model="m", messages=[], tools=[], temperature=0.0, max_tokens=1,
                         seed=7)["seed"] == 7  # fmt: skip
    assert "tools" not in build_request(model="m", messages=[], tools=[], temperature=0.0,
                                        max_tokens=1, seed=None)  # fmt: skip


def test_key_read_at_call_time_sent_only_as_bearer_header() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json=OK)

    env: dict[str, str] = {}
    client = _client(handler, env)
    env["PF_TEST_KEY"] = KEY  # set AFTER construction: read at call time
    resp = anyio.run(client.complete, {"model": "m", "messages": []})
    [req] = seen
    assert req.headers["Authorization"] == f"Bearer {KEY}"
    assert str(req.url) == "https://api.groq.com/openai/v1/chat/completions"
    assert KEY not in req.content.decode()
    assert (resp.tokens_in, resp.tokens_out) == (7, 2)
    assert KEY not in repr(client.__dict__) and KEY not in repr(client)


def test_missing_key_names_the_variable_not_a_value() -> None:
    with pytest.raises(ProviderError, match="PF_TEST_KEY is not set"):
        anyio.run(_client(lambda r: httpx2.Response(200, json=OK), {}).complete, {})


@pytest.mark.parametrize("status", [400, 401, 429, 500])
def test_http_errors_never_echo_the_key_or_body(status: int) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(status, json={"error": f"bad key {KEY}"})

    with pytest.raises(ProviderError) as exc:
        anyio.run(_client(handler).complete, {})
    assert str(exc.value) == f"HTTP {status}" and KEY not in str(exc.value)


def test_transport_failure_is_a_provider_error_without_details() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError(f"cannot reach with {request.headers['Authorization']}")

    with pytest.raises(ProviderError, match=r"^request failed \(ConnectError\)$"):
        anyio.run(_client(handler).complete, {})


def test_usage_parsing_is_strict() -> None:
    assert usage_of(OK) == (7, 2)
    assert usage_of({}) == (None, None)
    assert usage_of({"usage": {"prompt_tokens": True, "completion_tokens": -1}}) == (None, None)
    assert usage_of({"usage": {"prompt_tokens": "7"}}) == (None, None)


@pytest.mark.parametrize(
    ("url", "ok"),
    [("https://api.groq.com/openai/v1", True), ("http://localhost:11434/v1/", True),
     ("http://127.0.0.1:11434/v1", True), ("http://[::1]:11434/v1", True),
     ("http://api.groq.com/openai/v1", False), ("http://10.0.0.5:11434/v1", False),
     ("ftp://x/v1", False), ("https:///v1", False)],
)  # fmt: skip
def test_http_only_to_loopback(url: str, ok: bool) -> None:
    if ok:
        ProviderConfig(name="p", base_url=url, model="m", api_key_env="K")
    else:
        with pytest.raises(ValidationError, match="loopback"):
            ProviderConfig(name="p", base_url=url, model="m", api_key_env="K")


def test_provider_config_has_no_key_field() -> None:
    with pytest.raises(ValidationError, match="Extra inputs"):
        ProviderConfig.model_validate(
            {
                "name": "p",
                "base_url": "https://x/v1",
                "model": "m",
                "api_key_env": "K",
                "api_key": KEY,
            }
        )
    with pytest.raises(ValidationError):
        ProviderConfig(name="p", base_url="https://x/v1", model="m", api_key_env="sk-live-123")


def test_replay_is_strict(tmp_path: Any) -> None:
    events = load_transcript(write_minimal_transcript(tmp_path / "t.jsonl"))
    recorded = {"model": "m", "messages": [{"role": "user", "content": "hi"}]}
    replay = ReplayChatClient(events)
    resp = anyio.run(replay.complete, json.loads(json.dumps(recorded)))
    assert resp.body["choices"][0]["message"]["content"] == "done" and replay.exhausted
    with pytest.raises(ReplayMismatch, match="more requests"):
        anyio.run(replay.complete, recorded)
    with pytest.raises(ReplayMismatch, match="differs"):
        anyio.run(ReplayChatClient(events).complete, {**recorded, "temperature": 1})
