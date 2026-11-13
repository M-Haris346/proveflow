"""proveflow.eval.heldout on SYNTHETIC data (the real held-out set is never read here)."""

from __future__ import annotations

import csv
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from proveflow.eval import heldout as ho
from proveflow.eval import label_sheet as ls
from proveflow.eval import metrics as met
from proveflow.eval import split as sp
from proveflow.flows import roles as v2roles

REPO = Path(__file__).resolve().parents[2]
RESULTS = REPO / "docs" / "eval" / "RESULTS_V2.md"

# one synthetic tool per v2 rule (same invented tools as tests/unit/test_roles_v2.py)
RULE_TOOLS: dict[str, tuple[str, str, dict[str, Any]]] = {
    "C1": ("render_chart", "Render.", {"outputPath": {"description": "Where it is saved."}}),
    "C2": ("vcs_blame", "", {"repository": {}}),
    "C3": ("vcs_revert", "", {}),
    "C4": ("respond_prompt", "Answer the dialog on the page.", {"prompt_text": {}}),
    "C5": ("browser_hover_item", "", {}),
    "C6": ("update_notes", "Update a file in the personal document store.", {}),
    "C7": ("navigate_history", "", {}),
    "C8": ("ping_endpoint", "Ping it.", {"url": {}}),
    "C9": ("ask_assistant", "", {"model": {}, "prompt": {}}),
    "C11a": ("page_snapshot", "", {}),
    "C11c": ("lookup_rows", "Rows are untrusted data.", {}),
    "C11d": ("sandbox_tool", "Executes arbitrary code in the worker.", {}),
    "C12": ("configure_client", "", {"customHeaders": {}}),
}


def _plan_text() -> bytes:
    text = RESULTS.read_bytes()
    marker = ho.PLAN_END.encode()
    return text[: text.index(marker) + len(marker)]


def _setup(tmp: Path, *, fill: bool = True, uncertain_every: int = 3) -> tuple[Path, Path]:
    recs = [{"server_id": "syn", "tool_name": n, "description": d,
             "input_schema": {"properties": p}, "provenance": {"source": "x", "category": "y"}}
            for n, d, p in RULE_TOOLS.values()]  # fmt: skip
    src = tmp / "tools.jsonl"
    src.write_text("".join(json.dumps(r) + "\n" for r in recs), encoding="utf-8")
    hdir = tmp / "heldout"
    sp.make_heldout([src], hdir)
    if fill:
        path = hdir / sp.HELDOUT_CSV
        with path.open(encoding="utf-8", newline="") as fh:
            rows = list(csv.DictReader(fh))
        for i, r in enumerate(rows):
            for role in sp.ROLES:
                r[f"{role}_a"] = r[f"{role}_final"] = "yes" if role == "sink" else "no"
            r["uncertain_a"] = "yes" if i % uncertain_every == 0 else "no"
        ls.write_csv(path, sp.TEST_COLUMNS, rows)
    out = tmp / "RESULTS_V2.md"
    out.write_bytes(_plan_text())
    return hdir, out


def _loaders() -> tuple[Any, Any]:
    return (lambda: (v2roles, "sha-a"), lambda: (v2roles, "sha-b"))


def test_plan_in_repo_matches_the_fixed_sha() -> None:
    import hashlib

    assert hashlib.sha256(_plan_text()).hexdigest() == ho.PLAN_SHA256


def test_single_run_increments_counter_then_refuses(tmp_path: Path) -> None:
    hdir, out = _setup(tmp_path)
    result = ho.run(hdir, out, loaders=_loaders(), expected=("sha-a", "sha-b"))
    assert met.heldout_counter(hdir) == 1
    assert result["metadata"]["heldout_evaluations"] == 1
    text = out.read_bytes()
    assert text.startswith(_plan_text())  # plan copied byte-for-byte
    assert b"## Generated results" in text and out.with_suffix(".json").exists()
    r = result["results"]
    assert r["primary"]["n"] == 13
    assert r["secondary"]["n"] == 13 - r["uncertain_rows"]
    for ver in ("v1", "v2"):
        for role in sp.ROLES:
            m = r["primary"][ver][role]
            assert m["tp"] + m["fp"] + m["fn"] + m["tn"] == 13
    # a second run is refused (the counter is not reset by re-writing the plan)
    out.write_bytes(_plan_text())
    with pytest.raises(ho.HeldoutError, match="already evaluated"):
        ho.run(hdir, out, loaders=_loaders(), expected=("sha-a", "sha-b"))
    assert met.heldout_counter(hdir) == 1


def test_refused_when_labels_incomplete(tmp_path: Path) -> None:
    hdir, out = _setup(tmp_path, fill=False)
    with pytest.raises(ho.HeldoutError, match="refusing to evaluate"):
        ho.run(hdir, out, loaders=_loaders(), expected=("sha-a", "sha-b"))
    assert met.heldout_counter(hdir) == 0


def test_refused_on_classifier_sha_mismatch_counter_untouched(tmp_path: Path) -> None:
    hdir, out = _setup(tmp_path)
    with pytest.raises(ho.HeldoutError, match="classifier sha mismatch"):
        ho.run(hdir, out, loaders=_loaders(), expected=("sha-a", "WRONG"))
    assert met.heldout_counter(hdir) == 0


def test_refused_when_plan_changed_or_results_exist(tmp_path: Path) -> None:
    hdir, out = _setup(tmp_path)
    out.write_bytes(_plan_text().replace(b"Metric plan", b"Metric PLAN"))
    with pytest.raises(ho.HeldoutError, match="differs from the fixed plan"):
        ho.run(hdir, out, loaders=_loaders(), expected=("sha-a", "sha-b"))
    out.write_bytes(_plan_text() + b"\nsomething\n")
    with pytest.raises(ho.HeldoutError, match="already has content"):
        ho.run(hdir, out, loaders=_loaders(), expected=("sha-a", "sha-b"))
    assert met.heldout_counter(hdir) == 0


def test_v1_split_counter_is_never_touched(tmp_path: Path) -> None:
    split_counter = REPO / "data" / "eval" / "roles" / "split" / "metrics_runs.json"
    before = split_counter.read_bytes()
    hdir, out = _setup(tmp_path)
    ho.run(hdir, out, loaders=_loaders(), expected=("sha-a", "sha-b"))
    assert split_counter.read_bytes() == before


@pytest.mark.parametrize("rule", list(RULE_TOOLS))
def test_exposure_detects_each_rule_on_its_synthetic_tool(rule: str) -> None:
    name, desc, props = RULE_TOOLS[rule]
    rec = {"tool_name": name, "server_id": "syn", "description": desc,
           "input_schema": {"properties": props}}  # fmt: skip
    assert rule in ho.exposure(v2roles, rec)


def test_exposure_reason_keys_exist_in_frozen_v2_source() -> None:
    source = Path(str(v2roles.__file__)).read_text(encoding="utf-8")
    for rule, key in ho.EVIDENCE_RULES.items():
        assert key.split("'")[0].split("(")[0].strip() in source, rule
    assert set(ho.RULE_ORDER) == set(RULE_TOOLS)
    assert not set(ho.NOT_IN_V2) & set(ho.RULE_ORDER)


def test_exposure_zero_is_reported_untested(tmp_path: Path) -> None:
    rec = {"tool_name": "get_current_time", "server_id": "s", "description": "Time",
           "input_schema": {}}  # fmt: skip
    assert ho.exposure(v2roles, rec) == set()


def test_v2_loader_sha_matches_frozen_value() -> None:
    _, sha = ho.load_v2()
    assert sha == ho.V2_SHA256


def _have_commit(rev: str) -> bool:
    res = subprocess.run(["git", "cat-file", "-e", f"{rev}^{{commit}}"], cwd=REPO,  # noqa: S607
                         capture_output=True)  # fmt: skip
    return res.returncode == 0


@pytest.mark.skipif(not _have_commit(ho.V1_COMMIT), reason="v1 commit not in local history")
def test_v1_loader_reproduces_frozen_sha_and_v1_behaviour() -> None:
    v1, sha = ho.load_v1()
    assert sha == ho.V1_SHA256
    hover = {"tool_name": "browser_hover_item", "server_id": "s", "description": "",
             "input_schema": {}}  # fmt: skip
    assert ho.predict(v1, hover)["sink"] is True  # v1: hover was a browser sink
    assert ho.predict(v2roles, hover)["sink"] is False  # v2 (C5): it is not
