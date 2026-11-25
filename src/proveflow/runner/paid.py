"""DEV-ONLY campaign entry point (Phase 7.3a). Not a ``proveflow`` subcommand: no provider is
claimed as supported, and only the key holder runs ``run``.

    uv run python -m proveflow.runner.paid preflight PLAN --dry-run-root DIR [--cache DIR]
    uv run python -m proveflow.runner.paid dry-run PLAN --root DIR [--kill-at-request N]
    uv run python -m proveflow.runner.paid run PLAN --config TOML --state PATH [--yes]

(``--cache`` defaults to ``.proveflow-corpus``, the gitignored corpus cache, for all three.)

* ONE PLAN FILE feeds all three (runner/plan.py): the dry run and the paid run differ ONLY in the
  model side (scripted / provider) and the root directory. Their state files differ by design:
  ``runner.campaign._open`` refuses a state file of the other model side.
* ``preflight`` spends nothing and makes no network call: no twin, no proxy, no HTTP client. It
  prints the plan, the per-source draw, the cell count, the DRY RUN's MEASURED request bytes,
  the token ESTIMATE and the spend with its arithmetic, the price with its URLs and read date
  (from the plan file, never a remembered number), and the cap.
* ``dry-run`` runs the REAL plan on REAL twins and proxies with the SCRIPTED model side
  (runner/scripted.py); its report is SCRIPTED and is refused under docs/results/.
* ``run`` reads the key from the environment variable the config names, AT CALL TIME, through
  the existing ``HttpChatClient``; the key is never in the plan, never logged, never in a
  cassette or transcript. It REFUSES before anything is created (exit 2) when: the config's
  provider differs from the plan's; the key variable is unset; the state path is not this plan's
  state file; a root is under docs/results/. Without ``--yes`` it prints the maximum spend and
  exits (the runner.manual pattern).
* The corpus is read from the local cache only (runner/offline_corpus.py): a campaign never
  fetches.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any

import anyio

from proveflow.config import ProviderConfig, load_config
from proveflow.runner import report as report_module
from proveflow.runner.campaign import CampaignState
from proveflow.runner.engine import plan_cells, run_engine, sample_records, trial_attempt_for
from proveflow.runner.offline_corpus import cached_records
from proveflow.runner.plan import (
    EVIDENCE_RUN,
    CampaignPlan,
    PlanError,
    bytes_per_token,
    campaign_id_of,
    check_provider,
    completion_tokens_per_turn,
    load_plan,
    load_template,
    plan_sha256,
)
from proveflow.runner.scenario import Scenario

EXIT_REFUSED = 2
DRY_RUN_KEY_ENV = "PROVEFLOW_DRY_RUN_HAS_NO_KEY"  # a dry run's provider entry: never read


class Refused(SystemExit):
    """A refusal before anything is created (exit 2, the reason on stderr)."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        print(f"refused: {reason}", file=sys.stderr)
        super().__init__(EXIT_REFUSED)


# Each refusal is ONE named function, so a mutation can disable exactly one (tests/planchecks).
def under_docs_results(path: Path) -> bool:
    return report_module._under_docs_results(path)


def key_is_set(provider: ProviderConfig) -> bool:
    """Whether the key's variable is set and non-empty. The value is not kept or printed;
    ``HttpChatClient`` reads it again at call time."""
    return bool(os.environ.get(provider.api_key_env))


def state_matches(state: Path, campaign_id: str) -> bool:
    return state.name == state_path_of(state.parent, campaign_id).name


def confirmed(args: argparse.Namespace) -> bool:
    return bool(args.yes)


def state_path_of(root: Path, campaign_id: str) -> Path:
    return root / f"{campaign_id}.campaign.json"


def measure_path_of(root: Path, campaign_id: str) -> Path:
    return root / f"{campaign_id}.dryrun-measure.json"


def report_path_of(root: Path, campaign_id: str) -> Path:
    return root / f"{campaign_id}.report.json"


# --- the estimate (pure; planchecks pins its arithmetic) -------------------------------------


def estimate(plan: CampaignPlan, measured: Sequence[dict[str, int]], cells: int) -> dict[str, Any]:
    """Tokens and dollars ESTIMATED from the dry run's MEASURED request bytes, converted with the
    evidence run's measured bytes-per-token. Per turn the mean measured request size; a trial is
    the sum over the scripted turns. Output tokens per turn: the evidence run's mean."""
    by_turn: dict[int, list[int]] = {}
    for m in measured:
        by_turn.setdefault(m["turn"], []).append(m["bytes"])
    if not by_turn:
        raise PlanError("the dry-run measurement holds no request")
    turns = len(by_turn)
    mean_bytes = {t: sum(v) / len(v) for t, v in sorted(by_turn.items())}
    bpt = bytes_per_token()
    tin = round(sum(mean_bytes.values()) / bpt)
    tout = round(turns * completion_tokens_per_turn())
    price_in = Decimal(plan.price.input_usd_per_mtok)
    price_out = Decimal(plan.price.output_usd_per_mtok)
    total_in, total_out = cells * tin, cells * tout
    usd_in = Decimal(total_in) * price_in / Decimal(1_000_000)
    usd_out = Decimal(total_out) * price_out / Decimal(1_000_000)
    reservation = plan.limits.max_trial_tokens
    last_start = (cells - 1) * (tin + tout) + reservation
    return {
        "turns": turns, "mean_request_bytes": mean_bytes, "bytes_per_token": bpt,
        "tokens_in_per_trial": tin, "tokens_out_per_trial": tout,
        "tokens_per_trial": tin + tout, "total_in": total_in, "total_out": total_out,
        "usd_in": usd_in, "usd_out": usd_out, "usd_expected": usd_in + usd_out,
        "usd_hard_max": Decimal(plan.budget_total) * price_out / Decimal(1_000_000),
        "usd_all_input_max": Decimal(plan.budget_total) * price_in / Decimal(1_000_000),
        "needed_for_last_start": last_start, "fits": last_start <= plan.budget_total,
        "runaway_trials": plan.budget_total // reservation,
    }  # fmt: skip


# --- shared --------------------------------------------------------------------------------


def _load(plan_path: Path) -> tuple[CampaignPlan, Scenario, str]:
    try:
        plan = load_plan(plan_path)
        template = load_template(plan, plan_path)
    except PlanError as exc:
        raise Refused(str(exc)) from None
    return plan, template, campaign_id_of(plan)


def _engine_kwargs(plan: CampaignPlan, records: Any, campaign_id: str,
                   root: Path) -> dict[str, Any]:  # fmt: skip
    return {"records": records, "campaign_id": campaign_id,
            "state_path": state_path_of(root, campaign_id), "out_dir": root / campaign_id,
            "budget_total": plan.budget_total, "per_source_n": plan.per_source_n,
            "seed": plan.sampler_seed, "carriers": [plan.carrier], "goals": [plan.goal],
            "models": [plan.provider.model], "limits": plan.limits}  # fmt: skip


def _attempt_for(plan: CampaignPlan, template: Scenario, out_dir: Path, llm: Any,
                 provider: ProviderConfig, mitigation: Any = None) -> Any:  # fmt: skip
    from proveflow.proxy import policy

    twin_dir = policy.TWIN_ROOT / "campaign"
    twin_dir.mkdir(parents=True, exist_ok=True)
    return trial_attempt_for(template, llm_for=lambda model: llm, provider_for=lambda m: provider,
                             out_dir=out_dir, twin_dir=twin_dir, parent_env=dict(os.environ),
                             limits=plan.limits, temperature=plan.temperature,
                             seed=plan.trial_seed, mitigation=mitigation)  # fmt: skip


def _finish(plan: CampaignPlan, state: CampaignState, root: Path) -> str:
    from proveflow.runner.exposure import exposure_of

    rep = report_module.aggregate(state, exposure_of(state, root / state.campaign_id),
                                  plan.delivery)  # fmt: skip
    report_module.write_report(rep, report_path_of(root, state.campaign_id))
    return report_module.format_report(rep)


# --- subcommands ---------------------------------------------------------------------------


def cmd_preflight(args: argparse.Namespace) -> int:
    plan, _template, cid = _load(args.plan)
    records = cached_records(args.cache)
    sampled, sampling = sample_records(records, per_source_n=plan.per_source_n,
                                       seed=plan.sampler_seed)  # fmt: skip
    cells = len(plan_cells(sampled, carriers=[plan.carrier], goals=[plan.goal],
                           models=[plan.provider.model]))  # fmt: skip
    mpath = measure_path_of(args.dry_run_root, cid)
    try:
        measure = json.loads(mpath.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise Refused(
            f"no dry-run measurement for {cid} under --dry-run-root: run dry-run first"
        ) from None
    if measure.get("campaign_id") != cid or measure.get("plan_sha256") != plan_sha256(plan):
        raise Refused("the dry-run measurement belongs to another plan")
    e = estimate(plan, measure["requests"], cells)
    p = plan.price
    out = [
        f"plan {args.plan.name}  sha256 {plan_sha256(plan)}  campaign {cid}",
        f"provider {plan.provider.name} ({plan.provider.base_url}), model {plan.provider.model}, "
        f"temperature {plan.temperature}, trial seed {plan.trial_seed} "
        f"(sent: {plan.provider.send_seed}); delivery {plan.delivery.upper()}",
        f"carrier {plan.carrier.value}; goal {plan.goal.kind}; sampler seed {plan.sampler_seed}; "
        f"per source n = {plan.per_source_n}",
        *(f"  draw {s}: {d.drawn} of {d.population}" for s, d in sampling.per_source.items()),
        f"cells: {cells}",
        f"limits per trial: {plan.limits.max_tokens_in} in + {plan.limits.max_tokens_out} out = "
        f"{plan.limits.max_trial_tokens} (the reservation); cap {plan.budget_total} tokens",
        f"MEASURED (dry run, scripted, {len(measure['requests'])} requests): mean request bytes "
        "per turn " + ", ".join(f"t{t}={b:.0f}" for t, b in e["mean_request_bytes"].items()),
        f"CALIBRATION (measured, {EVIDENCE_RUN}, N = 2 requests): {e['bytes_per_token']:.3f} "
        f"bytes per prompt token; {completion_tokens_per_turn():.1f} completion tokens per turn",
        f"ESTIMATE per trial ({e['turns']} scripted turns; a real model may take more): "
        f"{e['tokens_in_per_trial']} in + {e['tokens_out_per_trial']} out = "
        f"{e['tokens_per_trial']}",
        f"ESTIMATE total: {cells} x {e['tokens_in_per_trial']} = {e['total_in']} in, {cells} x "
        f"{e['tokens_out_per_trial']} = {e['total_out']} out",
        f"PRICE (published; read {p.read_date}; the pages carry "
        f"{'no date' if p.page_date is None else 'date ' + p.page_date}): "
        f"${p.input_usd_per_mtok} per 1M in, ${p.output_usd_per_mtok} per 1M out; "
        + "; ".join(p.urls),
        f"ESTIMATED SPEND: {e['total_in']} x {p.input_usd_per_mtok} / 1e6 = ${e['usd_in']:.4f} "
        f"+ {e['total_out']} x {p.output_usd_per_mtok} / 1e6 = ${e['usd_out']:.4f} = "
        f"${e['usd_expected']:.4f}",
        f"HARD MAXIMUM at the cap: {plan.budget_total} x {p.output_usd_per_mtok} / 1e6 = "
        f"${e['usd_hard_max']:.4f} (every token at the output price; all input: "
        f"${e['usd_all_input_max']:.4f}); overshoot past the cap is at most one response",
        f"FIT: the last cell starts after {cells - 1} x {e['tokens_per_trial']} + "
        f"{plan.limits.max_trial_tokens} = {e['needed_for_last_start']} "
        f"{'<=' if e['fits'] else '>'} cap {plan.budget_total}: "
        f"{'fits' if e['fits'] else 'DOES NOT FIT'}; a runaway (every trial at its maximum) "
        f"stops after {e['runaway_trials']} trials",
        "preflight spent nothing and made no network call",
    ]
    print(chr(10).join(out))
    return 0 if e["fits"] else EXIT_REFUSED


def cmd_dry_run(args: argparse.Namespace) -> int:
    from proveflow.runner.scripted import ScriptedChatClient

    plan, template, cid = _load(args.plan)
    if under_docs_results(args.root):
        raise Refused("a dry run's root may not be under docs/results/ (it is SCRIPTED)")
    records = cached_records(args.cache)
    args.root.mkdir(parents=True, exist_ok=True)
    out_dir = args.root / cid
    out_dir.mkdir(exist_ok=True)
    chat = ScriptedChatClient(template, kill_at_request=args.kill_at_request)
    provider = ProviderConfig(name=plan.provider.name, base_url=plan.provider.base_url,
                              model=plan.provider.model, api_key_env=DRY_RUN_KEY_ENV,
                              send_seed=plan.provider.send_seed)  # fmt: skip
    attempt_for = _attempt_for(plan, template, out_dir, chat, provider)
    mpath = measure_path_of(args.root, cid)
    try:
        previous = json.loads(mpath.read_text(encoding="utf-8"))["requests"]
    except (OSError, ValueError, KeyError):
        previous = []

    async def go() -> CampaignState:
        return await run_engine(**_engine_kwargs(plan, records, cid, args.root),
                                model_side="scripted", attempt_for=attempt_for)  # fmt: skip

    try:
        state = anyio.run(go)
    finally:  # the measurement survives a (scripted) kill: a resume adds to it
        body = {"campaign_id": cid, "plan_sha256": plan_sha256(plan), "model_side": "scripted",
                "note": "request bytes MEASURED on the real plan; usage is SCRIPTED",
                "requests": previous + [{"turn": m.turn, "bytes": m.bytes}
                                        for m in chat.measured]}  # fmt: skip
        mpath.write_bytes((json.dumps(body, indent=2) + chr(10)).encode("utf-8"))
    print(_finish(plan, state, args.root))
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    plan, template, cid = _load(args.plan)
    try:
        config = load_config(args.config)
    except Exception as exc:  # ConfigError names the problem, never a value
        raise Refused(str(exc)) from None
    provider = next((p for p in config.provider if p.name == plan.provider.name), None)
    if provider is None:
        raise Refused(f"no [[provider]] named {plan.provider.name!r} in {args.config.name}")
    try:
        check_provider(plan, provider)
    except PlanError as exc:
        raise Refused(str(exc)) from None
    if not key_is_set(provider):
        raise Refused(f"environment variable {provider.api_key_env} is not set")
    root = args.state.parent
    if not state_matches(args.state, cid):
        raise Refused(f"--state {args.state.name} is not this plan's state file ({cid})")
    if under_docs_results(root):
        raise Refused("a paid run's root may not be under docs/results/: copy the report there "
                      "only after review")  # fmt: skip
    print(f"provider {provider.name} ({provider.base_url}), model {provider.model}: this "
          f"campaign may spend up to {plan.budget_total} provider-reported tokens (the cap)",
          file=sys.stderr)  # fmt: skip
    if not confirmed(args):
        print("not confirmed: re-run with --yes to spend these tokens", file=sys.stderr)
        return EXIT_REFUSED
    from proveflow.runner.llm import HttpChatClient

    records = cached_records(args.cache)
    root.mkdir(parents=True, exist_ok=True)
    out_dir = root / cid
    out_dir.mkdir(exist_ok=True)
    attempt_for = _attempt_for(plan, template, out_dir, HttpChatClient(provider), provider)

    async def go() -> CampaignState:
        return await run_engine(**_engine_kwargs(plan, records, cid, root),
                                model_side="provider", attempt_for=attempt_for)  # fmt: skip

    state = anyio.run(go)
    print(_finish(plan, state, root))
    return 0


def parse(argv: Sequence[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="python -m proveflow.runner.paid")
    sub = p.add_subparsers(dest="command", required=True)
    pre = sub.add_parser("preflight")
    pre.add_argument("plan", type=Path)
    pre.add_argument("--cache", type=Path, default=Path(".proveflow-corpus"))
    pre.add_argument("--dry-run-root", type=Path, required=True)
    dry = sub.add_parser("dry-run")
    dry.add_argument("plan", type=Path)
    dry.add_argument("--cache", type=Path, default=Path(".proveflow-corpus"))
    dry.add_argument("--root", type=Path, required=True)
    dry.add_argument("--kill-at-request", type=int, default=None)
    run = sub.add_parser("run")
    run.add_argument("plan", type=Path)
    run.add_argument("--cache", type=Path, default=Path(".proveflow-corpus"))
    run.add_argument("--config", type=Path, required=True)
    run.add_argument("--state", type=Path, required=True)
    run.add_argument("--yes", action="store_true", help="spend provider tokens (required)")
    return p.parse_args(list(argv))


COMMANDS = {"preflight": cmd_preflight, "dry-run": cmd_dry_run, "run": cmd_run}


def main(argv: Sequence[str] | None = None) -> int:
    args = parse(sys.argv[1:] if argv is None else argv)
    return COMMANDS[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
