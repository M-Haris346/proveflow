"""proveflow.eval.split and proveflow.eval.metrics on SYNTHETIC tools and labels only."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from proveflow.eval import metrics as met
from proveflow.eval import split as sp


def _rec(server: str, source: str, name: str, desc: str = "", schema: dict | None = None) -> dict:  # type: ignore[type-arg]
    return {"server_id": server, "tool_name": name, "description": desc,
            "input_schema": schema or {}, "provenance": {"source": source}}  # fmt: skip


def _synthetic_tools(tmp: Path) -> tuple[Path, Path]:
    recs = []
    # big server: 20 tools -> CAP 15
    recs += [_rec("big", "popular", f"send_item_{i:02d}", "Send an item") for i in range(20)]
    # two servers with overlapping names (Jaccard 4/6 = 0.67) -> one group
    shared = ["read_file", "write_file", "list_directory", "move_file"]
    recs += [_rec("fs-a", "reference", n, "Files") for n in [*shared, "a_only"]]
    recs += [_rec("fs-b", "registry", n, "Files") for n in [*shared, "b_only"]]
    for s, src in (("web", "reference"), ("mail", "registry"), ("db", "registry"),
                   ("clock", "reference")):  # fmt: skip
        recs += [_rec(s, src, f"fetch_page_{s}", "Fetch a web page", {"properties": {"url": {}}}),
                 _rec(s, src, f"get_time_{s}", "Return the time"),
                 _rec(s, src, f"query_database_{s}", "Run SQL"),
                 _rec(s, src, f"post_message_{s}", "Post a message")]  # fmt: skip
    jsonl = tmp / "tools.jsonl"
    jsonl.write_text("".join(json.dumps(r) + "\n" for r in recs), encoding="utf-8")
    pg = tmp / "pg.json"
    pg.write_text(json.dumps({"source": "pg-mcp-guard", "commit": "b7a6dce",
                              "provenance": "in-process list_tools, stub executor",
                              "tools": [{"name": "run_query", "description": "Run SQL",
                                         "input_schema": {}}]}), encoding="utf-8")  # fmt: skip
    return jsonl, pg


def test_split_rules(tmp_path: Path) -> None:
    jsonl, pg = _synthetic_tools(tmp_path)
    meta = sp.make_split([jsonl, pg], tmp_path / "split")
    # CAP
    assert meta["tools_before_cap"] == 20 + 10 + 16 + 1
    assert len(meta["capped_out"]["big"]) == 5
    # Jaccard grouping (variant A)
    assert meta["groups"]["fs-a"] == ["fs-a", "fs-b"]
    # forced dev
    assert "pg-mcp-guard" in meta["dev_groups"]
    # rule: share near 0.40, every test group <= 50%, >= 2 groups each side
    assert meta["max_group_share_test"] <= 0.5
    assert len(meta["test_groups"]) >= 2 and len(meta["dev_groups"]) >= 2
    sizes = meta["group_sizes_after_cap"]
    assert meta["test_tools"] == sum(sizes[g] for g in meta["test_groups"])
    assert abs(meta["test_share"] - 0.40) <= 0.10


def test_cap_is_deterministic_and_seeded(tmp_path: Path) -> None:
    jsonl, pg = _synthetic_tools(tmp_path)
    a = sp.make_split([jsonl, pg], tmp_path / "a")
    b = sp.make_split([jsonl, pg], tmp_path / "b")
    assert a["capped_out"] == b["capped_out"]
    for name in ("split.json", "dev_tools.jsonl", "test_tools.jsonl", "labels_dev.csv",
                 "labels_test.csv"):  # fmt: skip
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes()


def test_test_csv_is_blind(tmp_path: Path) -> None:
    jsonl, pg = _synthetic_tools(tmp_path)
    sp.make_split([jsonl, pg], tmp_path / "split")
    with (tmp_path / "split" / "labels_test.csv").open(encoding="utf-8", newline="") as fh:
        header = next(csv.reader(fh))
    assert header == sp.TEST_COLUMNS
    assert not any(c.startswith(("proposal", "pred", "classifier", "server")) for c in header)
    assert "matched_proposal" not in header
    with (tmp_path / "split" / "labels_dev.csv").open(encoding="utf-8", newline="") as fh:
        assert next(csv.reader(fh)) == sp.DEV_COLUMNS


def test_infeasible_split_is_an_error(tmp_path: Path) -> None:
    jsonl = tmp_path / "t.jsonl"
    jsonl.write_text(json.dumps(_rec("only", "reference", "x")) + "\n", encoding="utf-8")
    with pytest.raises(sp.SplitError, match="no split satisfies"):
        sp.make_split([jsonl], tmp_path / "s")
    assert sp.main(["--tools", str(jsonl), "--out-dir", str(tmp_path / "s")]) == 1


# --- metrics ----------------------------------------------------------------------


def _truth(name: str) -> dict[str, bool]:
    """Synthetic ground truth from the tool name (labels are fake on purpose)."""
    return {
        "untrusted_source": name.startswith("fetch_page"),
        "private_data": name.startswith(("query_database", "read_file", "run_query")),
        "sink": name.startswith(
            ("send_item", "post_message", "write_file", "move_file", "fetch_page")
        ),
    }


def _fill(split_dir: Path, *, with_b: bool = True, final: bool = True) -> None:
    yn = {True: "yes", False: "no"}
    for split in ("dev", "test"):
        path = split_dir / f"labels_{split}.csv"
        with path.open(encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            columns = list(reader.fieldnames or [])
            rows = list(reader)
        for i, row in enumerate(rows):
            t = _truth(row["tool_name"])
            for role, v in t.items():
                row[f"{role}_a"] = yn[v]
                if split == "test":
                    # labeler B disagrees on sink for every 3rd row
                    b = (not v) if (role == "sink" and i % 3 == 0) else v
                    row[f"{role}_b"] = yn[b] if with_b else ""
                    row[f"{role}_final"] = yn[v] if final else ""
            row["uncertain_a"] = "yes" if i == 0 else "no"
            row["labeler_a"] = "haris"
        with path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=columns, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)


@pytest.fixture
def labeled(tmp_path: Path) -> Path:
    jsonl, pg = _synthetic_tools(tmp_path)
    sp.make_split([jsonl, pg], tmp_path / "split")
    _fill(tmp_path / "split")
    return tmp_path / "split"


def test_metrics_counts_match_manual_computation(labeled: Path) -> None:
    result = met.compute(labeled)
    test_rows = met.load_rows(labeled, "test")
    for role in sp.ROLES:
        m = result["test"]["pooled"][role]
        tp = sum(r.truth[role] and r.pred[role] for r in test_rows)
        fp = sum(not r.truth[role] and r.pred[role] for r in test_rows)
        fn = sum(r.truth[role] and not r.pred[role] for r in test_rows)
        assert (m["tp"], m["fp"], m["fn"]) == (tp, fp, fn)
        assert m["tp"] + m["fp"] + m["fn"] + m["tn"] == len(test_rows)
        for key, denom in (("precision", tp + fp), ("recall", tp + fn)):
            rate = m[key]
            assert rate["n"] == denom
            if denom >= 10:
                assert rate["ci"] is not None and rate["ci_note"] is None
            elif denom > 0:
                assert rate["ci"] is None and rate["ci_note"] == "N < 10, not reported"


def test_kappa_from_raw_labels(labeled: Path) -> None:
    result = met.compute(labeled)
    k = result["test"]["kappa"]
    assert k["untrusted_source"]["observed_agreement"] == pytest.approx(1.0)
    assert k["sink"]["observed_agreement"] < 1.0
    assert k["sink"]["kappa"] is not None and k["sink"]["kappa"] < 1.0


def test_per_source_breakdown_and_uncertain(labeled: Path) -> None:
    result = met.compute(labeled)
    sources = set(result["test"]["by_source"]) | set(result["dev"]["by_source"])
    assert sources <= {"reference", "popular", "registry", "own"}
    assert sum(b["n"] for b in result["test"]["by_source"].values()) == result["test"]["n"]
    assert result["dev"]["uncertain_rows"] == 1


def test_missing_final_label_is_an_error(tmp_path: Path) -> None:
    jsonl, pg = _synthetic_tools(tmp_path)
    sp.make_split([jsonl, pg], tmp_path / "split")
    _fill(tmp_path / "split", final=False)
    with pytest.raises(met.MetricsError, match="adjudication incomplete"):
        met.compute(tmp_path / "split")


def test_kappa_reported_missing_without_labeler_b(tmp_path: Path) -> None:
    jsonl, pg = _synthetic_tools(tmp_path)
    sp.make_split([jsonl, pg], tmp_path / "split")
    _fill(tmp_path / "split", with_b=False)
    result = met.compute(tmp_path / "split")
    assert result["test"]["kappa"]["sink"]["note"] == "labeler B labels missing"


def test_bad_label_value_is_an_error(labeled: Path) -> None:
    path = labeled / "labels_dev.csv"
    path.write_text(path.read_text(encoding="utf-8").replace(",yes,", ",maybe,", 1), "utf-8")
    with pytest.raises(met.MetricsError, match="expected 'yes' or 'no'"):
        met.compute(labeled)


FORBIDDEN_IN_DEV_ONLY = ("labels_test.csv", "test_tools.jsonl", "metrics_runs.json", "split.json")


def test_dev_only_never_opens_test_files_or_counter(
    labeled: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import builtins
    import io

    (labeled / "metrics_runs.json").write_text('{"test_evaluations": 1}\n', encoding="utf-8")
    counter_before = (labeled / "metrics_runs.json").read_bytes()

    def guard(path: object) -> None:
        if Path(str(path)).name in FORBIDDEN_IN_DEV_ONLY:
            raise AssertionError(f"--dev-only opened {Path(str(path)).name}")

    real_open, real_path_open = builtins.open, Path.open
    real_read_text, real_read_bytes = Path.read_text, Path.read_bytes
    monkeypatch.setattr(builtins, "open", lambda f, *a, **k: (guard(f), real_open(f, *a, **k))[1])
    monkeypatch.setattr(io, "open", builtins.open)
    monkeypatch.setattr(Path, "open", lambda s, *a, **k: (guard(s), real_path_open(s, *a, **k))[1])
    monkeypatch.setattr(
        Path, "read_text", lambda s, *a, **k: (guard(s), real_read_text(s, *a, **k))[1]
    )
    monkeypatch.setattr(
        Path, "read_bytes", lambda s, *a, **k: (guard(s), real_read_bytes(s, *a, **k))[1]
    )

    out = tmp_path / "DEV_RESULTS.md"
    assert met.main(["--split-dir", str(labeled), "--dev-only", "--out", str(out)]) == 0
    monkeypatch.undo()

    assert (labeled / "metrics_runs.json").read_bytes() == counter_before
    text = out.read_text(encoding="utf-8")
    assert "DEV split only" in text and "NOT a claim" in text and "classifier_sha256" in text
    data = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))
    assert data["metadata"]["mode"] == "dev_only" and "test" not in data
    # dev numbers equal the full run's dev block (same rows, same classifier)
    full = met.compute(labeled)
    assert data["dev"]["pooled"] == full["dev"]["pooled"]
    # every error row is a real FN/FP of the dev block
    for role in sp.ROLES:
        m = data["dev"]["pooled"][role]
        kinds = [e["kind"] for e in data["errors"] if e["role"] == role]
        assert (kinds.count("FN"), kinds.count("FP")) == (m["fn"], m["fp"])


def test_dev_only_guard_would_catch_a_test_read(
    labeled: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mutation: if the dev path read the test split, the guard above must fire."""
    real_load = met.load_rows
    monkeypatch.setattr(met, "load_rows", lambda d, s: real_load(d, "test" if s == "dev" else s))
    real_read_text = Path.read_text

    def guarded(self: Path, *a: object, **k: object) -> str:
        if self.name in FORBIDDEN_IN_DEV_ONLY:
            raise AssertionError(f"opened {self.name}")
        return real_read_text(self, *a, **k)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "read_text", guarded)
    with pytest.raises(AssertionError, match=r"test_tools\.jsonl"):
        met.compute_dev(labeled)


def test_results_md_written_with_metadata_and_run_counter(labeled: Path, tmp_path: Path) -> None:
    out = tmp_path / "RESULTS.md"
    assert met.main(["--split-dir", str(labeled), "--out", str(out)]) == 0
    assert met.main(["--split-dir", str(labeled), "--out", str(out)]) == 0
    text = out.read_text(encoding="utf-8")
    for needle in ("classifier_sha256", "labels_sha256", "proveflow_version", "python",
                   "split_seed", "Cohen's kappa", "By source", "Threats to validity",
                   "evaluated 2 time(s)"):  # fmt: skip
        assert needle in text, needle
    data = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))
    assert data["metadata"]["test_evaluations"] == 2
    assert data["metadata"]["split_cap"] == 15
