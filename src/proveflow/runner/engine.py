"""The campaign engine (Phase 7.1). OFFLINE machinery: it runs nothing paid by itself; what the
model side is (scripted, replay, a real provider) is the caller's ``attempt_for``, recorded as the
campaign's ``model_side`` in the state file.

* SAMPLING is STRATIFIED BY SOURCE and EQUAL per source (``sample_records``): the corpus is 72.0%
  BIPIA (docs/METHODOLOGY.md threat 13), so a uniform or proportional draw would mostly measure
  one project's authoring style. Each source contributes ``min(per_source_n, population)``
  records, drawn deterministically from the recorded ``seed``. The COST, stated: BIPIA's 250 are
  under-sampled relative to the others, so the result is PER-SOURCE rates at comparable
  precision; nothing is ever pooled (runner/report.py). The state file records the seed and, per
  source, the POPULATION and the DRAW, so a reader sees each source's sampling fraction.
  ``attack_family`` is NEVER a sampling or reporting axis (a per-source taxonomy: a BIPIA
  technique, an InjecAgent harm class, an AgentDojo domain; corpus/records.py).
* CELLS are (payload, carrier, goal, model); each gets one trial key. They run through the
  step-2 state machine UNCHANGED (``runner.campaign.run_campaign``): every outcome classified,
  two ledgers never derived from each other, the budget checked before each attempt, backoff
  and Retry-After honoured, resumable from the state file, fail closed on any non-429 failure.
"""

from __future__ import annotations

import random
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import Any

import anyio

from proveflow.core.attacks import Carrier, Goal
from proveflow.corpus.records import CorpusRecord
from proveflow.corpus.sources import SOURCE_PRIORITY
from proveflow.runner.campaign import (
    AttemptResult,
    CampaignState,
    CellSpec,
    ModelSide,
    SamplingRecord,
    SleepFn,
    SourceDraw,
    run_campaign,
)
from proveflow.runner.limits import RunBudget, TrialLimits

CellAttempt = Callable[[str, str, RunBudget], Awaitable[AttemptResult]]
AttemptFor = Callable[[CellSpec, CorpusRecord, Goal], CellAttempt]


def _source_rank(source: str) -> int:
    return SOURCE_PRIORITY.index(source) if source in SOURCE_PRIORITY else len(SOURCE_PRIORITY)


def sample_records(records: Sequence[CorpusRecord], *, per_source_n: int,
                   seed: int) -> tuple[list[CorpusRecord], SamplingRecord]:  # fmt: skip
    """EQUAL per source, deterministic: per source (in docs/DATASETS.md order), the records
    sorted by id, then ``random.Random(f"{seed}:{source}").sample`` of ``min(n, population)``,
    kept in id order. Reads ONLY ``source_dataset`` and ``id``: never ``attack_family``."""
    if per_source_n < 1:
        raise ValueError("per_source_n must be at least 1")
    by_source: dict[str, list[CorpusRecord]] = {}
    for r in records:
        by_source.setdefault(r.source_dataset, []).append(r)
    drawn: list[CorpusRecord] = []
    per_source: dict[str, SourceDraw] = {}
    for source in sorted(by_source, key=lambda s: (_source_rank(s), s)):
        pool = sorted(by_source[source], key=lambda r: r.id)
        k = min(per_source_n, len(pool))
        # not security: a reproducible, recorded sampling draw
        picked = random.Random(f"{seed}:{source}").sample(pool, k)  # noqa: S311
        drawn += sorted(picked, key=lambda r: r.id)
        per_source[source] = SourceDraw(population=len(pool), drawn=k)
    return drawn, SamplingRecord(seed=seed, per_source_n=per_source_n, per_source=per_source)


def plan_cells(records: Sequence[CorpusRecord], *, carriers: Sequence[Carrier],
               goals: Sequence[Goal], models: Sequence[str]) -> dict[str, CellSpec]:  # fmt: skip
    """One trial key per (payload, carrier, goal, model), in a deterministic order."""
    cells: dict[str, CellSpec] = {}
    for record in records:
        for carrier in carriers:
            for goal in goals:
                for model in models:
                    key = f"c{len(cells):04d}"
                    cells[key] = CellSpec(source_dataset=record.source_dataset,
                                          record_id=record.id, carrier=carrier.value,
                                          goal_kind=goal.kind, model=model)  # fmt: skip
    return cells


async def run_engine(
    records: Sequence[CorpusRecord],
    *,
    campaign_id: str,
    state_path: Path,
    out_dir: Path,
    budget_total: int,
    per_source_n: int,
    seed: int,
    carriers: Sequence[Carrier],
    goals: Sequence[Goal],
    models: Sequence[str],
    model_side: ModelSide,
    attempt_for: AttemptFor,
    limits: TrialLimits | None = None,
    sleep: SleepFn = anyio.sleep,
) -> CampaignState:
    """Sample, plan and run (or resume) a campaign. ``attempt_for(cell, record, goal)`` returns
    the attempt function for one cell (in production a ``run_trial`` of the instantiated
    attack; in tests a scripted one)."""
    sampled, sampling = sample_records(records, per_source_n=per_source_n, seed=seed)
    cells = plan_cells(sampled, carriers=carriers, goals=goals, models=models)
    by_id = {r.id: r for r in sampled}
    goal_of: dict[str, Goal] = {g.kind: g for g in goals}
    if len(goal_of) != len(goals):
        raise ValueError("one goal per goal kind")

    async def attempt(key: str, trial_id: str, budget: RunBudget) -> AttemptResult:
        cell = cells[key]
        return await attempt_for(cell, by_id[cell.record_id], goal_of[cell.goal_kind])(
            key, trial_id, budget
        )

    return await run_campaign(list(cells), campaign_id=campaign_id, state_path=state_path,
                              out_dir=out_dir, budget_total=budget_total, attempt=attempt,
                              limits=limits, sleep=sleep, model_side=model_side, cells=cells,
                              sampling=sampling)  # fmt: skip


def trial_attempt_for(
    template: Any,
    *,
    llm_for: Callable[[str], Any],
    provider_for: Callable[[str], Any],
    out_dir: Path,
    twin_dir: Path,
    parent_env: Any,
    temperature: float = 0.0,
    seed: int = 0,
) -> AttemptFor:
    """Production ``attempt_for``: instantiate the cell's attack (the corpus payload VERBATIM
    plus its goal clause, corpus.instantiate) into ``template`` (a Scenario with an attack
    server) and ``run_trial`` it with the cell's model."""
    from proveflow.core.attacks import Carrier as CarrierEnum
    from proveflow.corpus.instantiate import instantiate
    from proveflow.runner.scenario import Scenario
    from proveflow.runner.trial import run_trial

    def attempt_for(cell: CellSpec, record: CorpusRecord, goal: Goal) -> CellAttempt:
        async def attempt(key: str, trial_id: str, budget: RunBudget) -> AttemptResult:
            attack = instantiate(record.payload(), CarrierEnum(cell.carrier), goal)
            body = {**template.model_dump(mode="json"), "attack": attack.model_dump(mode="json")}
            scenario = Scenario.model_validate(body)  # the validators re-check F9
            return await run_trial(scenario, trial_id=trial_id, llm=llm_for(cell.model),
                                   provider=provider_for(cell.model), temperature=temperature,
                                   seed=seed, out_dir=out_dir, twin_dir=twin_dir, budget=budget,
                                   parent_env=parent_env)  # fmt: skip

        return attempt

    return attempt_for
