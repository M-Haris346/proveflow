"""DEV-ONLY manual run against a real provider (Phase 5, Q5). Not a `proveflow` subcommand,
and no provider is claimed as supported until a run is recorded in docs/PROVIDERS.md.

    uv run python -m proveflow.runner.manual --scenario S.json --config proveflow.toml \\
        --provider groq --out-dir DIR [--seed N] [--temperature T] --yes

Without ``--yes`` it prints the provider, the model and the trial's MAXIMUM token cost, and
exits without spending anything (no twin, no proxy, no HTTP client is created): a dev tool
that can spend money on the first keystroke is not acceptable. The key is read from the
environment variable named in the config, at call time, and never written anywhere.
A transcript from a real run is committed only after it passes the D7 checks
(tests/safety/test_runner_safety.py), and the commit names the provider and model.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path

import anyio

from proveflow.config import ProviderConfig, load_config
from proveflow.proxy import policy
from proveflow.runner.limits import RunBudget, TrialLimits
from proveflow.runner.scenario import Scenario

EXIT_NOT_CONFIRMED = 2


class NotConfirmed(SystemExit):
    pass


def parse(argv: Sequence[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="python -m proveflow.runner.manual")
    p.add_argument("--scenario", type=Path, required=True)
    p.add_argument("--config", type=Path, required=True)
    p.add_argument("--provider", required=True)
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--temperature", type=float, default=0.0)
    p.add_argument("--yes", action="store_true", help="spend provider tokens (required)")
    return p.parse_args(list(argv))


def cost_line(provider: ProviderConfig, limits: TrialLimits) -> str:
    return (
        f"provider {provider.name} ({provider.base_url}), model {provider.model}: this trial "
        f"may spend up to {limits.max_tokens_in} tokens in + {limits.max_tokens_out} out "
        f"= {limits.max_trial_tokens} provider-reported tokens"
    )


def require_consent(args: argparse.Namespace, line: str) -> None:
    """The spend gate: without --yes nothing is created and nothing is sent."""
    print(line, file=sys.stderr)
    if not args.yes:
        print("not confirmed: re-run with --yes to spend these tokens", file=sys.stderr)
        raise NotConfirmed(EXIT_NOT_CONFIRMED)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse(sys.argv[1:] if argv is None else argv)
    config = load_config(args.config)
    provider = next((p for p in config.provider if p.name == args.provider), None)
    if provider is None:
        print(f"no [[provider]] named {args.provider!r} in {args.config.name}", file=sys.stderr)
        return 1
    scenario = Scenario.model_validate_json(args.scenario.read_text(encoding="utf-8"))
    limits = TrialLimits()
    require_consent(args, cost_line(provider, limits))
    from proveflow.runner.llm import HttpChatClient
    from proveflow.runner.trial import run_trial

    args.out_dir.mkdir(parents=True, exist_ok=False)
    twin_dir = policy.TWIN_ROOT / "manual"
    twin_dir.mkdir(parents=True, exist_ok=True)

    async def go() -> object:
        return await run_trial(
            scenario, trial_id=f"manual-{scenario.id}", llm=HttpChatClient(provider),
            provider=provider, temperature=args.temperature, seed=args.seed,
            out_dir=args.out_dir, twin_dir=twin_dir, budget=RunBudget(),
            parent_env=dict(os.environ), limits=limits,
        )  # fmt: skip

    result = anyio.run(go)
    print(f"done: {result.outcome.reason}; verdict {result.verdict.model_dump_json()}",  # type: ignore[attr-defined]
          file=sys.stderr)  # fmt: skip
    return 0


if __name__ == "__main__":
    sys.exit(main())
