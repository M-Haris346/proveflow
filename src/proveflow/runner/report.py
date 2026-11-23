"""Campaign aggregation and the report (Phase 7.2). Statistics only: no record text, no payload
text, no endpoint ever enters a report.

* THE RESULTS LEDGER IS THE ONLY SOURCE OF COUNTED TRIALS (``runner.campaign.results``).
  ``aggregate`` takes a CampaignState and nothing else, never a transcript: ``run_trial`` gives a
  verdict (compromised=false) to rate-limited and failed attempts too, so reading verdicts off
  transcripts would count attempts that measured nothing, in the denominator AND the numerator.
* PER SOURCE ONLY, with a Wilson 95% interval per source (``stats.intervals.wilson``). There is
  NO pooled headline figure anywhere: the corpus is 72.0% BIPIA (docs/METHODOLOGY.md threat 13),
  so a pooled rate would mostly measure one project's authoring style.
* Every report carries ``LOWER_BOUND_NOTE``, next to the numbers: R2 and R3 are
  capability-dependent LOWER BOUNDS, so every compromise rate is a lower bound.
* Each source's COUNTED trials are also broken down by end reason (``ended_by``): limit-ended
  trials count, so their number per reason is printed beside every rate (docs/BACKLOG.md).
* The outcomes that are NOT counted (rate-limited, failed, unclassified, interrupted) are
  reported ALONGSIDE the rates, per source, so a reader sees what was excluded.
* A campaign whose model side is SCRIPTED carries ``SCRIPTED_NOTE`` and can NEVER be written
  under docs/results/ (``write_report`` refuses): a scripted provider does not react to
  payloads, so its rates measure the script, not attack success. A campaign whose model side
  was never recorded cannot be aggregated at all (fail closed).
* Written as canonical JSON with explicit LF bytes, so committed evidence does not depend on
  the author's OS.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from proveflow.core._base import FrozenModel
from proveflow.runner.campaign import FAILED_REASONS, Attempt, CampaignState, ModelSide, results
from proveflow.stats.intervals import wilson

REPORT_SCHEMA = 1
LOWER_BOUND_NOTE = (
    "R2 and R3 are capability-dependent LOWER BOUNDS (docs/METHODOLOGY.md, threats 10 and 13): "
    "every compromise rate in this report is a lower bound on what these payloads could "
    "achieve, not an attack-success rate. ZERO REAL POSITIVES until a real campaign shows one."
)
SCRIPTED_NOTE = (
    "The model side is SCRIPTED: a scripted provider does not react to payloads, so these "
    "rates measure the script, not attack success."
)
PER_SOURCE_NOTE = (
    "Rates are PER SOURCE only and are never pooled: the corpus is 72.0% BIPIA "
    "(docs/METHODOLOGY.md threat 13)."
)


class ReportError(ValueError):
    """The campaign cannot be reported as asked (fail closed)."""


class ScriptedEvidenceRefused(ReportError):
    """Scripted data must never be written where real evidence lives (docs/results/)."""


class Excluded(FrozenModel):
    """Attempts of one source that are NOT counted, by why."""

    rate_limited: int = 0
    failed: int = 0
    unclassified: int = 0
    interrupted: int = 0


class SourceRow(FrozenModel):
    source_dataset: str
    population: int  # records of this source the sampler could draw from
    drawn: int  # records drawn (the sampling fraction is drawn / population)
    trials: int  # COMPLETED trials in the results ledger: the denominator
    compromised: int
    rate: float | None  # compromised / trials; None with no trials
    wilson95_low: float | None
    wilson95_high: float | None
    # Each COUNTED trial by its end reason (docs/BACKLOG.md "Limit-ended trials are counted
    # results"): a limit:* trial counts as not compromised even if a compromise would have come
    # after the cap, and limit:wall_clock depends on provider latency. Printed beside the rate.
    ended_by: dict[str, int]
    excluded: Excluded


class CampaignReport(FrozenModel):
    schema_version: Literal[1] = 1  # REPORT_SCHEMA
    campaign_id: str
    model_side: ModelSide
    sampling_seed: int | None
    per_source: tuple[SourceRow, ...] = Field(min_length=1)
    notes: tuple[str, ...]


def _excluded(state: CampaignState, source: str) -> Excluded:
    counts = {"rate_limited": 0, "failed": 0, "unclassified": 0, "interrupted": 0}
    for a in state.attempts:
        if state.cells[a.trial_key].source_dataset != source:
            continue
        if a.status == "rate_limited":
            counts["rate_limited"] += 1
        elif a.status == "interrupted":
            counts["interrupted"] += 1
        elif a.status == "failed":
            known = a.exception is not None or a.reason in FAILED_REASONS
            counts["failed" if known else "unclassified"] += 1
    return Excluded(**counts)


def counted_trials(state: CampaignState) -> list[tuple[str, Attempt]]:
    """(trial key, attempt) for every COUNTED trial: the results ledger, nothing else. Counting
    one per attempt (or one per transcript on disk, the same thing) is the D7 defect."""
    return list(results(state).items())


def ended_by(trials: list[Attempt]) -> dict[str, int]:
    """Counted trials per end reason (every limit:* reason kept apart from final_answer)."""
    out: dict[str, int] = {}
    for a in trials:
        out[a.reason or "?"] = out.get(a.reason or "?", 0) + 1
    return dict(sorted(out.items()))


def aggregate(state: CampaignState) -> CampaignReport:
    """Per-source Wilson rates from THE RESULTS LEDGER ONLY (this function takes no path and
    reads no transcript)."""
    if state.model_side is None:
        raise ReportError("the campaign's model side was never recorded: it cannot be reported")
    if not state.cells:
        raise ReportError("the campaign has no cells: it was not run by the engine")
    counted = counted_trials(state)
    sources = sorted({c.source_dataset for c in state.cells.values()})
    rows: list[SourceRow] = []
    for source in sources:
        mine = [a for k, a in counted if state.cells[k].source_dataset == source]
        trials = len(mine)
        hits = sum(1 for a in mine if (a.verdict or {}).get("compromised") is True)
        interval = wilson(hits, trials) if trials else None
        draw = state.sampling.per_source.get(source) if state.sampling else None
        rows.append(SourceRow(
            source_dataset=source, population=draw.population if draw else 0,
            drawn=draw.drawn if draw else 0, trials=trials, compromised=hits,
            rate=(hits / trials) if trials else None,
            wilson95_low=interval.low if interval else None,
            wilson95_high=interval.high if interval else None,
            ended_by=ended_by(mine), excluded=_excluded(state, source),
        ))  # fmt: skip
    notes = [LOWER_BOUND_NOTE, PER_SOURCE_NOTE]
    if state.model_side == "scripted":
        notes.append(SCRIPTED_NOTE)
    return CampaignReport(campaign_id=state.campaign_id, model_side=state.model_side,
                          sampling_seed=state.sampling.seed if state.sampling else None,
                          per_source=tuple(rows), notes=tuple(notes))  # fmt: skip


def report_bytes(report: CampaignReport) -> bytes:
    """Canonical JSON, explicit LF, UTF-8: the same bytes on every OS."""
    body: Any = report.model_dump(mode="json")
    return (json.dumps(body, indent=2, sort_keys=True, ensure_ascii=False) + chr(10)).encode(
        "utf-8"
    )


def _under_docs_results(path: Path) -> bool:
    parts = [p.casefold() for p in path.resolve().parts]
    return any(parts[i : i + 2] == ["docs", "results"] for i in range(len(parts) - 1))


def write_report(report: CampaignReport, path: Path) -> None:
    """Write ``report`` as LF bytes. SCRIPTED data is refused under docs/results/."""
    if report.model_side == "scripted" and _under_docs_results(path):
        raise ScriptedEvidenceRefused(
            f"{path}: a SCRIPTED campaign's report may not be written under docs/results/ "
            "(it measures the script, not attack success)"
        )
    path.write_bytes(report_bytes(report))


def format_report(report: CampaignReport) -> str:
    """The human-readable report: one line per source, the notes right beside the numbers."""
    lines = [f"campaign {report.campaign_id} (model side: {report.model_side.upper()})"]
    for r in report.per_source:
        if r.trials:
            rate = (f"{r.compromised}/{r.trials} compromised, Wilson 95% "
                    f"[{r.wilson95_low:.3f}, {r.wilson95_high:.3f}]")  # fmt: skip
        else:
            rate = "no completed trials"
        x = r.excluded
        ended = ", ".join(f"{n} {reason}" for reason, n in r.ended_by.items()) or "none"
        lines.append(
            f"  {r.source_dataset}: {rate}; counted trials ended: {ended}; "
            f"drawn {r.drawn} of {r.population}; NOT counted: "
            f"{x.rate_limited} rate-limited, {x.failed} failed, {x.unclassified} unclassified, "
            f"{x.interrupted} interrupted"
        )
    lines += [f"  NOTE: {n}" for n in report.notes]
    return chr(10).join(lines)
