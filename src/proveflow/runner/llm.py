"""LLM clients (Phase 5, D1/D2): one OpenAI-compatible HTTP path, and a strict replay.

``HttpChatClient`` POSTs ``<base_url>/chat/completions`` over httpx2 (the exact-pinned
dependency already in the tree via mcp). It has no provider-specific code path; the request
body is built once by ``build_request`` from documented common fields only
(docs/PROVIDERS.md):
* ``tool_choice`` is never sent (unsupported by Ollama; "auto" is the documented default when
  tools are present), nor ``messages[].name`` (a 400 on Groq), ``n``, ``logprobs``;
* ``seed`` is sent only when the provider config says ``send_seed``; the transcript records
  the seed and whether it was sent.

The API key: read from the environment variable named by ``api_key_env`` at the moment of
the call, used for one ``Authorization`` header, never stored on an object, never logged,
never part of a recorded request (headers are not recorded) or of an error message.

``ReplayChatClient`` answers from a recorded transcript without any network: each new
request must equal the recorded request (canonical JSON) or ``ReplayMismatch`` is raised.
It never generates text. There is no author mode in this package: authoring a transcript
from fixed response bodies is a dev-only script (tools/author_transcript.py), unreachable
from the test suite.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

import httpx2

from proveflow.config import ProviderConfig
from proveflow.proxy.cassette import canonical
from proveflow.runner.transcript import Event, LlmRequest, LlmResponse

REQUEST_TIMEOUT_S = 60.0


class ProviderError(RuntimeError):
    """The provider call failed. The message never carries the key or response headers."""


class ReplayMismatch(RuntimeError):
    """A replayed run sent a request that differs from the recorded one (or ran past it)."""


@dataclass(frozen=True)
class ChatResponse:
    status: int
    body: Any
    tokens_in: int | None
    tokens_out: int | None


class ChatClient(Protocol):
    async def complete(self, body: dict[str, Any]) -> ChatResponse: ...


def build_request(
    *,
    model: str,
    messages: Sequence[Mapping[str, Any]],
    tools: Sequence[Mapping[str, Any]],
    temperature: float,
    max_tokens: int,
    seed: int | None,
) -> dict[str, Any]:
    """The request body, the same for every provider (no tool_choice, no name, no n)."""
    body: dict[str, Any] = {
        "model": model,
        "messages": [dict(m) for m in messages],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if tools:
        body["tools"] = [dict(t) for t in tools]
    if seed is not None:
        body["seed"] = seed
    return body


def usage_of(body: Any) -> tuple[int | None, int | None]:
    """Provider-reported prompt/completion tokens (F10), or None when absent or not an int."""
    usage = body.get("usage") if isinstance(body, dict) else None
    if not isinstance(usage, dict):
        return None, None
    tin, tout = usage.get("prompt_tokens"), usage.get("completion_tokens")
    ok_in = isinstance(tin, int) and not isinstance(tin, bool) and tin >= 0
    ok_out = isinstance(tout, int) and not isinstance(tout, bool) and tout >= 0
    return (tin if ok_in else None), (tout if ok_out else None)


class HttpChatClient:
    def __init__(
        self,
        provider: ProviderConfig,
        *,
        environ: Mapping[str, str] | None = None,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        self._provider = provider
        # Only a lookup function is kept, never the mapping itself, so no repr, log or
        # traceback of this object can print an environment value.
        self._lookup = (environ if environ is not None else os.environ).get
        self._transport = transport

    def __repr__(self) -> str:
        return (
            f"HttpChatClient(provider={self._provider.name!r}, "
            f"api_key_env={self._provider.api_key_env!r})"
        )

    @property
    def url(self) -> str:
        return self._provider.base_url.rstrip("/") + "/chat/completions"

    async def complete(self, body: dict[str, Any]) -> ChatResponse:
        name = self._provider.api_key_env
        key = self._lookup(name)
        if not key:
            raise ProviderError(f"environment variable {name} is not set")
        try:
            async with httpx2.AsyncClient(
                transport=self._transport, timeout=REQUEST_TIMEOUT_S
            ) as http:
                response = await http.post(
                    self.url, json=body, headers={"Authorization": f"Bearer {key}"}
                )
        except httpx2.HTTPError as exc:
            raise ProviderError(f"request failed ({type(exc).__name__})") from None
        finally:
            del key
        try:
            payload: Any = response.json()
        except ValueError:
            raise ProviderError(f"HTTP {response.status_code}: response is not JSON") from None
        if response.status_code != 200:
            raise ProviderError(f"HTTP {response.status_code}")
        tokens_in, tokens_out = usage_of(payload)
        return ChatResponse(response.status_code, payload, tokens_in, tokens_out)


class ReplayChatClient:
    """Strict replay of the (llm_request, llm_response) pairs of a recorded transcript."""

    def __init__(self, events: Sequence[Event]) -> None:
        requests = [e for e in events if isinstance(e, LlmRequest)]
        responses = [e for e in events if isinstance(e, LlmResponse)]
        if [r.turn for r in requests] != [r.turn for r in responses]:
            raise ReplayMismatch("recorded requests and responses do not pair up by turn")
        self._pairs = list(zip(requests, responses, strict=True))
        self._next = 0

    @property
    def exhausted(self) -> bool:
        return self._next >= len(self._pairs)

    async def complete(self, body: dict[str, Any]) -> ChatResponse:
        if self.exhausted:
            raise ReplayMismatch("the run sent more requests than were recorded")
        request, response = self._pairs[self._next]
        if request.truncated or response.truncated:
            raise ReplayMismatch(f"turn {request.turn} was truncated; it cannot be replayed")
        if canonical(body) != canonical(request.body):
            raise ReplayMismatch(f"turn {request.turn}: request differs from the recording")
        self._next += 1
        return ChatResponse(response.status, response.body, response.tokens_in, response.tokens_out)
