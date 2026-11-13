"""Role-classifier metrics from labeled split CSVs -> docs/eval/RESULTS.md (+ RESULTS.json).

    python -m proveflow.eval.metrics --split-dir data/eval/roles/split \\
        [--out docs/eval/RESULTS.md]

- Truth: TEST = `<role>_final` (adjudicated, docs/eval/LABELING_GUIDE.md); DEV = `<role>_a`.
  A test row without a final label is an error (adjudication is not complete).
- Prediction: proveflow's tool-level classifier (`flows.roles.classify_tool`) on the same
  name / description / input schema the labelers saw.
- Per role: TP/FP/FN/TN, precision, recall, F1. A Wilson 95% interval is reported ONLY where
  its denominator is >= 10 (TP+FP for precision, TP+FN for recall); otherwise
  "N < 10, not reported" (the point estimate and counts are still shown).
- Cohen's kappa per role on the TEST split from the RAW labels A and B (before discussion).
- Breakdown by source (reference / popular / registry / own) next to the pooled numbers.
- Every run increments a counter in <split-dir>/metrics_runs.json; the report states how
  many times the test split has been evaluated.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
import shutil
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.text import Text

from proveflow import __version__
from proveflow.eval.split import ROLES
from proveflow.flows import roles as roles_module
from proveflow.flows import server_roles as server_roles_module
from proveflow.flows.roles import assigned_roles, classify_tool
from proveflow.stats.intervals import cohens_kappa, wilson

MIN_CI_DENOMINATOR = 10
NOT_IMPLEMENTED_EXIT = 2
YES, NO = "yes", "no"


class MetricsError(RuntimeError):
    pass


@dataclass(frozen=True)
class Row:
    tool_id: str
    source: str
    truth: dict[str, bool]
    pred: dict[str, bool]
    label_a: dict[str, bool]
    label_b: dict[str, bool] | None
    uncertain: bool
    unresolved: bool
    tool_name: str = ""
    server_id: str = ""


def _yn(value: str, where: str) -> bool:
    v = value.strip().lower()
    if v == YES:
        return True
    if v == NO:
        return False
    raise MetricsError(f"{where}: expected 'yes' or 'no'")


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _tools(path: Path) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rec = json.loads(line)
            out[rec["tool_id"]] = rec
    return out


def _predict(rec: dict[str, Any]) -> dict[str, bool]:
    tool = classify_tool(
        rec["tool_name"], rec["server_id"], rec.get("description") or "",
        rec.get("input_schema") or {},
    )  # fmt: skip
    got = {r.value for r in assigned_roles(tool)}
    return {r: r in got for r in ROLES}


def load_rows(split_dir: Path, split: str) -> list[Row]:
    tools = _tools(split_dir / f"{split}_tools.jsonl")
    rows: list[Row] = []
    for i, raw in enumerate(_read_csv(split_dir / f"labels_{split}.csv"), start=2):
        where = f"labels_{split}.csv line {i}"
        tid = raw["tool_id"]
        if tid not in tools:
            raise MetricsError(f"{where}: unknown tool_id")
        label_a = {r: _yn(raw[f"{r}_a"], f"{where} {r}_a") for r in ROLES}
        label_b: dict[str, bool] | None = None
        if split == "test":
            if any(raw.get(f"{r}_final", "").strip() == "" for r in ROLES):
                raise MetricsError(f"{where}: missing final label (adjudication incomplete)")
            truth = {r: _yn(raw[f"{r}_final"], f"{where} {r}_final") for r in ROLES}
            if all(raw.get(f"{r}_b", "").strip() for r in ROLES):
                label_b = {r: _yn(raw[f"{r}_b"], f"{where} {r}_b") for r in ROLES}
        else:
            truth = label_a
        uncertain = any(
            raw.get(col, "").strip().lower() == YES for col in ("uncertain_a", "uncertain_b")
        )
        rows.append(
            Row(
                tool_id=tid,
                source=str(tools[tid].get("source", "unknown")),
                truth=truth,
                pred=_predict(tools[tid]),
                label_a=label_a,
                label_b=label_b,
                uncertain=uncertain,
                unresolved=raw.get("resolution_note", "").strip().lower().startswith("unresolved"),
                tool_name=str(tools[tid].get("tool_name", "")),
                server_id=str(tools[tid].get("server_id", "")),
            )
        )
    return rows


def _rate(k: int, n: int) -> dict[str, Any]:
    if n == 0:
        return {"value": None, "k": k, "n": n, "ci": None, "ci_note": "undefined (n = 0)"}
    out: dict[str, Any] = {"value": k / n, "k": k, "n": n}
    if n >= MIN_CI_DENOMINATOR:
        ci = wilson(k, n)
        out.update(ci=[ci.low, ci.high], ci_note=None)
    else:
        out.update(ci=None, ci_note=f"N < {MIN_CI_DENOMINATOR}, not reported")
    return out


def role_metrics(rows: Sequence[Row], role: str) -> dict[str, Any]:
    tp = sum(r.truth[role] and r.pred[role] for r in rows)
    fp = sum((not r.truth[role]) and r.pred[role] for r in rows)
    fn = sum(r.truth[role] and not r.pred[role] for r in rows)
    tn = len(rows) - tp - fp - fn
    precision = _rate(tp, tp + fp)
    recall = _rate(tp, tp + fn)
    p, rc = precision["value"], recall["value"]
    f1 = None if p is None or rc is None or p + rc == 0 else 2 * p * rc / (p + rc)
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "precision": precision,
            "recall": recall, "f1": f1, "n": len(rows)}  # fmt: skip


def kappa_metrics(rows: Sequence[Row]) -> dict[str, Any]:
    pairs = [r for r in rows if r.label_b is not None]
    if not pairs:
        return {r: {"kappa": None, "n": 0, "note": "labeler B labels missing"} for r in ROLES}
    out: dict[str, Any] = {}
    for role in ROLES:
        a = [r.label_a[role] for r in pairs]
        b = [r.label_b[role] for r in pairs if r.label_b is not None]
        out[role] = {
            "kappa": cohens_kappa(a, b),
            "n": len(pairs),
            "observed_agreement": sum(x == y for x, y in zip(a, b, strict=True)) / len(pairs),
            "positive_rate_a": sum(a) / len(pairs),
            "positive_rate_b": sum(b) / len(pairs),
        }
    return out


def _block(rows: Sequence[Row]) -> dict[str, Any]:
    by_source: dict[str, list[Row]] = {}
    for r in rows:
        by_source.setdefault(r.source, []).append(r)
    return {
        "n": len(rows),
        "pooled": {role: role_metrics(rows, role) for role in ROLES},
        "by_source": {
            src: {"n": len(rs), **{role: role_metrics(rs, role) for role in ROLES}}
            for src, rs in sorted(by_source.items())
        },
        "uncertain_rows": sum(r.uncertain for r in rows),
    }


def _sha_files(paths: Sequence[Path]) -> str:
    h = hashlib.sha256()
    for p in paths:
        h.update(p.name.encode())
        h.update(p.read_bytes())
    return h.hexdigest()


def _git_commit() -> str:
    git = shutil.which("git")
    if git is None:
        return "unknown"
    try:
        out = subprocess.run(  # noqa: S603 - fixed read-only git query
            [git, "rev-parse", "HEAD"], capture_output=True, text=True, check=True, timeout=10
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return out.stdout.strip() or "unknown"


def compute(split_dir: Path) -> dict[str, Any]:
    split_meta = json.loads((split_dir / "split.json").read_text(encoding="utf-8"))
    dev = load_rows(split_dir, "dev")
    test = load_rows(split_dir, "test")
    runs_path = split_dir / "metrics_runs.json"
    runs = json.loads(runs_path.read_text(encoding="utf-8")) if runs_path.exists() else {}
    runs["test_evaluations"] = int(runs.get("test_evaluations", 0)) + 1
    runs_path.write_text(json.dumps(runs, indent=2) + "\n", encoding="utf-8", newline="\n")
    return {
        "schema_version": 1,
        "metadata": {
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "proveflow_version": __version__,
            "git_commit": _git_commit(),
            "python": platform.python_version(),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor() or "unknown",
            "classifier_sha256": _classifier_sha256(),
            "labels_sha256": _sha_files(
                [split_dir / "labels_dev.csv", split_dir / "labels_test.csv"]
            ),
            "split_inputs": split_meta.get("inputs"),
            "split_seed": split_meta.get("seed"),
            "split_cap": split_meta.get("cap"),
            "test_evaluations": runs["test_evaluations"],
        },
        "dev": _block(dev),
        "test": {
            **_block(test),
            "kappa": kappa_metrics(test),
            "unresolved_rows": sum(r.unresolved for r in test),
        },
    }


# --- held-out v2 guard (checkpoint 1c Stage D) ----------------------------------------
# Required label cells: <role>_a and <role>_final for every role, on every row. The labeler-B
# columns are optional (no second held-out labeler is planned); kappa is reported only if
# they are complete. The held-out counter lives in <heldout_dir>/metrics_runs.json under
# "heldout_evaluations" (created at 0 by `split --heldout`), separate from the v1 split's
# "test_evaluations".
HELDOUT_CSV = "labels_heldout_v2.csv"
HELDOUT_COUNTER_KEY = "heldout_evaluations"
HELDOUT_REQUIRED = [*(f"{r}_a" for r in ROLES), *(f"{r}_final" for r in ROLES)]


def heldout_label_gaps(heldout_dir: Path) -> int:
    """Number of empty required label cells (an empty sheet counts as one gap)."""
    rows = _read_csv(heldout_dir / HELDOUT_CSV)
    if not rows:
        return 1
    return sum(1 for row in rows for c in HELDOUT_REQUIRED if not (row.get(c) or "").strip())


def heldout_counter(heldout_dir: Path) -> int:
    data = json.loads((heldout_dir / "metrics_runs.json").read_text(encoding="utf-8"))
    return int(data[HELDOUT_COUNTER_KEY])


def guard_heldout(heldout_dir: Path) -> None:
    """Refuse held-out evaluation while any required label cell is empty."""
    gaps = heldout_label_gaps(heldout_dir)
    if gaps:
        raise MetricsError(
            f"held-out labels incomplete: {gaps} empty label cell(s) in {HELDOUT_CSV}; "
            "refusing to evaluate (counter unchanged)"
        )


def _classifier_sha256() -> str:
    return _sha_files([Path(roles_module.__file__), Path(server_roles_module.__file__)])


def compute_dev(split_dir: Path) -> dict[str, Any]:
    """Dev-only evaluation for tuning (checkpoint 1c). Opens ONLY dev_tools.jsonl and
    labels_dev.csv: never a test file, never split.json, never metrics_runs.json (the
    test-evaluation counter is untouched)."""
    dev = load_rows(split_dir, "dev")
    errors = [
        {"tool_id": r.tool_id, "server_id": r.server_id, "tool_name": r.tool_name, "role": role,
         "kind": "FN" if r.truth[role] else "FP", "uncertain": r.uncertain}
        for r in dev
        for role in ROLES
        if r.truth[role] != r.pred[role]
    ]  # fmt: skip
    return {
        "schema_version": 1,
        "metadata": {
            "mode": "dev_only",
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "proveflow_version": __version__,
            "git_commit": _git_commit(),
            "python": platform.python_version(),
            "classifier_sha256": _classifier_sha256(),
            "labels_sha256": _sha_files([split_dir / "labels_dev.csv"]),
        },
        "dev": _block(dev),
        "errors": sorted(
            errors, key=lambda e: (e["role"], e["kind"], e["server_id"], e["tool_name"])
        ),
    }


def render_dev(result: dict[str, Any]) -> str:
    md = result["metadata"]
    block = result["dev"]
    out = [
        "# Role classifier: DEV split only (tuning aid, NOT a claim)",
        "",
        "Generated by `python -m proveflow.eval.metrics --dev-only`; do not edit by hand. "
        "Dev labels were used for tuning, so these numbers are optimistic by construction. "
        "No test file was read and the test-evaluation counter was not touched.",
        "",
        "## Run metadata",
        "",
        *(f"- **{k}**: `{v}`" for k, v in md.items()),
        "",
        f"## DEV split (N = {block['n']} tools)",
        "",
        "### Pooled",
        "",
        *_table(block["pooled"]),
        "",
        "### By source",
        "",
    ]
    for src, sb in block["by_source"].items():
        out += [f"**{src}** (N = {sb['n']})", "", *_table(sb), ""]
    out += [f"Rows marked uncertain by a labeler: {block['uncertain_rows']}.", ""]
    out += [f"## Errors ({len(result['errors'])})", "",
            "| Role | Kind | Server | Tool | Uncertain |", "|---|---|---|---|---|"]  # fmt: skip
    for e in result["errors"]:
        out.append(
            f"| `{e['role']}` | {e['kind']} | {e['server_id']} | `{e['tool_name']}` | "
            f"{'yes' if e['uncertain'] else 'no'} |"
        )
    out.append("")
    return "\n".join(out)


def _fmt_rate(m: dict[str, Any]) -> str:
    if m["value"] is None:
        return f"undefined ({m['k']}/{m['n']})"
    base = f"{m['value']:.3f} ({m['k']}/{m['n']})"
    if m["ci"] is None:
        return f"{base}; CI: {m['ci_note']}"
    return f"{base}; 95% CI [{m['ci'][0]:.3f}, {m['ci'][1]:.3f}]"


def _table(block: dict[str, Any]) -> list[str]:
    lines = [
        "| Role | TP | FP | FN | TN | Precision | Recall | F1 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for role in ROLES:
        m = block[role]
        f1 = "undefined" if m["f1"] is None else f"{m['f1']:.3f}"
        lines.append(
            f"| `{role}` | {m['tp']} | {m['fp']} | {m['fn']} | {m['tn']} | "
            f"{_fmt_rate(m['precision'])} | {_fmt_rate(m['recall'])} | {f1} |"
        )
    return lines


THREATS = (
    "Small N: the eval set has about 70-150 tools; CIs are wide and cells with a denominator "
    "below 10 have no CI.",
    "Partial blindness: the heuristic author (Claude) may know public servers' tool names from "
    "training; the roles.py vocabulary was written before the split.",
    "Reference-server style: the six reference servers share one repository's writing style "
    "and can sit on both sides of the split (variant A), which may inflate test numbers; see "
    "the per-source rows.",
    "Known gap: an agent-controlled URL parameter is labeled sink (LABELING_GUIDE), but the "
    "classifier gives it weight 0.25 < threshold 0.5, which lowers sink recall.",
    "Pattern redaction may alter descriptions (pattern_redactions in the collector output).",
)


def render(result: dict[str, Any]) -> str:
    md = result["metadata"]
    out = [
        "# Role-classifier results [measured]",
        "",
        "Generated by `python -m proveflow.eval.metrics`; do not edit by hand.",
        "",
        "## Run metadata",
        "",
        *(f"- **{k}**: `{v}`" for k, v in md.items()),
        "",
        f"**The test split has now been evaluated {md['test_evaluations']} time(s).**",
        "",
    ]
    for split in ("test", "dev"):
        block = result[split]
        out += [f"## {split.upper()} split (N = {block['n']} tools)", "", "### Pooled", ""]
        out += _table(block["pooled"])
        out += ["", "### By source", ""]
        for src, sb in block["by_source"].items():
            out += [f"**{src}** (N = {sb['n']})", "", *_table(sb), ""]
        out.append(f"Rows marked uncertain by a labeler: {block['uncertain_rows']}.")
        if split == "test":
            out += ["", "### Inter-rater agreement (raw labels A vs B, before discussion)", ""]
            out += ["| Role | Cohen's kappa | N | Observed agreement | A positive | B positive |",
                    "|---|---|---|---|---|---|"]  # fmt: skip
            for role in ROLES:
                k = block["kappa"][role]
                if k.get("kappa") is None and k["n"] == 0:
                    out.append(f"| `{role}` | n/a ({k['note']}) | 0 | - | - | - |")
                    continue
                kv = "undefined" if k["kappa"] is None else f"{k['kappa']:.3f}"
                out.append(
                    f"| `{role}` | {kv} | {k['n']} | {k['observed_agreement']:.3f} | "
                    f"{k['positive_rate_a']:.3f} | {k['positive_rate_b']:.3f} |"
                )
            out += [
                "",
                f"Unresolved disagreements (final = labeler A): {block['unresolved_rows']}.",
            ]
        out.append("")
    out += ["## Threats to validity", "", *(f"- {t}" for t in THREATS), ""]
    return "\n".join(out)


def main(argv: Sequence[str] | None = None) -> int:
    console = Console(stderr=True)
    parser = argparse.ArgumentParser(prog="python -m proveflow.eval.metrics")
    parser.add_argument("--split-dir", type=Path, default=None)
    parser.add_argument(
        "--heldout", type=Path, default=None,
        help="held-out dir (data/eval/roles/heldout_v2): refused while any label is empty",
    )  # fmt: skip
    parser.add_argument(
        "--out", type=Path, default=None,
        help="default: docs/eval/RESULTS.md, or docs/eval/DEV_RESULTS.md with --dev-only",
    )  # fmt: skip
    parser.add_argument(
        "--dev-only", action="store_true",
        help="tuning aid: read only the dev split; never open test files or the counter",
    )  # fmt: skip
    ns = parser.parse_args(argv)
    if ns.heldout is not None:
        try:
            guard_heldout(ns.heldout)
        except (MetricsError, FileNotFoundError, KeyError) as exc:
            console.print(Text(f"error: {exc}", style="red"))
            return 1
        console.print(Text(
            "held-out labels complete, but the held-out evaluation (v1 and v2 in one run) is "
            "implemented in Stage D part 2; nothing evaluated, counter unchanged"
        ))  # fmt: skip
        return NOT_IMPLEMENTED_EXIT
    if ns.split_dir is None:
        parser.error("--split-dir is required (or use --heldout)")
    if ns.dev_only:
        out = ns.out or Path("docs/eval/DEV_RESULTS.md")
        try:
            dev_result = compute_dev(ns.split_dir)
        except (MetricsError, KeyError, FileNotFoundError) as exc:
            console.print(Text(f"error: {exc}", style="red"))
            return 1
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(render_dev(dev_result), encoding="utf-8", newline="\n")
        out.with_suffix(".json").write_text(
            json.dumps(dev_result, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
        )
        console.print(Text(f"classifier_sha256 {dev_result['metadata']['classifier_sha256']}"))
        console.print(Text(f"wrote {out} and {out.with_suffix('.json')} (dev only)"))
        return 0
    ns.out = ns.out or Path("docs/eval/RESULTS.md")
    try:
        result = compute(ns.split_dir)
    except (MetricsError, KeyError, FileNotFoundError) as exc:
        console.print(Text(f"error: {exc}", style="red"))
        return 1
    ns.out.parent.mkdir(parents=True, exist_ok=True)
    ns.out.write_text(render(result), encoding="utf-8", newline="\n")
    ns.out.with_suffix(".json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    console.print(Text(f"wrote {ns.out} and {ns.out.with_suffix('.json')}"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
