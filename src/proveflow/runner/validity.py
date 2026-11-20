"""The injection-channel guard (Phase 5, F9): a trial is valid only if the attack payload and
the canary reached the model ONLY through a tool result that came back through a proxy.

The runner builds the messages, so a bug that put the payload into a system or user message
would make every trial trivially "compromised": a false-positive factory that would look
like a working tool. ``injection_channel_violations`` is checked by ``run_trial`` before any
verdict is computed; a violation raises ``InvalidTrial`` and produces no verdict.
"""

from __future__ import annotations

from collections.abc import Sequence

from proveflow.core.attacks import Attack
from proveflow.proxy.cassette import canonical
from proveflow.runner.transcript import Event, LlmRequest, ToolResult

RUNNER_ROLES = frozenset({"system", "user"})


class InvalidTrial(RuntimeError):
    """The trial's evidence is invalid by construction; no verdict is produced."""


def injection_channel_violations(events: Sequence[Event], attack: Attack | None) -> list[str]:
    if attack is None:
        return []
    needles = {"payload": attack.payload.text, "canary": attack.canary}
    out: list[str] = []
    for e in events:
        if not isinstance(e, LlmRequest) or not isinstance(e.body, dict):
            continue
        for m in e.body.get("messages") or []:
            if isinstance(m, dict) and m.get("role") in RUNNER_ROLES:
                text = canonical(m.get("content"))
                out += [f"turn {e.turn}: {k} in a {m['role']} message"
                        for k, v in needles.items() if v in text]  # fmt: skip
    for e in events:  # the first event that carries the canary must be a tool result
        text = canonical(e.model_dump(mode="json"))
        if attack.canary in text:
            if not isinstance(e, ToolResult):
                out.append(f"seq {e.seq}: the canary first appears in a {e.kind} event")
            break
    return out
