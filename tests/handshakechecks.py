"""Named checks for the twin handshake deadline (Phase 7.0). A handshake hang is made VISIBLE,
BOUNDED and NAMED here; its root cause is still unknown (docs/BACKLOG.md, sighting 3).

Two INDEPENDENT layers bound it, and neither subsumes the other:
  PROXY: proxy/server.py ``serve()`` gives each stage (cassette.HANDSHAKE_STAGES) its own bound
    (``limits.handshake_timeout_s``) and ends the session ``handshake_timeout`` NAMING the stage;
  HARNESS: runner/harness.py ``running_proxies`` bounds each proxy's startup
    (``startup_bound_s``), the backstop when the proxy itself never ends the session.
One mutation per layer (the other layer switched off) plus one for the layering
(tests/mutation/test_handshake_mutation.py). Offline: in-process proxies, the fake twin."""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import anyio
import pytest

QUICK = 1.0  # the bound for a stage that is MADE to hang: the clock starts when it starts
ENOUGH = 10.0  # the bound for stages that must succeed first (a twin starts in ~2 s unloaded)


def _hang(*args: Any, **kwargs: Any) -> Any:
    async def forever() -> Any:
        await anyio.sleep_forever()

    return forever()


def _patch_spawn(mp: pytest.MonkeyPatch) -> None:
    from proveflow.proxy import upstream

    mp.setattr(upstream, "spawn", lambda *a, **k: _hang())


def _patch_tools_list(mp: pytest.MonkeyPatch) -> None:
    from proveflow.proxy import server

    mp.setattr(server, "_list_upstream_tools", lambda client: _hang())


# How to make EACH stage hang: (twin args, monkeypatch, per-stage bound). Its keys must equal
# cassette.HANDSHAKE_STAGES exactly (checked below), so a new stage cannot go untested.
HANG_MAKERS: dict[str, tuple[tuple[str, ...], Callable[[pytest.MonkeyPatch], None] | None, float]] = {  # noqa: E501
    "spawn": ((), _patch_spawn, QUICK),
    "initialize": (("--hang-initialize",), None, QUICK),
    "tools_list": ((), _patch_tools_list, ENOUGH),
}  # fmt: skip


def stage_facts(events: list[Any]) -> list[tuple[str, str]]:
    return [(e.stage, e.status) for e in events if e.kind == "handshake_stage"]


def _session(tmp_path: Path, **limits: Any) -> Any:
    from proveflow.proxy.session import ProxyLimits
    from proxyhelpers import make_session

    twin_args = limits.pop("twin_args", ())
    return make_session(tmp_path, limits=ProxyLimits(**limits), twin_args=twin_args)


def assert_every_stage_is_recorded(tmp_path: Path) -> None:
    """Named check (Q2): EVERY stage of cassette.HANDSHAKE_STAGES (read at call time, the one
    source of truth) is recorded started then completed, once, in that order, on a normal
    session; nothing is outstanding at the end. A stage added to the literal without being
    recorded fails here."""
    from proveflow.proxy import cassette
    from proveflow.proxy.cassette import load_cassette
    from proxyhelpers import run_in_process

    session = _session(tmp_path, handshake_timeout_s=ENOUGH)

    async def script(client: Any) -> Any:
        return await client.list_tools()

    run_in_process(session, script)
    events = load_cassette(session.cassette_path)
    want = [(stage, status) for stage in cassette.HANDSHAKE_STAGES
            for status in ("started", "completed")]  # fmt: skip
    if stage_facts(events) != want:
        raise AssertionError(f"not every handshake stage was recorded: {stage_facts(events)}")
    end = events[-1]
    if end.kind != "session_end" or end.handshake_outstanding is not None:
        raise AssertionError(f"a normal session ended with a stage outstanding: {end}")


def hung_session_events(tmp_path: Path, stage: str, mp: pytest.MonkeyPatch,
                        session_timeout_s: float = 60.0) -> tuple[list[Any], float]:  # fmt: skip
    from proveflow.proxy.cassette import load_cassette
    from proxyhelpers import run_in_process

    twin_args, patch, bound = HANG_MAKERS[stage]
    if patch is not None:
        patch(mp)
    session = _session(tmp_path, handshake_timeout_s=bound, session_timeout_s=session_timeout_s,
                       twin_args=twin_args)  # fmt: skip

    async def script(client: Any) -> Any:
        return await client.list_tools()

    start = time.monotonic()
    run_in_process(session, script)
    return load_cassette(session.cassette_path), time.monotonic() - start


def assert_a_hung_stage_is_named_in_the_cassette(tmp_path: Path, stage: str,
                                                 session_timeout_s: float = 60.0) -> None:  # fmt: skip  # noqa: E501
    """Named check (the PROXY layer, no harness): a stage made to hang ends the session
    ``handshake_timeout`` with ``handshake_outstanding`` naming it, from the cassette ALONE:
    that stage started and never completed, and the session ended well before the session
    timeout."""
    with pytest.MonkeyPatch.context() as mp:
        events, wall = hung_session_events(tmp_path, stage, mp, session_timeout_s)
    end = events[-1]
    if end.kind != "session_end" or end.reason != "handshake_timeout":
        raise AssertionError(f"a hung {stage} did not end the session as handshake_timeout: {end}")
    if end.handshake_outstanding != stage:
        raise AssertionError(f"the cassette names {end.handshake_outstanding!r}, not {stage!r}")
    facts = stage_facts(events)
    if facts[-1] != (stage, "started") or (stage, "completed") in facts:
        raise AssertionError(
            f"the cassette does not show {stage} started and never completed: {facts}"
        )
    if wall >= session_timeout_s:
        raise AssertionError(
            f"the hung {stage} was not bounded below the session timeout ({wall:.1f} s)"
        )


def assert_every_hung_stage_is_named(tmp_path: Path) -> None:
    """Named check: HANG_MAKERS covers EXACTLY cassette.HANDSHAKE_STAGES, and each stage made
    to hang is named in the cassette."""
    from proveflow.proxy import cassette

    if set(HANG_MAKERS) != set(cassette.HANDSHAKE_STAGES):
        raise AssertionError(
            f"stages without a hang test: {set(cassette.HANDSHAKE_STAGES) ^ set(HANG_MAKERS)}"
        )
    for stage in cassette.HANDSHAKE_STAGES:
        (tmp_path / stage).mkdir()
        assert_a_hung_stage_is_named_in_the_cassette(tmp_path / stage, stage)


def _leaves(exc: BaseException | None) -> list[BaseException]:
    if exc is None:
        return []
    if isinstance(exc, BaseExceptionGroup):
        return [leaf for inner in exc.exceptions for leaf in _leaves(inner)]
    return [exc]


def _run_harness(sessions: list[Any], outer_s: float) -> BaseException | None:
    from proveflow.runner.harness import running_proxies

    async def go() -> None:
        with anyio.fail_after(outer_s):
            async with running_proxies([("twin", s) for s in sessions],
                                       parent_env=dict(os.environ)):  # fmt: skip
                pass

    try:
        anyio.run(go)
    except BaseException as exc:
        return exc
    return None


def assert_the_harness_bounds_a_proxy_that_never_answers(tmp_path: Path) -> None:
    """Named check (the HARNESS layer, the proxy layer absent): a proxy that never answers the
    agent's initialize at all makes running_proxies raise ProxyStartupTimeout within its bound,
    instead of waiting forever."""
    from proveflow.proxy.cassette import HANDSHAKE_STAGES
    from proveflow.runner import harness

    session = _session(tmp_path, handshake_timeout_s=0.2)
    # The EXPECTED bound, from the stated derivation's constants, NOT from startup_bound_s
    # itself: a mutated startup_bound_s must not also move this check's own outer bound.
    bound = (len(HANDSHAKE_STAGES) + 1) * 0.2 * harness.HARNESS_MARGIN
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(harness, "serve", lambda *a, **k: _hang())
        start = time.monotonic()
        raised = _run_harness([session], outer_s=bound + 20.0)
    names = [type(e).__name__ for e in _leaves(raised)]
    if "ProxyStartupTimeout" not in names:
        raise AssertionError(f"the harness never gave up on a mute proxy (raised {names})")
    if time.monotonic() - start > bound + 10.0:
        raise AssertionError("the harness gave up, but long after its bound")


def assert_the_proxy_names_the_stage_before_the_harness_gives_up(tmp_path: Path) -> None:
    """Named check (the LAYERING): with BOTH layers on and the twin never answering
    initialize, the PROXY fires first and names the stage in the cassette; the harness's
    backstop does NOT fire (it would name no stage)."""
    from proveflow.proxy.cassette import load_cassette

    session = _session(tmp_path, handshake_timeout_s=QUICK, twin_args=("--hang-initialize",))
    raised = _run_harness([session], outer_s=60.0)
    names = [type(e).__name__ for e in _leaves(raised)]
    if "ProxyStartupTimeout" in names:
        raise AssertionError("the harness fired before the proxy could name the stage")
    end = load_cassette(session.cassette_path)[-1]
    if (end.reason, end.handshake_outstanding) != ("handshake_timeout", "initialize"):
        raise AssertionError(
            f"the proxy did not name the outstanding stage: {end} (raised {names})"
        )


def assert_the_harness_bound_exceeds_the_proxy_bound_for_a_range() -> None:
    """Named check: for a RANGE of handshake timeouts, not only the default, the harness's
    bound is above the proxy's worst case, so the proxy (which names the stage) fires first."""
    from proveflow.runner import harness

    for t in (0.1, 0.5, 1.0, 5.0, 30.0, 60.0, 120.0, 600.0):
        if not harness.startup_bound_s(t) > harness.proxy_handshake_bound_s(t):
            raise AssertionError(f"harness bound {harness.startup_bound_s(t)} <= proxy bound "
                                 f"{harness.proxy_handshake_bound_s(t)} at handshake timeout {t}")  # fmt: skip  # noqa: E501


def assert_a_handshake_timeout_reads_as_an_early_stop(tmp_path: Path) -> None:
    """Named check (D4): the oracle, UNEDITED, reads a handshake_timeout session as an early
    stop (rules._stopped_early: every reason but agent_closed), and evaluates it without error."""
    from proveflow.oracle import rules

    with pytest.MonkeyPatch.context() as mp:
        events, _ = hung_session_events(tmp_path, "initialize", mp)
    if not rules._stopped_early(events):
        raise AssertionError("the oracle did not read a handshake_timeout session as an early stop")
    rules.evaluate(events)  # raises on an incomplete cassette; a handshake timeout is complete


def handshake_trial(tmp_path: Path, mp: pytest.MonkeyPatch) -> Any:
    """A REAL run_trial (committed clean_utility scenario, generated twins, real proxies) whose
    upstream tools/list hangs, with a short per-stage bound."""
    from proveflow.config import ProviderConfig
    from proveflow.proxy import policy as policy_module
    from proveflow.proxy.session import ProxyLimits
    from proveflow.runner import trial
    from proveflow.runner.limits import RunBudget
    from runnerchecks import AUTHORED, fixture_scenario

    _patch_tools_list(mp)
    real = trial._sessions
    mp.setattr(trial, "_sessions", lambda *a, **k: [
        (n, s.model_copy(update={"limits": ProxyLimits(handshake_timeout_s=ENOUGH)}))
        for n, s in real(*a, **k)])  # fmt: skip

    class NeverCalled:
        async def complete(self, body: Any) -> Any:
            raise AssertionError("the LLM was called: the trial got past proxy startup")

    async def attempt(key: str, trial_id: str, budget: Any) -> Any:
        return await trial.run_trial(
            fixture_scenario("clean_utility"), trial_id=trial_id, llm=NeverCalled(),
            provider=ProviderConfig(**AUTHORED), temperature=0.0, seed=0, out_dir=tmp_path,
            twin_dir=policy_module.TWIN_ROOT, budget=budget, parent_env=dict(os.environ),
        )  # fmt: skip

    return attempt, RunBudget


def assert_a_handshake_timeout_writes_no_trial_end(tmp_path: Path) -> None:
    """Named check (Q3a): a handshake timeout reaches the runner as an EXCEPTION, never as a
    trial_end reason: the transcript is trial_start alone, and the cassette names the stage. A
    change that routes it to trial_end without updating the campaign's reason sets fails here."""
    from proveflow.proxy.cassette import load_cassette
    from proveflow.runner.transcript import load_transcript

    with pytest.MonkeyPatch.context() as mp:
        attempt, budget = handshake_trial(tmp_path, mp)
        raised: BaseException | None = None
        try:
            anyio.run(attempt, "t1", "t1-a1", budget())
        except BaseException as exc:  # EXPECTED: the handshake timeout surfaces as an exception
            raised = exc
        if raised is None:
            raise AssertionError("a handshake timeout did not raise out of run_trial")
    kinds = [e.kind for e in load_transcript(tmp_path / "t1-a1.transcript.jsonl")]
    if kinds != ["trial_start"]:
        raise AssertionError(f"a handshake timeout wrote more than trial_start: {kinds}")
    ends = [load_cassette(p)[-1] for p in sorted(tmp_path.glob("t1-a1.*.cassette.jsonl"))]
    if ("handshake_timeout", "tools_list") not in [
        (e.reason, e.handshake_outstanding) for e in ends
    ]:
        raise AssertionError(f"no cassette names the outstanding stage: {ends}")


def assert_the_campaign_files_a_handshake_timeout_as_a_failure(tmp_path: Path) -> None:
    """Named check (Q3b): the campaign files a handshake timeout as a FAILED attempt via
    Attempt.exception, never a result, and the budget ledger still counts that attempt (its
    usage read from its transcript: 0 tokens, since no LLM request was made)."""
    from proveflow.runner.campaign import (
        AttemptFailed,
        budget_spent,
        load_state,
        results,
        run_campaign,
    )

    out = tmp_path / "out"
    out.mkdir()
    with pytest.MonkeyPatch.context() as mp:
        attempt, _ = handshake_trial(out, mp)

        async def go() -> Any:
            return await run_campaign(["t1"], campaign_id="c1", state_path=tmp_path / "s.json",
                                      out_dir=out, budget_total=500_000, attempt=attempt)  # fmt: skip  # noqa: E501

        try:
            anyio.run(go)
        except AttemptFailed:
            pass
        else:
            raise AssertionError("a handshake timeout did not stop the campaign")
    state = load_state(tmp_path / "s.json")
    got = [(a.status, a.reason, (a.exception or "")[:14], a.usage_source, a.tokens_in + a.tokens_out)  # noqa: E501
           for a in state.attempts]  # fmt: skip
    if got != [("failed", None, "ExceptionGroup", "transcript", 0)] or results(state):
        raise AssertionError(
            f"a handshake timeout was not filed as a failure with its usage: {got}"
        )
    if budget_spent(state) != 0 or len(state.attempts) != 1:
        raise AssertionError("the budget ledger does not count the handshake-timeout attempt")


def assert_a_v3_cassette_is_refused(tmp_path: Path) -> None:
    """Named check (Q1a): a schema-3 cassette is REFUSED (fail closed, no shim), with a message
    naming the file's version and the one this proveflow reads, so a v3 file can never be
    misread as v4."""
    import json

    from proveflow.proxy.cassette import (
        SCHEMA_VERSION,
        CassetteError,
        canonical,
        digest,
        load_cassette,
    )

    body = {"schema_version": 3, "seq": 0, "prev_sha256": "0" * 64, "kind": "error",
            "error_kind": "x", "detail": "y", "truncated": False}  # fmt: skip
    body["sha256"] = digest(body)
    path = tmp_path / "v3.cassette.jsonl"
    path.write_bytes((canonical(body) + chr(10)).encode("utf-8"))
    try:
        load_cassette(path)
    except CassetteError as exc:
        text = str(exc)
        if "3" not in text or f"reads {SCHEMA_VERSION}" not in text:
            raise AssertionError(f"the refusal does not name both versions: {text}") from None
        return
    raise AssertionError(
        f"a schema-3 cassette was read by a schema-{SCHEMA_VERSION} proveflow: {json.dumps(body)}"
    )
