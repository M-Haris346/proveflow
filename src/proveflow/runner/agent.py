"""The agent loop (Phase 5): one LLM, N proxies, every step recorded in the transcript.

Messages the RUNNER authors are exactly two: the scenario's system prompt and its user task
(``runner_messages``). Everything else in the conversation is the model's own output or a
tool result that came back through a proxy. The attack payload must therefore reach the
model ONLY inside a tool result (F9, checked over every transcript by
tests/safety/test_runner_validity.py).

Fail closed, every stop recorded (``limit_hit`` or ``error``) before ``trial_end``:
* before each request: turns, provider-reported tokens in/out against ``TrialLimits``;
* each tool call counts against ``max_tool_calls``, forwarded or not;
* the whole loop runs under the wall-clock cap (only THAT the cap fired is recorded);
* a response without integer usage counts ends the trial (``usage_missing``): the budget
  cannot be enforced on counts the provider did not report (F10);
* a provider error, a malformed response, or a replay mismatch ends the trial.
Tool calls: JSON arguments are parsed; invalid JSON or an unknown tool gets an error result
and is NOT forwarded. A known tool routes to its proxy by the routing table.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import anyio
import mcp_types

from proveflow.runner.harness import ProxyHandle
from proveflow.runner.limits import TrialLimits
from proveflow.runner.llm import ChatClient, ProviderError, ReplayMismatch, build_request
from proveflow.runner.routing import RoutingTable
from proveflow.runner.transcript import TranscriptWriter

NON_TEXT = "[non-text content omitted]"


@dataclass
class AgentOutcome:
    reason: str
    final_answer: str | None
    tokens_in: int
    tokens_out: int
    turns: int
    tool_calls: int


def runner_messages(system_prompt: str, task: str) -> list[dict[str, Any]]:
    """The ONLY messages the runner authors (F9)."""
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": task},
    ]


def result_text(result: Any) -> tuple[str, bool]:
    if not isinstance(result, mcp_types.CallToolResult):
        return NON_TEXT, True
    parts = [c.text if isinstance(c, mcp_types.TextContent) else NON_TEXT for c in result.content]
    return "\n".join(parts), bool(result.is_error)


class _Stop(Exception):
    def __init__(self, reason: str) -> None:
        self.reason = reason


async def run_agent(
    *,
    llm: ChatClient,
    model: str,
    temperature: float,
    seed: int | None,
    system_prompt: str,
    task: str,
    routing: RoutingTable,
    proxies: Mapping[str, ProxyHandle],
    limits: TrialLimits,
    record: TranscriptWriter,
) -> AgentOutcome:
    out = AgentOutcome("running", None, 0, 0, 0, 0)
    messages = runner_messages(system_prompt, task)
    tools = routing.openai_tools()

    def stop_limit(limit: str, detail: str) -> _Stop:
        record.emit("limit_hit", limit=limit, detail=detail)
        return _Stop(f"limit:{limit}")

    def stop_error(kind: str, detail: str) -> _Stop:
        record.emit("error", error_kind=kind, detail=detail)
        return _Stop(kind)

    async def loop() -> None:
        while True:
            if out.turns >= limits.max_turns:
                raise stop_limit("max_turns", f"{limits.max_turns} turns")
            if out.tokens_in >= limits.max_tokens_in:
                raise stop_limit("max_tokens_in", f"{out.tokens_in} >= {limits.max_tokens_in}")
            room_out = limits.max_tokens_out - out.tokens_out
            if room_out <= 0:
                raise stop_limit("max_tokens_out", f"{out.tokens_out} >= {limits.max_tokens_out}")
            out.turns += 1
            body = build_request(
                model=model,
                messages=messages,
                tools=tools,
                temperature=temperature,
                max_tokens=min(limits.max_tokens_per_request, room_out),
                seed=seed,
            )
            record.emit("llm_request", turn=out.turns, body=body)
            try:
                resp = await llm.complete(body)
            except ProviderError as exc:
                raise stop_error("provider_error", str(exc)) from None
            except ReplayMismatch as exc:
                raise stop_error("replay_mismatch", str(exc)) from None
            record.emit("llm_response", turn=out.turns, status=resp.status, body=resp.body,
                        tokens_in=resp.tokens_in, tokens_out=resp.tokens_out)  # fmt: skip
            if resp.tokens_in is None or resp.tokens_out is None:
                raise stop_error("usage_missing", "response has no integer usage counts")
            out.tokens_in += resp.tokens_in
            out.tokens_out += resp.tokens_out
            message = _message_of(resp.body)
            if message is None:
                raise stop_error("malformed_response", "no choices[0].message")
            calls = message.get("tool_calls") or []
            if not isinstance(calls, list):
                raise stop_error("malformed_response", "tool_calls is not a list")
            assistant: dict[str, Any] = {"role": "assistant", "content": message.get("content")}
            if calls:
                assistant["tool_calls"] = calls
            messages.append(assistant)
            if not calls:
                text = message.get("content")
                out.final_answer = text if isinstance(text, str) else ""
                record.emit("final_answer", text=out.final_answer)
                raise _Stop("final_answer")
            for call in calls:
                if out.tool_calls >= limits.max_tool_calls:
                    raise stop_limit("max_tool_calls", f"{limits.max_tool_calls} tool calls")
                out.tool_calls += 1
                content = await _tool_call(call, out.turns, routing, proxies, record)
                messages.append(content)

    try:
        with anyio.fail_after(limits.wall_clock_s):
            await loop()
    except _Stop as stop:
        out.reason = stop.reason
    except TimeoutError:
        record.emit("limit_hit", limit="wall_clock", detail=f"{limits.wall_clock_s} s")
        out.reason = "limit:wall_clock"
    return out


def _message_of(body: Any) -> dict[str, Any] | None:
    choices = body.get("choices") if isinstance(body, dict) else None
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return None
    message = choices[0].get("message")
    return message if isinstance(message, dict) else None


async def _tool_call(
    call: Any,
    turn: int,
    routing: RoutingTable,
    proxies: Mapping[str, ProxyHandle],
    record: TranscriptWriter,
) -> dict[str, Any]:
    call_id = str(call.get("id", "")) if isinstance(call, dict) else ""
    function = call.get("function") if isinstance(call, dict) else None
    name = function.get("name") if isinstance(function, dict) else None
    raw = function.get("arguments") if isinstance(function, dict) else None
    route = routing.route(name) if isinstance(name, str) else None
    server = route.server if route else "-"
    session_id = route.session_id if route else "-"
    arguments: Any = raw
    error: str | None = None
    if route is None:
        error = f"unknown tool {name!r}"
    else:
        try:
            arguments = json.loads(raw) if isinstance(raw, str) and raw else {}
        except ValueError:
            error = "invalid JSON arguments"
        else:
            if not isinstance(arguments, dict):
                error = "arguments must be a JSON object"
    record.emit("tool_call", turn=turn, call_id=call_id, tool=str(name), server=server,
                session_id=session_id, arguments=arguments)  # fmt: skip
    if error is not None or route is None:
        text, is_error = f"proveflow runner: {error}", True
    else:
        result = await proxies[route.session_id].client.call_tool(route.tool.name, arguments)
        text, is_error = result_text(result)
    record.emit("tool_result", call_id=call_id, content=text, is_error=is_error)
    return {"role": "tool", "tool_call_id": call_id, "content": text}
