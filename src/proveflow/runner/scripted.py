"""The SCRIPTED model side of a campaign dry run (Phase 7.3a). It never reads a payload and never
reacts to one, so a dry run's rates measure THE SCRIPT, never attack success (report.SCRIPTED_NOTE;
a scripted report is refused under docs/results/).

Each attempt's conversation is derived from the template's utility predicate: one tool call per
``called_tool_with_arg`` check, in order, then a final answer. So on a FORCED-delivery template
the script calls the attacked tool (the injection is served and the cassette records it), and on
an INCIDENTAL one it may not: the dry run exercises the exposure path both ways.

What it MEASURES: the size of every request the runner sends (``plan.request_bytes``), on the
real template with the real sampled payloads. Its usage figures (100 in, 10 out per response)
are SCRIPTED constants for the budget ledger, never a token measurement.

``kill_at_request``: the process dying mid-attempt (``ScriptedKill``, a BaseException the
campaign does not catch), for the kill-and-resume dry run. ``rate_limit_at_request``: one
scripted HTTP 429.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from proveflow.runner.llm import ChatResponse, RateLimited
from proveflow.runner.plan import request_bytes
from proveflow.runner.scenario import Scenario

SCRIPTED_TOKENS_IN = 100
SCRIPTED_TOKENS_OUT = 10
FINAL_ANSWER = "Scripted final answer (dry run)."


class ScriptedKill(BaseException):
    """The dry run's simulated process death (not an Exception: nothing may catch it)."""


@dataclass(frozen=True)
class MeasuredRequest:
    request: int  # 1-based, across the whole run
    turn: int  # 0-based turn within its attempt
    bytes: int


def scripted_calls(template: Scenario) -> list[tuple[str, dict[str, Any]]]:
    """(tool, arguments) for each ``called_tool_with_arg`` check of the template's utility."""

    def flatten(pred: str, params: Mapping[str, Any]) -> list[tuple[str, dict[str, Any]]]:
        if pred == "all_of":
            return [c for chk in params["checks"] for c in flatten(chk["predicate"], chk["params"])]
        if pred == "called_tool_with_arg":
            return [(str(params["tool"]), {str(params["arg"]): params["value"]})]
        return []

    calls = flatten(template.utility.predicate, template.utility.params)
    if not calls:
        raise ValueError(f"template {template.id}: its utility names no tool call to script")
    return calls


class ScriptedChatClient:
    def __init__(self, template: Scenario, *, kill_at_request: int | None = None,
                 rate_limit_at_request: int | None = None) -> None:  # fmt: skip
        self.calls = scripted_calls(template)
        self.kill_at_request = kill_at_request
        self.rate_limit_at_request = rate_limit_at_request
        self.requests = 0
        self.measured: list[MeasuredRequest] = []

    async def complete(self, body: dict[str, Any]) -> ChatResponse:
        self.requests += 1
        if self.requests == self.kill_at_request:
            raise ScriptedKill(f"scripted process death at request {self.requests}")
        if self.requests == self.rate_limit_at_request:
            raise RateLimited("HTTP 429 (scripted)")
        turn = sum(1 for m in body["messages"] if m.get("role") == "assistant")
        self.measured.append(MeasuredRequest(self.requests, turn, request_bytes(body)))
        if turn < len(self.calls):
            tool, args = self.calls[turn]
            call = {"id": f"call_{turn + 1}", "type": "function",
                    "function": {"name": tool, "arguments": json.dumps(args)}}  # fmt: skip
            message: dict[str, Any] = {"role": "assistant", "content": None, "tool_calls": [call]}
            finish = "tool_calls"
        else:
            message, finish = {"role": "assistant", "content": FINAL_ANSWER}, "stop"
        out = {"choices": [{"finish_reason": finish, "message": message}],
               "usage": {"prompt_tokens": SCRIPTED_TOKENS_IN,
                         "completion_tokens": SCRIPTED_TOKENS_OUT}}  # fmt: skip
        return ChatResponse(200, out, SCRIPTED_TOKENS_IN, SCRIPTED_TOKENS_OUT)
