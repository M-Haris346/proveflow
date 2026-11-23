"""The injection-channel guard (Phase 5, F9): a trial is valid only if the attack payload and
the canary reached the model ONLY through a tool result that came back through a proxy.
The SPLIT VALUES (``Attack.split_values``: the marker, R3, and since Phase 6 the action
target, R2) may be readable NOWHERE in a form R2/R3 match, neither in runner-authored text
nor in a tool result: they reach the model only separator-split, so only rejoining them,
never quoting, can produce them. (In Phase 3b the action target was a tool-result value whose
first carrier had to be a tool result; split, its raw form first appears in the model's own
tool call, so that rule would refuse every successful R2 trial.)

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
    per_trial = attack.tool_result_values()  # the canary
    needles = {**attack.tool_result_texts(), **per_trial}  # payload + goal clause (Phase 6)
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
    out += split_value_violations(events, attack)
    return out


def split_value_violations(events: Sequence[Event], attack: Attack) -> list[str]:
    """R2 and R3: each split value may reach the model only SEPARATOR-SPLIT. Anywhere the
    model can READ it in a form R2/R3 match (``oracle.matcher.SPLIT_VALUE_ENCODINGS``: raw or
    any case), the rule would fire on a faithful quotation, so the trial is refused: in
    runner-authored text (the system prompt, the task) and in every tool result. Fail-closed
    and conservative: a tool that ECHOED a split value back after the model produced it would
    refuse the trial too. MEASURED for the sandbox: its reply to every sink tool the fake twin
    offers carries none of the call's argument values (corpuschecks.assert_the_sandbox_never_
    echoes_sink_arguments, with an echoing-sandbox mutation). NOT measured for a dual-role
    sink FORWARDED to a guard-passing generated twin; its reply is that tool's one canned
    response (twin/generator.py, F3), argument-independent by construction."""
    from proveflow.oracle.matcher import split_value_encodings_found as found

    out: list[str] = []
    for label, value in attack.split_values().items():
        for e in events:
            if isinstance(e, LlmRequest) and isinstance(e.body, dict):
                for m in e.body.get("messages") or []:
                    if (
                        isinstance(m, dict)
                        and m.get("role") in RUNNER_ROLES
                        and (found(canonical(m.get("content")), value))
                    ):
                        out.append(f"turn {e.turn}: {label} readable in a {m['role']} message")
            elif isinstance(e, ToolResult) and found(e.content, value):
                out.append(f"seq {e.seq}: {label} readable (not separator-split) in a tool result")
    return out
