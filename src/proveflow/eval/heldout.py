"""The ONE held-out evaluation of frozen classifier v1 and v2 (checkpoint 1c, Stage D part 2).

    python -m proveflow.eval.heldout [--heldout data/eval/roles/heldout_v2]
                                     [--out docs/eval/RESULTS_V2.md]

Protocol (docs/eval/RESULTS_V2.md "Metric plan", fixed before any prediction):
- refuses unless the plan section of --out is byte-identical (PLAN_SHA256), guard_heldout
  passes, heldout_evaluations == 0, and both classifier shas match (v1 from git V1_COMMIT,
  v2 from the working tree; both loaded in-process);
- writes heldout_evaluations = 1 BEFORE computing anything; any later run is refused;
- never reads or touches the v1 test split or its counter;
- per-rule exposure uses the frozen v2 module's own functions/constants, read-only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import subprocess
import sys
import types
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.text import Text

from proveflow import __version__
from proveflow.eval.metrics import (
    HELDOUT_COUNTER_KEY,
    HELDOUT_CSV,
    YES,
    MetricsError,
    _read_csv,
    guard_heldout,
    heldout_counter,
)
from proveflow.eval.split import ROLES
from proveflow.stats.intervals import wilson

V1_COMMIT = "86157de"
V1_SHA256 = "08deee09cb4feb3cf388b93c263dbcdc6f95165cba1678a6305680b5b60f4a16"
V2_SHA256 = "db4100d59c74668c594947fd0bf7d52869bfc831778ff24ac2de352f91a78a50"
FLOW_FILES = ("src/proveflow/flows/roles.py", "src/proveflow/flows/server_roles.py")
PLAN_END = "<!-- PLAN-END: everything above this line is fixed; generated results follow. -->\n"
PLAN_SHA256 = "38e6c70adeaac7fda80b2dfea368c6a79b9d74603f0315ece113d6d814a61e0b"
WIDE_N = 10

# Evidence-adding v2 rules: substring of the evidence reason the frozen v2 module emits.
EVIDENCE_RULES: dict[str, str] = {
    "C1": "saves output to a file",
    "C2": "schema: repository param",
    "C3": "name: version-control write",
    "C4": "schema: agent text",
    "C8": "(GET can carry data)",
    "C9": "schema: 'model' + input",
    "C11a": "name: captures rendered content",
    "C11c": "description: says its output is untrusted",
    "C11d": "description: arbitrary code execution",
    "C12": "schema: HTTP header param",
}
RULE_ORDER = ("C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8", "C9", "C11a", "C11c", "C11d",
              "C12")  # fmt: skip
NOT_IN_V2 = {"C10": "reverted (no dev effect)", "C11b": "skipped (single-server convention)"}


class HeldoutError(RuntimeError):
    """Refusal before evaluation; the counter is untouched unless stated otherwise."""


# --- classifier loading -------------------------------------------------------------------


def classifier_sha256(blobs: Sequence[tuple[str, bytes]]) -> str:
    """Same construction as proveflow.eval.metrics._sha_files: file name, then bytes."""
    h = hashlib.sha256()
    for name, data in blobs:
        h.update(name.encode())
        h.update(data)
    return h.hexdigest()


def _git_show(rev: str, path: str) -> bytes:
    git = shutil.which("git")
    if git is None:
        raise HeldoutError("git not found; cannot load v1 from history")
    try:
        return subprocess.run(  # noqa: S603 - fixed read-only git query
            [git, "show", f"{rev}:{path}"], capture_output=True, check=True, timeout=30
        ).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        raise HeldoutError(f"cannot read {path} at {rev}: {type(exc).__name__}") from None


def _module_from_source(name: str, source: bytes, filename: str) -> types.ModuleType:
    mod = types.ModuleType(name)
    mod.__file__ = filename
    sys.modules[name] = mod  # some constructs resolve their module by name
    exec(compile(source, filename, "exec"), mod.__dict__)  # noqa: S102 - our own frozen file
    return mod


def load_v1() -> tuple[types.ModuleType, str]:
    blobs = [(Path(p).name, _git_show(V1_COMMIT, p)) for p in FLOW_FILES]
    sha = classifier_sha256(blobs)
    mod = _module_from_source("proveflow_frozen_v1_roles", blobs[0][1], f"{V1_COMMIT}:roles.py")
    return mod, sha


def load_v2() -> tuple[types.ModuleType, str]:
    from proveflow.flows import roles, server_roles

    files = [Path(str(roles.__file__)), Path(str(server_roles.__file__))]
    return roles, classifier_sha256([(f.name, f.read_bytes()) for f in files])


# --- per-tool prediction and exposure -----------------------------------------------------


def predict(mod: Any, rec: dict[str, Any]) -> dict[str, bool]:
    tool = mod.classify_tool(rec["tool_name"], rec["server_id"], rec.get("description") or "",
                             rec.get("input_schema") or {})  # fmt: skip
    got = {r.value for r in mod.assigned_roles(tool)}
    return {r: r in got for r in ROLES}


def raw_evidence(r2: Any, rec: dict[str, Any]) -> list[Any]:
    """v2's pre-threshold evidence, in classify_tool's exact order (read-only use)."""
    name, desc = rec["tool_name"], rec.get("description") or ""
    schema = rec.get("input_schema") or {}
    toks = r2.tokenize(name)
    ev: list[Any] = (
        r2._name_evidence(name)
        + r2._write_tool_desc(toks, r2._desc_evidence(desc))
        + r2._schema_evidence(schema)
        + r2._repo_evidence(toks, schema)
        + r2._entered_text_evidence(desc, schema)
        + r2._phrase_evidence(desc)
    )
    selected = r2.classify_tool(name, rec["server_id"], desc, schema).roles
    if tuple(r2.select_roles(ev)) != tuple(selected):
        raise HeldoutError("raw-evidence reconstruction differs from classify_tool")
    return ev


def exposure(r2: Any, rec: dict[str, Any]) -> set[str]:
    """v2 rules whose trigger matches this tool."""
    ev = raw_evidence(r2, rec)
    reasons = [e.reason for e in ev]
    hit = {rule for rule, key in EVIDENCE_RULES.items() if any(key in r for r in reasons)}
    toks = r2.tokenize(rec["tool_name"])
    tokset = set(toks)
    if ("browser" in tokset and tokset & {"hover", "drag"}) or (
        "close" in tokset and tokset & r2.UI_NOUNS
    ):
        hit.add("C5")
    desc_private = [e for e in r2._desc_evidence(rec.get("description") or "")
                    if e.role is r2.ToolRole.PRIVATE_DATA]  # fmt: skip
    if desc_private and r2._name_writes(toks) and r2._first(toks, r2.READ_VERBS) is None:
        hit.add("C6")
    if "navigate" in tokset:
        hit.add("C7")
    return hit


# --- metrics --------------------------------------------------------------------------------


def _rate(k: int, n: int) -> dict[str, Any]:
    if n == 0:
        return {"value": None, "k": k, "n": n, "ci": None, "note": "undefined (n = 0)"}
    ci = wilson(k, n)
    return {"value": k / n, "k": k, "n": n, "ci": [ci.low, ci.high],
            "note": "n < 10: very wide" if n < WIDE_N else None}  # fmt: skip


def role_metrics(truth: list[bool], pred: list[bool]) -> dict[str, Any]:
    tp = sum(t and p for t, p in zip(truth, pred, strict=True))
    fp = sum((not t) and p for t, p in zip(truth, pred, strict=True))
    fn = sum(t and not p for t, p in zip(truth, pred, strict=True))
    tn = len(truth) - tp - fp - fn
    prec, rec = _rate(tp, tp + fp), _rate(tp, tp + fn)
    p, r = prec["value"], rec["value"]
    f1 = None if p is None or r is None or p + r == 0 else 2 * p * r / (p + r)
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "precision": prec, "recall": rec,
            "f1": f1, "n": len(truth)}  # fmt: skip


def block(rows: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {"n": len(rows)}
    for ver in ("v1", "v2"):
        out[ver] = {
            role: role_metrics([r["truth"][role] for r in rows], [r[ver][role] for r in rows])
            for role in ROLES
        }
    return out


def evaluate(heldout_dir: Path, v1: Any, v2: Any) -> dict[str, Any]:
    """Pure computation (no counter, no files written)."""
    labels = _read_csv(heldout_dir / HELDOUT_CSV)
    recs = {}
    for line in (heldout_dir / "heldout_tools.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            recs[r["tool_id"]] = r
    if {r["tool_id"] for r in labels} != set(recs):
        raise HeldoutError("labels and heldout_tools.jsonl cover different tool_ids")
    rows: list[dict[str, Any]] = []
    expo: dict[str, list[str]] = {rule: [] for rule in RULE_ORDER}
    for lab in labels:
        rec = recs[lab["tool_id"]]
        rows.append({
            "tool_id": lab["tool_id"], "tool_name": rec["tool_name"],
            "server_id": rec["server_id"],
            "uncertain": lab["uncertain_a"] == YES,
            "truth": {r: lab[f"{r}_final"] == YES for r in ROLES},
            "v1": predict(v1, rec), "v2": predict(v2, rec),
        })  # fmt: skip
        for rule in exposure(v2, rec):
            expo[rule].append(rec["tool_name"])
    errors = {
        ver: sorted(
            ({"role": role, "kind": "FN" if r["truth"][role] else "FP",
              "tool_name": r["tool_name"], "uncertain": r["uncertain"]}
             for r in rows for role in ROLES if r["truth"][role] != r[ver][role]),
            key=lambda e: (e["role"], e["kind"], e["tool_name"]),
        )
        for ver in ("v1", "v2")
    }  # fmt: skip
    return {
        "primary": block(rows),
        "secondary": block([r for r in rows if not r["uncertain"]]),
        "uncertain_rows": sum(r["uncertain"] for r in rows),
        "positives": {role: sum(r["truth"][role] for r in rows) for role in ROLES},
        "exposure": {
            rule: {
                "tools": len(v),
                "status": "exposed" if v else "untested",
                "tool_names": sorted(v),
            }
            for rule, v in expo.items()
        },
        "not_in_v2": NOT_IN_V2,
        "errors": errors,
    }


# --- rendering ------------------------------------------------------------------------------


def _fmt(m: dict[str, Any]) -> str:
    if m["value"] is None:
        return f"undefined ({m['k']}/{m['n']})"
    base = f"{m['value']:.3f} ({m['k']}/{m['n']}) [{m['ci'][0]:.3f}, {m['ci'][1]:.3f}]"
    return base + (" *" if m["note"] else "")


def _table(b: dict[str, Any]) -> list[str]:
    out = [
        "| Role | Version | TP | FP | FN | TN | Precision (95% Wilson) | Recall (95% Wilson) "
        "| F1 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for role in ROLES:
        for ver in ("v1", "v2"):
            m = b[ver][role]
            f1 = "undefined" if m["f1"] is None else f"{m['f1']:.3f}"
            out.append(f"| `{role}` | {ver} | {m['tp']} | {m['fp']} | {m['fn']} | {m['tn']} | "
                       f"{_fmt(m['precision'])} | {_fmt(m['recall'])} | {f1} |")  # fmt: skip
    note = "`*` = interval denominator n < 10: very wide. F1 has no interval (see plan)."
    return [*out, "", note]


def render(result: dict[str, Any]) -> str:
    md = result["metadata"]
    r = result["results"]
    out = ["", "## Generated results", "",
           "Generated by `python -m proveflow.eval.heldout` (one run); do not edit by hand.", "",
           "### Run metadata", ""]  # fmt: skip
    out += [f"- **{k}**: `{v}`" for k, v in md.items()]
    out += ["", f"Truth positives (all 55 rows): {r['positives']}. Rows with uncertain_a = yes: "
            f"{r['uncertain_rows']}.", ""]  # fmt: skip
    out += [f"### Primary: all rows (N = {r['primary']['n']})", "", *_table(r["primary"]), ""]
    out += [f"### Secondary: uncertain_a = no (N = {r['secondary']['n']})", "",
            *_table(r["secondary"]), ""]  # fmt: skip
    out += ["### Per-rule exposure (v2 rules)", "",
            "Number of held-out tools on which the rule's trigger matches. 0 = **untested** "
            "(not passing).", "", "| Rule | Tools | Status |", "|---|---|---|"]  # fmt: skip
    for rule in RULE_ORDER:
        e = r["exposure"][rule]
        out.append(f"| {rule} | {e['tools']} | {e['status']} |")
    out += [f"| {k} | - | not in v2: {v} |" for k, v in NOT_IN_V2.items()]
    for ver in ("v1", "v2"):
        errs = r["errors"][ver]
        out += ["", f"### Errors, {ver} ({len(errs)})", "", "| Role | Kind | Tool | Uncertain |",
                "|---|---|---|---|"]  # fmt: skip
        out += [f"| `{e['role']}` | {e['kind']} | `{e['tool_name']}` | "
                f"{'yes' if e['uncertain'] else 'no'} |" for e in errs]  # fmt: skip
    out += ["", "No significance test was run and no superiority claim is made: n is small "
            "(55 tools, 7 servers) and the intervals above are wide.", ""]  # fmt: skip
    return "\n".join(out)


# --- the single run -------------------------------------------------------------------------


def _plan(out: Path) -> bytes:
    text = out.read_bytes()
    marker = PLAN_END.encode()
    if marker not in text:
        raise HeldoutError(f"{out}: plan marker not found")
    plan = text[: text.index(marker) + len(marker)]
    if hashlib.sha256(plan).hexdigest() != PLAN_SHA256:
        raise HeldoutError(f"{out}: the metric plan differs from the fixed plan (sha256)")
    if len(plan) != len(text):
        raise HeldoutError(f"{out}: already has content after the plan (results exist)")
    return plan


def _git_head() -> str:
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


def run(
    heldout_dir: Path,
    out: Path,
    loaders: tuple[Callable[[], tuple[Any, str]], Callable[[], tuple[Any, str]]] = (
        load_v1, load_v2),
    expected: tuple[str, str] = (V1_SHA256, V2_SHA256),
) -> dict[str, Any]:  # fmt: skip
    plan = _plan(out)
    try:
        guard_heldout(heldout_dir)
    except MetricsError as exc:
        raise HeldoutError(str(exc)) from None
    if heldout_counter(heldout_dir) != 0:
        raise HeldoutError("held-out set already evaluated (heldout_evaluations != 0); refusing")
    (v1, sha1), (v2, sha2) = loaders[0](), loaders[1]()
    if (sha1, sha2) != expected:
        raise HeldoutError(f"classifier sha mismatch: v1 {sha1[:12]}, v2 {sha2[:12]} "
                           f"(expected {expected[0][:12]}, {expected[1][:12]})")  # fmt: skip
    counter = heldout_dir / "metrics_runs.json"
    counter.write_text(json.dumps({HELDOUT_COUNTER_KEY: 1}, indent=2) + "\n", encoding="utf-8",
                       newline="\n")  # fmt: skip
    results = evaluate(heldout_dir, v1, v2)
    labels_sha = hashlib.sha256((heldout_dir / HELDOUT_CSV).read_bytes()).hexdigest()
    module_sha = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    result = {
        "schema_version": 1,
        "metadata": {
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "proveflow_version": __version__,
            "git_head": _git_head(),
            "eval_module_sha256": module_sha,
            "plan_sha256": PLAN_SHA256,
            "python": platform.python_version(),
            "v1_source": f"git {V1_COMMIT}",
            "v1_classifier_sha256": sha1,
            "v2_source": "working tree src/proveflow/flows/",
            "v2_classifier_sha256": sha2,
            "labels_sha256": labels_sha,
            HELDOUT_COUNTER_KEY: heldout_counter(heldout_dir),
        },
        "results": results,
    }
    out.write_bytes(plan + render(result).encode("utf-8"))
    out.with_suffix(".json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n",
                                        encoding="utf-8", newline="\n")  # fmt: skip
    return result


def main(argv: Sequence[str] | None = None) -> int:
    console = Console(stderr=True)
    ap = argparse.ArgumentParser(prog="python -m proveflow.eval.heldout")
    ap.add_argument("--heldout", type=Path, default=Path("data/eval/roles/heldout_v2"))
    ap.add_argument("--out", type=Path, default=Path("docs/eval/RESULTS_V2.md"))
    ns = ap.parse_args(argv)
    try:
        result = run(ns.heldout, ns.out)
    except (HeldoutError, OSError, ValueError, KeyError) as exc:
        console.print(Text(f"refused: {exc}", style="red"))
        return 1
    md = result["metadata"]
    console.print(Text(f"evaluated once: {HELDOUT_COUNTER_KEY} = {md[HELDOUT_COUNTER_KEY]}; "
                       f"wrote {ns.out} and {ns.out.with_suffix('.json')}"))  # fmt: skip
    return 0


if __name__ == "__main__":
    sys.exit(main())
