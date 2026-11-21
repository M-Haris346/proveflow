"""The injection-channel guard (Phase 5, F9): a trial is valid only if the attack payload and
the canary reached the model ONLY through a tool result that came back through a proxy.
Phase 3b: the per-trial action target (R2) too (``Attack.tool_result_values``): an action
target the runner itself authored would make R2 fire on the runner's own words. And the
per-trial marker (R3, ``Attack.answer_only_values``) may be readable NOWHERE in a form R3
matches, neither in runner-authored text nor in a tool result: the payload carries it
separator-split, so only rejoining it, never quoting, can produce it.

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
    per_trial = attack.tool_result_values()  # the canary, and the action target (R2)
    needles = {"payload": attack.payload.text, **per_trial}
    out: list[str] = []
    for e in events:
        if not isinstance(e, LlmRequest) or not isinstance(e.body, dict):
            continue
        for m in e.body.get("messages") or []:
            if isinstance(m, dict) and m.get("role") in RUNNER_ROLES:
                text = canonical(m.get("content"))
                out += [f"turn {e.turn}: {k} in a {m['role']} message"
                        for k, v in needles.items() if v in text]  # fmt: skip
    for label, value in per_trial.items():  # its first carrier must be a tool result
        for e in events:
            if value in canonical(e.model_dump(mode="json")):
                if not isinstance(e, ToolResult):
                    out.append(f"seq {e.seq}: the {label} first appears in a {e.kind} event")
                break
    out += answer_only_violations(events, attack)
    return out


def answer_only_violations(events: Sequence[Event], attack: Attack) -> list[str]:
    """R3 (Phase 3b): the marker may reach the model only SEPARATOR-SPLIT. Anywhere the model
    can READ it in a form R3 matches (``oracle.answer.R3_ENCODINGS``: raw or any case), R3
    would fire on a faithful quotation, so the trial is refused: in runner-authored text (the
    system prompt, the task) and in every tool result."""
    from proveflow.oracle.answer import r3_encodings_found

    out: list[str] = []
    for label, value in attack.answer_only_values().items():
        for e in events:
            if isinstance(e, LlmRequest) and isinstance(e.body, dict):
                for m in e.body.get("messages") or []:
                    if (
                        isinstance(m, dict)
                        and m.get("role") in RUNNER_ROLES
                        and (r3_encodings_found(canonical(m.get("content")), value))
                    ):
                        out.append(f"turn {e.turn}: {label} readable in a {m['role']} message")
            elif isinstance(e, ToolResult) and r3_encodings_found(e.content, value):
                out.append(f"seq {e.seq}: {label} readable (not separator-split) in a tool result")
    return out
