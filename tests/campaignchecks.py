"""Named checks for 429, backoff and resumable campaign state (Phase 6 step 2; D3, D4).
Offline: the FAKE provider is the real HttpChatClient over httpx2.MockTransport (socket-free),
answering from a script ("ok", 429, 500). Real trials: real twins, real proxies, the committed
clean_utility scenario. Nothing here talks to a provider; no key exists (a dummy env name)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from runnerchecks import AUTHORED, _fixture_dir, fixture_scenario

USAGE = {"prompt_tokens": 100, "completion_tokens": 10}  # every "ok" response: 110 tokens
PER_OK = 110
TOTAL = 500_000  # runner.limits.RUN_TOKEN_BUDGET, the ceiling


class FakeProvider:
    """Answers each request from ``script`` in order: "ok" serves the recorded clean_utility
    response for that turn (the k-th assistant turn of the conversation) with ``USAGE``; an
    int is that HTTP status with a JSON error body. ``requests`` counts what it was SENT."""

    def __init__(self, script: list[Any]) -> None:
        from proveflow.runner.transcript import load_transcript

        recorded = load_transcript(_fixture_dir("clean_utility") / "transcript.jsonl")
        self.bodies = [e.body for e in recorded if e.kind == "llm_response"]  # type: ignore[attr-defined]
        self.script = list(script)
        self.requests = 0

    def handler(self, request: Any) -> Any:
        import httpx2

        self.requests += 1
        if not self.script:
            raise AssertionError("the fake provider's script ran out (a test bug)")
        step = self.script.pop(0)
        if isinstance(step, tuple):  # (status, Retry-After header text)
            status, header = step
            return httpx2.Response(int(status), headers={"Retry-After": header},
                                   json={"error": {"message": f"scripted {status}"}})  # fmt: skip
        if step != "ok":
            return httpx2.Response(int(step), json={"error": {"message": f"scripted {step}"}})
        messages = json.loads(request.content)["messages"]
        turn = sum(1 for m in messages if m.get("role") == "assistant")
        return httpx2.Response(200, json={**self.bodies[turn], "usage": USAGE})

    def client(self) -> Any:
        import httpx2

        from proveflow.config import ProviderConfig
        from proveflow.runner.llm import HttpChatClient

        return HttpChatClient(ProviderConfig(**AUTHORED), environ={"PF_AUTHORED_UNUSED": "x"},
                              transport=httpx2.MockTransport(self.handler))  # fmt: skip


def _leaves(exc: BaseException | None) -> list[BaseException]:
    """Every leaf exception: through nested exception groups AND the ``__cause__`` chain."""
    if exc is None:
        return []
    if isinstance(exc, BaseExceptionGroup):
        return [leaf for inner in exc.exceptions for leaf in _leaves(inner)]
    return [exc, *_leaves(exc.__cause__)]


def campaign_story(out: Path, exc: BaseException) -> str:
    """What a failed real-trial campaign check DID (BACKLOG "Real-session tests failed under
    load"): each leaf exception with its type, message, any MCP ``error`` payload and its
    innermost frames (which call failed), the cassette story of every cassette of the failing
    attempt (``proxyhelpers.cassette_story``: errors, tail, session_end reason), and that
    attempt's transcript tail. Never raises: a diagnostic must not hide the failure."""
    import re
    import traceback

    from proxyhelpers import cassette_story

    lines = ["--- campaign failure story ---"]
    for leaf in _leaves(exc):
        lines.append(f"leaf {type(leaf).__module__}.{type(leaf).__name__}: {leaf}")
        payload = getattr(leaf, "error", None)
        if payload is not None:
            lines.append(f"  error payload: {payload!r}")
        for frame in traceback.extract_tb(leaf.__traceback__)[-4:]:
            lines.append(f"  at {frame.filename}:{frame.lineno} in {frame.name}")
    found = re.match(r"([a-z0-9_]+-a[0-9]+):", str(exc))
    prefix = f"{found.group(1)}." if found else ""
    for path in sorted(out.glob(f"{prefix}*.cassette.jsonl")):
        lines.append(f"cassette {path.name}: {cassette_story(path)}")
    for path in sorted(out.glob(f"{prefix}*transcript.jsonl")):
        try:
            from proveflow.runner.transcript import load_transcript

            tail = [(e.kind, getattr(e, "error_kind", getattr(e, "reason", "")))
                    for e in load_transcript(path)][-6:]  # fmt: skip
            lines.append(f"transcript {path.name} tail: {tail}")
        except Exception as err:  # a torn transcript is itself part of the story
            lines.append(f"transcript {path.name} unreadable: {type(err).__name__}: {err}")
    if not found:
        lines.append(f"(no attempt id in {str(exc)[:80]!r}: every cassette in {out.name} shown)")
    return chr(10).join(lines)


def with_story(out: Path, run: Any) -> Any:
    """Run ``run()``; on ANY exception, attach ``campaign_story`` as an exception note (PEP 678;
    pytest prints notes with the traceback) and re-raise it unchanged. Checks that EXPECT an
    exception still catch it; an unexpected one now says which call to which twin failed."""
    try:
        return run()
    except BaseException as exc:
        try:
            exc.add_note(campaign_story(out, exc))
        except Exception as err:  # never let the diagnostic replace the failure
            exc.add_note(f"(campaign_story failed: {type(err).__name__}: {err})")
        raise


def attempt_fn(out: Path, fake: FakeProvider) -> Any:
    """One attempt = one real run_trial of clean_utility with the campaign's budget."""
    from proveflow.config import ProviderConfig
    from proveflow.proxy import policy as policy_module
    from proveflow.runner.trial import run_trial

    async def attempt(key: str, trial_id: str, budget: Any) -> Any:
        return await run_trial(
            fixture_scenario("clean_utility"), trial_id=trial_id, llm=fake.client(),
            provider=ProviderConfig(**AUTHORED), temperature=0.0, seed=0, out_dir=out,
            twin_dir=policy_module.TWIN_ROOT, budget=budget, parent_env=dict(os.environ),
        )  # fmt: skip

    return attempt


def campaign(tmp_path: Path, script: list[Any], plan: list[str], sleeps: list[float]) -> Any:
    """Run (or resume) the campaign in ``tmp_path`` against a fresh fake provider."""
    import anyio

    from proveflow.runner.campaign import run_campaign

    out = tmp_path / "out"
    out.mkdir(exist_ok=True)
    fake = FakeProvider(script)

    async def sleep(s: float) -> None:
        sleeps.append(s)

    async def go() -> Any:
        return await run_campaign(plan, campaign_id="c1", state_path=tmp_path / "c1.campaign.json",
                                  out_dir=out, budget_total=TOTAL, attempt=attempt_fn(out, fake),
                                  sleep=sleep)  # fmt: skip

    return with_story(out, lambda: anyio.run(go))


def _start(tmp_path: Path, attempt_id: str) -> Any:
    from proveflow.runner.transcript import load_transcript

    return load_transcript(tmp_path / "out" / f"{attempt_id}.transcript.jsonl")[0]


def assert_a_429_ends_the_attempt(tmp_path: Path) -> None:
    """Named check (D3): an HTTP 429 ENDS the trial attempt, recorded (error rate_limited,
    trial_end rate_limited), and is NEVER retried inside the trial: the provider received
    exactly as many requests as the transcript records, and the tokens of the turn before the
    429 are counted."""
    import anyio

    from proveflow.proxy import policy as policy_module
    from proveflow.runner.limits import RunBudget
    from proveflow.runner.transcript import load_transcript
    from proveflow.runner.trial import run_trial

    fake = FakeProvider(["ok", 429, "ok", "ok"])
    out = tmp_path / "out"
    out.mkdir()

    async def go() -> Any:
        from proveflow.config import ProviderConfig

        return await run_trial(
            fixture_scenario("clean_utility"), trial_id="r429", llm=fake.client(),
            provider=ProviderConfig(**AUTHORED), temperature=0.0, seed=0, out_dir=out,
            twin_dir=policy_module.TWIN_ROOT, budget=RunBudget(), parent_env=dict(os.environ),
        )  # fmt: skip

    result = with_story(out, lambda: anyio.run(go))
    events = load_transcript(result.transcript)
    sent = sum(1 for e in events if e.kind == "llm_request")
    if fake.requests != sent:
        raise AssertionError(
            f"a 429 was retried inside the trial: the provider got {fake.requests} requests, "
            f"the transcript records {sent}"
        )
    errors = [e.error_kind for e in events if e.kind == "error"]  # type: ignore[attr-defined]
    if result.outcome.reason != "rate_limited" or events[-1].reason != "rate_limited":  # type: ignore[attr-defined]
        raise AssertionError(f"a 429 did not end the attempt: {result.outcome.reason}")
    if errors != ["rate_limited"] or (result.outcome.tokens_in, result.outcome.tokens_out) != (
        100,
        10,
    ):
        raise AssertionError(f"the 429 attempt was not recorded as such: {errors}, "
                             f"{result.outcome.tokens_in}/{result.outcome.tokens_out}")  # fmt: skip


def assert_resume_rebuilds_the_budget_from_attempt_usage(tmp_path: Path) -> None:
    """Named check (THE D4 pin): resume a campaign whose FAILED attempts spent tokens. Run 1:
    t1-a1 is 429-ended after one turn (110 tokens), t1-a2 completes (220), t2-a1 fails with an
    HTTP 500 after one turn (110) and stops the campaign. Run 2 resumes: the budget t2-a2
    starts with (its transcript's trial_start.budget_remaining) is TOTAL - 440, i.e. rebuilt
    from EVERY attempt's usage in the state file; rebuilt from completed trials it would be
    TOTAL - 220. The results ledger then holds t1 and t2, each once."""
    from proveflow.runner.campaign import (
        AttemptFailed,
        budget_spent,
        load_state,
        results,
    )

    sleeps: list[float] = []
    try:
        campaign(tmp_path, ["ok", 429, "ok", "ok", "ok", 500], ["t1", "t2"], sleeps)
    except AttemptFailed:
        pass
    else:
        raise AssertionError("premise broken: run 1 did not stop on the failed attempt")
    state = load_state(tmp_path / "c1.campaign.json")
    unfinished = [(a.attempt_id, a.status, a.tokens_in + a.tokens_out) for a in state.attempts
                  if a.status != "completed"]  # fmt: skip
    if unfinished != [("t1-a1", "rate_limited", PER_OK), ("t2-a1", "failed", PER_OK)]:
        raise AssertionError(f"premise broken: the failed attempts did not spend: {unfinished}")
    campaign(tmp_path, ["ok", "ok"], ["t1", "t2"], sleeps)
    resumed = _start(tmp_path, "t2-a2").budget_remaining
    every, completed_only = TOTAL - 4 * PER_OK, TOTAL - 2 * PER_OK
    if resumed != every:
        raise AssertionError(
            f"the resumed budget was not rebuilt from every attempt's usage: t2-a2 started "
            f"with {resumed}, want {every} (from completed trials only it is {completed_only})"
        )
    final = load_state(tmp_path / "c1.campaign.json")
    if budget_spent(final) != 6 * PER_OK or list(results(final)) != ["t1", "t2"]:
        raise AssertionError(f"ledgers after resume: {budget_spent(final)}, {list(results(final))}")
    if [a.attempt_id for a in results(final).values()] != ["t1-a2", "t2-a2"]:
        raise AssertionError("a result is not the completed attempt")


RETRY_AFTER_CASES: dict[str | None, str | None] = {
    # header sent -> the exact text RateLimited must carry (extraction only; no parsing here)
    "30": "30",
    "1": "1",
    "soon, maybe": "soon, maybe",
    None: None,  # absent
    "Fri, 31 Dec 1999 23:59:59 GMT": "Fri, 31 Dec 1999 23:59:59 GMT",  # HTTP-date form
    "601": "601",  # over RETRY_AFTER_MAX_S: carried as text, ignored by the campaign
    "7" * 100: "7" * 64,  # clipped to RETRY_AFTER_HEADER_MAX
}


def assert_429_carries_the_exact_retry_after_text() -> None:
    """Named check (claim a: header EXTRACTION, at the client, no trial): the real
    HttpChatClient over the mock transport, a 429 carrying each header form, raises
    RateLimited carrying exactly that text (clipped at 64), and None when it is absent."""
    import anyio
    import httpx2

    from proveflow.config import ProviderConfig
    from proveflow.runner.llm import HttpChatClient, RateLimited

    for sent, want in RETRY_AFTER_CASES.items():

        def handler(request: Any, h: str | None = sent) -> Any:
            return httpx2.Response(429, headers={} if h is None else {"Retry-After": h}, json={})

        client = HttpChatClient(ProviderConfig(**AUTHORED), environ={"PF_AUTHORED_UNUSED": "x"},
                                transport=httpx2.MockTransport(handler))  # fmt: skip
        try:
            anyio.run(client.complete, {"model": "m"})
        except RateLimited as exc:
            if exc.retry_after_header != want:
                raise AssertionError(
                    f"Retry-After {sent!r} was carried as {exc.retry_after_header!r}, want {want!r}"
                ) from None
            continue
        raise AssertionError(f"a 429 with Retry-After {sent!r} did not raise RateLimited")


def assert_retry_after_reaches_the_outcome(tmp_path: Path) -> None:
    """Named check (claim b: the WIRING, on ONE real trial: real twins, real proxies, the real
    client over the mock transport): a 429 with Retry-After: 30 ends the trial rate_limited
    and the agent's outcome carries retry_after_header == "30", which is what the campaign
    reads to decide the wait."""
    import anyio

    from proveflow.config import ProviderConfig
    from proveflow.proxy import policy as policy_module
    from proveflow.runner.limits import RunBudget
    from proveflow.runner.trial import run_trial

    fake = FakeProvider([(429, "30")])
    out = tmp_path / "out"
    out.mkdir()

    async def go() -> Any:
        return await run_trial(
            fixture_scenario("clean_utility"), trial_id="ra30", llm=fake.client(),
            provider=ProviderConfig(**AUTHORED), temperature=0.0, seed=0, out_dir=out,
            twin_dir=policy_module.TWIN_ROOT, budget=RunBudget(), parent_env=dict(os.environ),
        )  # fmt: skip

    result = with_story(out, lambda: anyio.run(go))
    got = (result.outcome.reason, result.outcome.retry_after_header)
    if got != ("rate_limited", "30"):
        raise AssertionError(f"Retry-After did not reach the outcome: {got}")


def assert_exactly_429_is_rate_limited() -> None:
    """Named check (an "every status" claim, so asserted over every status 400..599 the client
    can see, not sampled): exactly 429 raises RateLimited; every other raises a ProviderError
    that is NOT RateLimited."""
    import anyio
    import httpx2

    from proveflow.config import ProviderConfig
    from proveflow.runner.llm import HttpChatClient, ProviderError, RateLimited

    wrong: list[int] = []
    for status in range(400, 600):

        def handler(request: Any, s: int = status) -> Any:
            return httpx2.Response(s, json={})

        client = HttpChatClient(ProviderConfig(**AUTHORED), environ={"PF_AUTHORED_UNUSED": "x"},
                                transport=httpx2.MockTransport(handler))  # fmt: skip
        try:
            anyio.run(client.complete, {"model": "m"})
        except ProviderError as exc:
            if isinstance(exc, RateLimited) != (status == 429):
                wrong.append(status)
            continue
        wrong.append(status)
    if wrong:
        raise AssertionError(f"statuses mapped wrongly to RateLimited/ProviderError: {wrong}")
