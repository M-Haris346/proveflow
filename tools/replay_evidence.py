"""DEV-ONLY: replay one committed real-run transcript (evidence/provider-runs/<run>/) offline.

    uv run python tools/replay_evidence.py evidence/provider-runs/<run> [--timings PATH]

Strict ``ReplayChatClient``: no network, no API key, no provider. The only processes started
are the run's own generated twins (written under proveflow's twin directory, ``replay-evidence``),
behind the unchanged proxy. Provider, model, temperature, seed and limits come from the
transcript's ``trial_start``; the scenario from the run's ``scenario.json``.

It reports the replayed verdict and compares the transcript it writes with the committed one:
every event before ``trial_end`` must be byte-identical, and ``trial_end`` must be identical
except ``cassettes[].final_sha256`` and its own ``sha256``. Those hash the cassettes, whose
``session_start.upstream.argv`` holds the absolute interpreter and twin paths, so they
differ with another interpreter or twin directory. Cassettes are rewritten and not compared
(not committed); their hashes are the excluded fields. This tool therefore never shows that
the cassettes reproduced. Whole-file identity is printed as well, as information. Exit 0 only
if the comparison holds and the run ended for the same reason.

Leftovers: the scratch directory (printed on stderr) can be deleted. Its cassettes hold
absolute paths and must not be committed, and .gitignore does not cover them. The generated
twins stay under the twin directory's ``replay-evidence``; they are regenerated
deterministically and can be deleted.

Latency: the timings sidecar is NON-EVIDENCE (wall-clock, ADR-008) and not committed, and a
replay refuses to run without one (``MissingTimings``). With ``--timings`` the run's real
sidecar is used (it must be bound to this transcript by hash). Without it, a sidecar labelled
SYNTHETIC is written into the scratch directory, and ``latency_ms`` is not part of what is
reproduced.

Why this is a tool and never a committed test: the twin generator's output is allowed to
change (seeded synthetic data; archetypes will evolve). A committed replay-of-evidence test
would break on such a legitimate change, and create pressure to weaken it or to delete real
evidence. Never imported by src/ or tests/ (tests/safety/test_transcript_layers.py checks).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

import anyio

from proveflow.config import ProviderConfig
from proveflow.proxy import policy
from proveflow.runner.limits import TrialLimits
from proveflow.runner.llm import ReplayMismatch
from proveflow.runner.scenario import Scenario
from proveflow.runner.transcript import TrialEnd, TrialStart, load_transcript
from proveflow.runner.trial import replay_trial

SYNTHETIC_NOTE = "SYNTHETIC timings written by tools/replay_evidence.py, not measured"


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="python tools/replay_evidence.py")
    p.add_argument("run_dir", type=Path)
    p.add_argument("--timings", type=Path, default=None)
    args = p.parse_args(argv)
    evidence = args.run_dir / "transcript.jsonl"
    events = load_transcript(evidence)
    start, end = events[0], events[-1]
    if not isinstance(start, TrialStart) or not isinstance(end, TrialEnd):
        print("not a complete transcript", file=sys.stderr)
        return 1
    scenario = Scenario.model_validate_json((args.run_dir / "scenario.json").read_text("utf-8"))
    params = start.parameters
    provider = ProviderConfig(
        name=start.provider["name"], base_url=start.provider["base_url"],
        model=start.provider["model"], api_key_env="PF_REPLAY_UNUSED",
        send_seed=bool(params["seed_sent"]),
    )  # fmt: skip
    scratch = Path(tempfile.mkdtemp(prefix="pf-replay-evidence-"))
    print(f"scratch directory: {scratch}", file=sys.stderr)
    recorded = scratch / "recorded" / f"{start.trial_id}.transcript.jsonl"
    recorded.parent.mkdir()
    shutil.copyfile(evidence, recorded)
    timings = recorded.with_name(f"{start.trial_id}.timings.json")
    if args.timings is not None:
        shutil.copyfile(args.timings, timings)
    else:
        timings.write_bytes(json.dumps({
            "_note": SYNTHETIC_NOTE, "trial_id": start.trial_id,
            "transcript_sha256": end.sha256, "latency_ms": 0.0,
        }).encode("utf-8"))  # fmt: skip
    out = scratch / "replayed"
    out.mkdir()
    twin_dir = policy.TWIN_ROOT / "replay-evidence"
    twin_dir.mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if not k.upper().endswith("_API_KEY")}

    async def go() -> object:
        return await replay_trial(
            scenario, recorded=recorded, trial_id=start.trial_id, provider=provider,
            temperature=float(params["temperature"]), seed=int(params["seed"]), out_dir=out,
            twin_dir=twin_dir, parent_env=env, recorded_timings=timings,
            limits=TrialLimits.model_validate(start.limits),
        )  # fmt: skip

    try:
        result = anyio.run(go)
    except ReplayMismatch as exc:
        print(f"replay diverged: {exc}")
        return 1
    verdict = result.verdict.model_dump(mode="json")  # type: ignore[attr-defined]
    if args.timings is None:
        verdict["latency_ms"] = "not reproduced (no real timings sidecar; SYNTHETIC used)"
    mine = (out / recorded.name).read_bytes().splitlines(keepends=True)
    theirs = evidence.read_bytes().splitlines(keepends=True)
    before_end = len(mine) == len(theirs) and mine[:-1] == theirs[:-1]
    end_rest = _without_cassette_hashes(mine[-1]) == _without_cassette_hashes(theirs[-1])
    reason = result.outcome.reason  # type: ignore[attr-defined]
    print(f"outcome: {reason} (recorded: {end.reason})")
    print(f"verdict: {json.dumps(verdict)}")
    print(f"events before trial_end byte-identical ({len(theirs) - 1} lines): {before_end}")
    print(f"trial_end identical except cassette hashes and its own sha256: {end_rest}")
    print(f"whole file byte-identical (needs the run's interpreter and twin dir): "
          f"{mine == theirs}")  # fmt: skip
    print("cassettes are rewritten and not compared (not committed); "
          "their hashes are the excluded fields")  # fmt: skip
    print("scratch directory (path on stderr) can be deleted; its cassettes hold absolute "
          "paths and must not be committed (.gitignore does not cover them)")  # fmt: skip
    return 0 if before_end and end_rest and reason == end.reason else 1


def _without_cassette_hashes(line: bytes) -> object:
    event = json.loads(line)
    event.pop("sha256", None)
    for ref in event.get("cassettes", []):
        ref.pop("final_sha256", None)
    return event


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
