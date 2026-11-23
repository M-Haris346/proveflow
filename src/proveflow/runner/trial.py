"""One trial end to end (Phase 5): twins -> N proxies -> agent -> transcript -> oracle.

Layout of a trial in ``out_dir`` (every name a basename, so a transcript never carries a
path):
* ``<trial_id>.transcript.jsonl``       the runner's hash-chained record (evidence)
* ``<trial_id>.<server>.cassette.jsonl`` one per proxy, written by the proxy (evidence)
* ``<trial_id>.timings.json``            NON-EVIDENCE sidecar: wall-clock latency, which
                                         cannot be in any hashed chain (R-B3)
Twins are written into ``twin_dir`` (inside TWIN_ROOT, layer A).

The budget is reserved BEFORE anything is created (``BudgetExhausted`` = nothing started).
After the agent stops, every proxy has closed with ``session_end`` and the transcript's
``trial_end`` references each cassette by its final chain hash. The injection channel is
verified (F9) before any verdict; an invalid trial raises ``InvalidTrial``.

``replay_trial`` re-runs a recorded trial with ``ReplayChatClient`` (no network): fresh
twins (same seeds), fresh proxies, a NEW transcript. It requires the recorded timings
sidecar for ``latency_ms`` and raises ``MissingTimings`` without it; a fabricated latency
would be a published number nobody measured.
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from proveflow.config import ProviderConfig
from proveflow.core.trials import Trial, Verdict
from proveflow.oracle.rules import TrialFindings, evaluate_trial, to_verdict
from proveflow.proxy.cassette import load_cassette
from proveflow.proxy.policy import TwinUpstream
from proveflow.proxy.session import ProxySession
from proveflow.runner.agent import AgentOutcome, run_agent
from proveflow.runner.harness import running_proxies
from proveflow.runner.limits import RunBudget, TrialLimits
from proveflow.runner.llm import ChatClient, ChatResponse, ReplayChatClient, ReplayMismatch
from proveflow.runner.routing import RoutingTable
from proveflow.runner.scenario import Scenario
from proveflow.runner.transcript import LlmResponse, TranscriptWriter, load_transcript
from proveflow.runner.utility import evaluate_utility
from proveflow.runner.validity import InvalidTrial, injection_channel_violations
from proveflow.twin.generator import TwinBuild, generate_twin, twin_slug, write_twin

TIMINGS_NOTE = (
    "NON-EVIDENCE: wall-clock latency of this trial. Not part of any hashed chain, because "
    "wall-clock values cannot be (ADR-008); bound to the transcript by its final hash."
)


class MissingTimings(RuntimeError):
    """A replayed trial has no recorded timings sidecar; latency_ms cannot be reported."""


class TimingsMismatch(RuntimeError):
    """The timings sidecar does not belong to this transcript."""


@dataclass(frozen=True)
class TrialResult:
    trial: Trial
    outcome: AgentOutcome
    findings: TrialFindings
    utility: bool
    utility_predicate: str
    verdict: Verdict
    transcript: Path
    cassettes: tuple[Path, ...]
    timings: Path
    latency_recorded: bool  # True: latency_ms came from a recorded sidecar (replay)


class _TimedClient:
    def __init__(self, inner: ChatClient) -> None:
        self.inner = inner
        self.ms: list[float] = []

    async def complete(self, body: dict[str, Any]) -> ChatResponse:
        start = time.perf_counter()
        try:
            return await self.inner.complete(body)
        finally:
            self.ms.append((time.perf_counter() - start) * 1000.0)


def _build_twins(scenario: Scenario, twin_dir: Path, trial_id: str) -> dict[str, TwinBuild]:
    builds: dict[str, TwinBuild] = {}
    for server in scenario.servers:
        build = generate_twin(server.name, server.tools, seed=server.seed)
        if not (twin_dir / build.filename).exists():
            write_twin(build, twin_dir)
        builds[server.name] = build
    return builds


def _sessions(
    scenario: Scenario, builds: Mapping[str, TwinBuild], twin_dir: Path, out_dir: Path,
    trial_id: str,
) -> list[tuple[str, ProxySession]]:  # fmt: skip
    out: list[tuple[str, ProxySession]] = []
    for server in scenario.servers:
        build = builds[server.name]
        slug = twin_slug(server.name)
        out.append((server.name, ProxySession(
            session_id=f"{trial_id}.{slug}"[:64],
            upstream=TwinUpstream(name=slug, argv=(sys.executable, str(twin_dir / build.filename))),
            twin_sha256=build.sha256,
            tools=server.tools,
            attack=scenario.attack if server.name == scenario.attack_server else None,
            honey=build.honey,
            cassette_path=(out_dir / f"{trial_id}.{slug}.cassette.jsonl").resolve(),
        )))  # fmt: skip
    return out


def _transcript_hash(path: Path) -> str:
    return load_transcript(path)[-1].sha256


def read_timings(path: Path, transcript: Path) -> float:
    if not path.is_file():
        raise MissingTimings(f"no timings sidecar {path.name}: latency_ms cannot be reported")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("transcript_sha256") != _transcript_hash(transcript):
        raise TimingsMismatch(f"{path.name} does not belong to {transcript.name}")
    return float(data["latency_ms"])


async def run_trial(
    scenario: Scenario,
    *,
    trial_id: str,
    llm: ChatClient,
    provider: ProviderConfig,
    temperature: float,
    seed: int,
    out_dir: Path,
    twin_dir: Path,
    budget: RunBudget,
    parent_env: Mapping[str, str],
    limits: TrialLimits | None = None,
    recorded_latency_ms: float | None = None,
) -> TrialResult:
    limits = limits or TrialLimits()
    budget.reserve(limits)  # BudgetExhausted: nothing has been created
    builds = _build_twins(scenario, twin_dir, trial_id)
    sessions = _sessions(scenario, builds, twin_dir, out_dir, trial_id)
    transcript = out_dir / f"{trial_id}.transcript.jsonl"
    writer = TranscriptWriter(transcript)
    sent_seed = seed if provider.send_seed else None
    writer.emit(
        "trial_start",
        trial_id=trial_id,
        scenario_id=scenario.id,
        provider={"name": provider.name, "base_url": provider.base_url, "model": provider.model},
        parameters={
            "temperature": temperature,
            "max_tokens": limits.max_tokens_per_request,
            "seed": seed,
            "seed_sent": sent_seed is not None,
        },
        limits=limits.model_dump(mode="json"),
        budget_remaining=budget.remaining,
        servers=[{"server": name, "session_id": s.session_id} for name, s in sessions],
    )
    timed = _TimedClient(llm)
    try:
        async with running_proxies(sessions, parent_env=parent_env) as handles:
            proxy_outcomes = [(h.session.session_id, h.outcome) for h in handles]
            routing = RoutingTable.build(
                [(h.server, h.session.session_id, h.tools) for h in handles]
            )
            outcome = await run_agent(
                llm=timed, model=provider.model, temperature=temperature, seed=sent_seed,
                system_prompt=scenario.system_prompt, task=scenario.task, routing=routing,
                proxies={h.session.session_id: h for h in handles}, limits=limits, record=writer,
            )  # fmt: skip
        cassettes = tuple(s.cassette_path for _, s in sessions)
        refs = [{"session_id": s.session_id, "server": name, "file": s.cassette_path.name,
                 "final_sha256": load_cassette(s.cassette_path)[-1].sha256}
                for name, s in sessions]  # fmt: skip
        writer.emit("trial_end", reason=outcome.reason, tokens_in=outcome.tokens_in,
                    tokens_out=outcome.tokens_out, cassettes=refs)  # fmt: skip
    finally:
        writer.close()
        budget.spend(_spent(transcript))
    events = load_transcript(transcript)
    violations = injection_channel_violations(events, scenario.attack)
    if violations:
        raise InvalidTrial("; ".join(violations))
    findings = evaluate_trial(list(cassettes), trial_id=trial_id,
                              transcript=[e.model_dump(mode="json") for e in events])  # fmt: skip
    markers = {(name, tool): m for name, b in builds.items() for tool, m in b.markers.items()}
    utility = evaluate_utility(scenario.utility.predicate, scenario.utility.params, events, markers)
    measured = sum(timed.ms)
    timings = out_dir / f"{trial_id}.timings.json"
    with timings.open("x", encoding="utf-8") as fh:
        json.dump({"_note": TIMINGS_NOTE, "trial_id": trial_id,
                   "transcript_sha256": events[-1].sha256, "latency_ms": measured,
                   "per_call_ms": timed.ms,
                   # Phase 7.0, NON-EVIDENCE: per-proxy handshake stage times (never in a
                   # cassette: ADR-008)
                   "handshake_ms": {sid: (box[0].handshake_ms if box else {})
                                    for sid, box in proxy_outcomes}}, fh, indent=2)  # fmt: skip
    latency = measured if recorded_latency_ms is None else recorded_latency_ms
    trial = Trial(id=trial_id, flow_id=scenario.flow_id, attack=scenario.attack,
                  model=provider.model, seed=seed)  # fmt: skip
    verdict = to_verdict(findings, utility=utility, tokens_in=outcome.tokens_in,
                         tokens_out=outcome.tokens_out, latency_ms=latency)  # fmt: skip
    return TrialResult(trial, outcome, findings, utility, scenario.utility.predicate, verdict,
                       transcript, cassettes, timings, recorded_latency_ms is not None)  # fmt: skip


def _spent(transcript: Path) -> int:
    """Provider-reported tokens actually recorded (F10), counted even when the trial failed."""
    total = 0
    for e in load_transcript(transcript):
        if isinstance(e, LlmResponse):
            total += (e.tokens_in or 0) + (e.tokens_out or 0)
    return total


async def replay_trial(
    scenario: Scenario,
    *,
    recorded: Path,
    trial_id: str,
    provider: ProviderConfig,
    temperature: float,
    seed: int,
    out_dir: Path,
    twin_dir: Path,
    parent_env: Mapping[str, str],
    recorded_timings: Path | None = None,
    limits: TrialLimits | None = None,
) -> TrialResult:
    """Re-run a recorded trial without the network. Raises ``MissingTimings`` when the
    recorded timings sidecar is absent, and ``ReplayMismatch`` when the run diverges."""
    timings_path = recorded_timings or recorded.with_name(
        recorded.name.replace(".transcript.jsonl", ".timings.json")
    )
    latency = read_timings(timings_path, recorded)  # fails loudly, never defaults to 0
    replay = ReplayChatClient(load_transcript(recorded))
    result = await run_trial(
        scenario, trial_id=trial_id, llm=replay, provider=provider, temperature=temperature,
        seed=seed, out_dir=out_dir, twin_dir=twin_dir, budget=RunBudget(), parent_env=parent_env,
        limits=limits, recorded_latency_ms=latency,
    )  # fmt: skip
    if result.outcome.reason == "replay_mismatch" or not replay.exhausted:
        raise ReplayMismatch(f"replay of {recorded.name} diverged ({result.outcome.reason})")
    return result


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


__all__: Sequence[str] = (
    "InvalidTrial", "MissingTimings", "TimingsMismatch", "TrialResult", "read_timings",
    "replay_trial", "run_trial",
)  # fmt: skip
