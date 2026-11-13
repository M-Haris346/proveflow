"""Held-out v2 sheet (split --heldout) and the metrics guard, on SYNTHETIC tools only."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from proveflow.eval import metrics as met
from proveflow.eval import split as sp


def _jsonl(tmp: Path) -> Path:
    recs = [
        {"server_id": "big", "tool_name": f"tool_{i:02d}", "description": "Do a thing",
         "input_schema": {"properties": {"x": {}}}, "provenance": {"source": "popular",
                                                                   "category": "file"}}
        for i in range(20)
    ] + [
        {"server_id": "small", "tool_name": f"op_{i}", "description": "Other",
         "input_schema": {}, "provenance": {"source": "registry", "category": "other"}}
        for i in range(3)
    ]  # fmt: skip
    p = tmp / "tools.jsonl"
    p.write_text("".join(json.dumps(r) + "\n" for r in recs), encoding="utf-8")
    return p


def _rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        return list(reader.fieldnames or []), list(reader)


def test_heldout_sheet_is_blind_capped_and_counter_starts_at_zero(tmp_path: Path) -> None:
    out = tmp_path / "heldout"
    meta = sp.make_heldout([_jsonl(tmp_path)], out)
    header, rows = _rows(out / sp.HELDOUT_CSV)
    assert header == sp.TEST_COLUMNS  # same columns as labels_test.csv
    assert not any(c.startswith(("server", "proposal", "pred", "classifier", "v1", "v2"))
                   for c in header)  # fmt: skip
    assert all(not r[c] for r in rows for c in sp.LABEL_COLUMNS)  # every label cell empty
    assert [r["tool_id"] for r in rows] == sorted(r["tool_id"] for r in rows)
    assert meta["per_server"] == {"big": 15, "small": 3} and meta["tools_after_cap"] == 18
    assert meta["seed"] == sp.HELDOUT_SEED == 20261201 and meta["cap"] == sp.CAP
    raw = (out / sp.HELDOUT_CSV).read_bytes()
    raw.decode("utf-8")
    assert b"\r\n" not in raw  # LF only
    assert json.loads((out / "metrics_runs.json").read_text(encoding="utf-8")) == {
        "heldout_evaluations": 0
    }
    # same CAP sampler as v1, but its own pre-registered seed
    kept_v1_seed, _ = sp.apply_cap(sp.load_tools([_jsonl(tmp_path)]), seed=sp.SEED)
    kept_ho_seed, _ = sp.apply_cap(sp.load_tools([_jsonl(tmp_path)]), seed=sp.HELDOUT_SEED)
    assert {t.name for t in kept_ho_seed} == {r["tool_name"] for r in rows}
    assert {t.name for t in kept_v1_seed} != {t.name for t in kept_ho_seed}


def test_heldout_rebuild_never_resets_counter_or_overwrites_labels(tmp_path: Path) -> None:
    out = tmp_path / "heldout"
    src = _jsonl(tmp_path)
    sp.make_heldout([src], out)
    (out / "metrics_runs.json").write_text('{"heldout_evaluations": 1}\n', encoding="utf-8")
    sp.make_heldout([src], out)  # unlabeled sheet may be rebuilt...
    assert met.heldout_counter(out) == 1  # ...but the counter is never reset
    header, rows = _rows(out / sp.HELDOUT_CSV)
    rows[0]["sink_a"] = "yes"
    with (out / sp.HELDOUT_CSV).open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=header, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    with pytest.raises(sp.SplitError, match="already contains labels"):
        sp.make_heldout([src], out)


def _fill(out: Path, *, leave_one_empty: bool) -> None:
    header, rows = _rows(out / sp.HELDOUT_CSV)
    for r in rows:
        for c in met.HELDOUT_REQUIRED:
            r[c] = "no"
    if leave_one_empty:
        rows[-1]["private_data_final"] = ""
    with (out / sp.HELDOUT_CSV).open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=header, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


@pytest.mark.parametrize("state", ["unlabeled", "one_cell_empty"])
def test_metrics_refuses_heldout_while_any_label_cell_is_empty(tmp_path: Path, state: str) -> None:
    out = tmp_path / "heldout"
    sp.make_heldout([_jsonl(tmp_path)], out)
    if state == "one_cell_empty":
        _fill(out, leave_one_empty=True)
    with pytest.raises(met.MetricsError, match="refusing to evaluate"):
        met.guard_heldout(out)
    assert met.main(["--heldout", str(out)]) == 1
    assert met.heldout_counter(out) == 0  # refused -> counter unchanged


def test_complete_labels_pass_the_guard_but_nothing_is_evaluated_yet(tmp_path: Path) -> None:
    out = tmp_path / "heldout"
    sp.make_heldout([_jsonl(tmp_path)], out)
    _fill(out, leave_one_empty=False)
    met.guard_heldout(out)  # no exception
    assert met.main(["--heldout", str(out)]) == met.NOT_IMPLEMENTED_EXIT  # Stage D part 2
    assert met.heldout_counter(out) == 0


def test_heldout_counter_is_separate_from_test_counter(tmp_path: Path) -> None:
    out = tmp_path / "heldout"
    sp.make_heldout([_jsonl(tmp_path)], out)
    data = json.loads((out / "metrics_runs.json").read_text(encoding="utf-8"))
    assert set(data) == {"heldout_evaluations"} and "test_evaluations" not in data
