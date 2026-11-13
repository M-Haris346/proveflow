"""proveflow.eval.label_sheet (xlsx export/import) and the exact-value held-out guard.
SYNTHETIC tools only; the real held-out sheet is never read here."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
from openpyxl import load_workbook

from proveflow.eval import label_sheet as ls
from proveflow.eval import metrics as met
from proveflow.eval import split as sp

REPO = Path(__file__).resolve().parents[2]
GUIDE = REPO / "docs" / "eval" / "LABELING_GUIDE.md"


def _make(tmp: Path, extra_desc: str = "Run it") -> Path:
    recs = [
        {
            "server_id": "s1",
            "tool_name": f"t{i}",
            "description": f"{extra_desc} {i}",
            "input_schema": {"properties": {"x": {"type": "string"}}},
            "provenance": {"source": "popular", "category": "file"},
        }
        for i in range(4)
    ]
    recs.append({"server_id": "s2", "tool_name": "formula", "input_schema": {},
                 "description": '=HYPERLINK("http://example.invalid","x")',
                 "provenance": {"source": "registry", "category": "other"}})  # fmt: skip
    src = tmp / "tools.jsonl"
    src.write_text("".join(json.dumps(r) + "\n" for r in recs), encoding="utf-8")
    out = tmp / "heldout"
    sp.make_heldout([src], out)
    return out / sp.HELDOUT_CSV


def _fill(
    xlsx: Path, values: dict[str, str] | None = None, *, notes: str = "", uncertain: str = "no"
) -> None:
    wb = load_workbook(xlsx)
    ws = wb["label"]
    header = [c.value for c in ws[1]]
    for row in ws.iter_rows(min_row=2):
        for role in sp.ROLES:
            row[header.index(f"{role}_a")].value = (values or {}).get(role, "no")
        row[header.index("uncertain_a")].value = uncertain
        row[header.index("notes")].value = notes or None
    wb.save(xlsx)


def _csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


# --- guard: exact values ------------------------------------------------------------------


@pytest.mark.parametrize("column", ["sink_final", "uncertain_a"])
@pytest.mark.parametrize("bad", ["Yes ", "y", "", "YES", " no", "true"])
def test_guard_requires_exactly_yes_or_no(tmp_path: Path, bad: str, column: str) -> None:
    assert "uncertain_a" in met.HELDOUT_REQUIRED
    path = _make(tmp_path)
    rows = _csv_rows(path)
    for r in rows:
        for c in met.HELDOUT_REQUIRED:
            r[c] = "no"
    rows[0][column] = bad
    ls.write_csv(path, sp.TEST_COLUMNS, rows)
    with pytest.raises(met.MetricsError, match="not exactly one of"):
        met.guard_heldout(path.parent)
    rows[0][column] = "yes"
    ls.write_csv(path, sp.TEST_COLUMNS, rows)
    met.guard_heldout(path.parent)  # exact values pass
    assert met.ALLOWED_VALUES == ("yes", "no")


# --- export -------------------------------------------------------------------------------


def test_export_layout_protection_dropdown_and_guide(tmp_path: Path) -> None:
    path = _make(tmp_path)
    xlsx = tmp_path / "label.xlsx"
    assert ls.export(path, xlsx, GUIDE) == 5
    wb = load_workbook(xlsx)
    assert wb.sheetnames == ["label", "guide"]
    ws = wb["label"]
    header = [c.value for c in ws[1]]
    assert header == ls.SHEET_COLUMNS
    assert not any(h for h in header if h.startswith("server") or h.endswith(("_b", "_final")))
    assert header[-2:] == ["uncertain_a", "notes"]
    row = ws[2]
    for j, name in enumerate(header):
        locked = row[j].protection.locked
        assert locked is (name in ls.TEXT_COLUMNS), name
    [dv] = ws.data_validations.dataValidation
    assert dv.type == "list" and dv.formula1 == '"yes,no"'
    covered = str(dv.sqref)
    for name in [*(f"{r}_a" for r in sp.ROLES), "uncertain_a"]:
        col = ws.cell(row=1, column=header.index(name) + 1).column_letter
        assert f"{col}2" in covered, name
    notes_col = ws.cell(row=1, column=header.index("notes") + 1).column_letter
    assert f"{notes_col}2" not in covered.split()  # notes are free text
    guide = [c.value or "" for c in wb["guide"]["A"]]
    assert guide == ls.guide_text(GUIDE)
    assert guide[0].startswith("## The three roles")
    assert "## Rules" in guide  # Rules section included...
    assert any(line.startswith("7. `uncertain = yes`") for line in guide)  # ...through its end
    assert not any(line.startswith("## Labelers") for line in guide)  # next section excluded


def test_sheets_protected_but_rows_and_columns_resizable(tmp_path: Path) -> None:
    path = _make(tmp_path)
    xlsx = tmp_path / "label.xlsx"
    ls.export(path, xlsx, GUIDE)
    wb = load_workbook(xlsx)
    for name in ("label", "guide"):
        p = wb[name].protection
        assert p.sheet is True, name  # text cells stay locked
        assert p.formatRows is False and p.formatColumns is False, name  # resizing allowed
        assert p.formatCells is True, name  # cell formats stay protected


def test_export_stores_formula_like_text_as_string_and_refuses_overwrite(tmp_path: Path) -> None:
    path = _make(tmp_path)
    xlsx = tmp_path / "label.xlsx"
    ls.export(path, xlsx, GUIDE)
    ws = load_workbook(xlsx)["label"]
    cells = [c for c in ws["C"] if isinstance(c.value, str) and c.value.startswith("=")]
    assert cells and all(c.data_type == "s" for c in cells)  # text, never a formula
    with pytest.raises(ls.LabelSheetError, match="refusing to overwrite"):
        ls.export(path, xlsx, GUIDE)


@pytest.mark.parametrize(("bad", "msg"), [("a\rb", "CR"), ("a\x01b", "control"),
                                          ("x" * 40000, "Excel cell")])  # fmt: skip
def test_export_refuses_text_that_cannot_round_trip(tmp_path: Path, bad: str, msg: str) -> None:
    path = _make(tmp_path)
    rows = _csv_rows(path)
    rows[0]["description"] = bad
    ls.write_csv(path, sp.TEST_COLUMNS, rows)
    with pytest.raises(ls.LabelSheetError, match=msg):
        ls.export(path, tmp_path / "x.xlsx", GUIDE)


# --- import -------------------------------------------------------------------------------


def test_round_trip(tmp_path: Path) -> None:
    path = _make(tmp_path)
    before = _csv_rows(path)
    xlsx = tmp_path / "label.xlsx"
    ls.export(path, xlsx, GUIDE)
    _fill(xlsx, {"untrusted_source": "yes", "private_data": "no", "sink": "yes"}, notes="n",
          uncertain="yes")  # fmt: skip
    counts, sha = ls.import_(xlsx, path, "Labeler One")
    assert counts == {"untrusted_source_a": {"yes": 5}, "private_data_a": {"no": 5},
                      "sink_a": {"yes": 5}, "uncertain_a": {"yes": 5}}  # fmt: skip
    raw = path.read_bytes()
    assert b"\r\n" not in raw and not raw.startswith(b"\xef\xbb\xbf")
    import hashlib

    assert sha == hashlib.sha256(raw).hexdigest()
    after = _csv_rows(path)
    for b, a in zip(before, after, strict=True):
        for col in ls.TEXT_COLUMNS:
            assert a[col] == b[col]
        for role in sp.ROLES:
            assert a[f"{role}_a"] == a[f"{role}_final"] and a[f"{role}_b"] == ""
        assert a["labeler_a"] == "Labeler One" and a["note_a"] == "n"
        assert a["uncertain_a"] == "yes" and a["uncertain_b"] == ""
    met.guard_heldout(path.parent)  # complete and exact -> guard passes
    _, sha2 = ls.import_(xlsx, path, "Labeler One")  # identical re-import is fine
    assert sha2 == sha


def test_tampered_description_is_refused_and_csv_unchanged(tmp_path: Path) -> None:
    path = _make(tmp_path)
    xlsx = tmp_path / "label.xlsx"
    ls.export(path, xlsx, GUIDE)
    _fill(xlsx)
    wb = load_workbook(xlsx)
    wb["label"]["C3"].value = "edited by hand"
    wb.save(xlsx)
    before = path.read_bytes()
    with pytest.raises(ls.LabelSheetError, match="description differs"):
        ls.import_(xlsx, path, "L")
    assert path.read_bytes() == before


@pytest.mark.parametrize("change", ["extra", "missing", "duplicate"])
def test_extra_missing_or_duplicate_rows_are_refused(tmp_path: Path, change: str) -> None:
    path = _make(tmp_path)
    xlsx = tmp_path / "label.xlsx"
    ls.export(path, xlsx, GUIDE)
    _fill(xlsx)
    wb = load_workbook(xlsx)
    ws = wb["label"]
    if change == "missing":
        ws.delete_rows(ws.max_row)
    else:
        src = [c.value for c in ws[2]]
        if change == "extra":
            src[0] = "t-000000000000"
        ws.append(src)
    wb.save(xlsx)
    with pytest.raises(ls.LabelSheetError, match=r"missing|extra|duplicate"):
        ls.import_(xlsx, path, "L")


@pytest.mark.parametrize("bad", ["Yes ", "y", "", "YES", "maybe"])
def test_bad_value_is_refused(tmp_path: Path, bad: str) -> None:
    path = _make(tmp_path)
    xlsx = tmp_path / "label.xlsx"
    ls.export(path, xlsx, GUIDE)
    _fill(xlsx)
    wb = load_workbook(xlsx)
    ws = wb["label"]
    header = [c.value for c in ws[1]]
    ws.cell(row=3, column=header.index("private_data_a") + 1).value = bad or None
    wb.save(xlsx)
    with pytest.raises(ls.LabelSheetError, match="not exactly one of"):
        ls.import_(xlsx, path, "L")


def test_existing_final_conflict_is_refused(tmp_path: Path) -> None:
    path = _make(tmp_path)
    xlsx = tmp_path / "label.xlsx"
    ls.export(path, xlsx, GUIDE)
    _fill(xlsx)  # all "no"
    rows = _csv_rows(path)
    rows[1]["sink_final"] = "yes"  # an existing final label that disagrees
    ls.write_csv(path, sp.TEST_COLUMNS, rows)
    with pytest.raises(ls.LabelSheetError, match="existing sink_final conflicts"):
        ls.import_(xlsx, path, "L")


def test_existing_uncertain_conflict_is_refused(tmp_path: Path) -> None:
    path = _make(tmp_path)
    xlsx = tmp_path / "label.xlsx"
    ls.export(path, xlsx, GUIDE)
    _fill(xlsx, uncertain="no")
    rows = _csv_rows(path)
    rows[2]["uncertain_a"] = "yes"
    ls.write_csv(path, sp.TEST_COLUMNS, rows)
    with pytest.raises(ls.LabelSheetError, match="existing uncertain_a conflicts"):
        ls.import_(xlsx, path, "L")


@pytest.mark.parametrize("bad", ["Yes ", "y", "", "maybe"])
def test_bad_uncertain_value_is_refused(tmp_path: Path, bad: str) -> None:
    path = _make(tmp_path)
    xlsx = tmp_path / "label.xlsx"
    ls.export(path, xlsx, GUIDE)
    _fill(xlsx)
    wb = load_workbook(xlsx)
    ws = wb["label"]
    header = [c.value for c in ws[1]]
    ws.cell(row=4, column=header.index("uncertain_a") + 1).value = bad or None
    wb.save(xlsx)
    with pytest.raises(ls.LabelSheetError, match="uncertain_a is not exactly one of"):
        ls.import_(xlsx, path, "L")


@pytest.mark.parametrize("labeler", ["", "  ", "two\nlines"])
def test_labeler_must_be_one_non_empty_line(tmp_path: Path, labeler: str) -> None:
    path = _make(tmp_path)
    xlsx = tmp_path / "label.xlsx"
    ls.export(path, xlsx, GUIDE)
    _fill(xlsx)
    with pytest.raises(ls.LabelSheetError, match="--labeler"):
        ls.import_(xlsx, path, labeler)


def test_cli_prints_only_counts_and_sha(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = _make(tmp_path)
    xlsx = tmp_path / "label.xlsx"
    assert ls.main(["export", "--csv", str(path), "--out", str(xlsx), "--guide", str(GUIDE)]) == 0
    _fill(xlsx)
    assert ls.main(["import", str(xlsx), "--labeler", "L", "--csv", str(path)]) == 0
    err = capsys.readouterr().err
    assert "sha256" in err and "Run it" not in err and "HYPERLINK" not in err
