"""Error-proof labeling of the blind held-out sheet via an .xlsx (checkpoint 1c Stage D).

    python -m proveflow.eval.label_sheet export [--csv ...] [--out out/heldout_v2_labeling.xlsx]
    python -m proveflow.eval.label_sheet import <xlsx> --labeler "<text>" [--csv ...]

export: sheet "label" = tool_id, tool_name, description, input_schema (wrapped, locked: the
sheet is protected and only label/notes cells are editable; rows and columns may still be
resized), then ONLY the <role>_a columns, uncertain_a (one per tool, as in v1) - each a
dropdown of ALLOWED_VALUES - and a notes column. No server id, no _b/_final, no prediction.
Sheet "guide" = verbatim from docs/eval/LABELING_GUIDE.md, from "## The three roles" through
the end of "## Rules". Every text cell is stored as a string (never a formula). Refuses to
overwrite an existing xlsx.

import: refuses unless the xlsx has exactly the CSV's tool_ids (no missing/extra/duplicate),
every non-label column equals the committed CSV exactly, and every role cell and uncertain_a
is exactly one of ALLOWED_VALUES (no blanks: import is all-or-nothing). Writes the CSV with
<role>_a and uncertain_a from the xlsx, <role>_final = <role>_a (single labeler; _b left
empty), labeler_a = --labeler, note_a = notes. Refuses if the CSV already holds different
_a/_final/uncertain_a values. UTF-8, LF, no BOM. Prints only counts per column and value, and
the new sha256. Never prints a row.

v1 encoding of uncertainty (kept identical): one column uncertain_a per tool, values yes/no,
every v1 row filled; metrics count a row as uncertain if uncertain_a or uncertain_b is "yes"
and report that count only (it never changes P/R).

openpyxl is a DEV-only dependency, imported lazily (the proveflow CLI never needs it).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.text import Text

from proveflow.eval.metrics import ALLOWED_VALUES
from proveflow.eval.split import HELDOUT_CSV, ROLES, TEST_COLUMNS

DEFAULT_CSV = Path("data/eval/roles/heldout_v2") / HELDOUT_CSV
DEFAULT_XLSX = Path("out/heldout_v2_labeling.xlsx")
DEFAULT_GUIDE = Path("docs/eval/LABELING_GUIDE.md")
TEXT_COLUMNS = ["tool_id", "tool_name", "description", "input_schema"]
ROLE_COLUMNS = [f"{r}_a" for r in ROLES]
UNCERTAIN = "uncertain_a"
CHOICE_COLUMNS = [*ROLE_COLUMNS, UNCERTAIN]  # every one a yes/no dropdown, all required
NOTES = "notes"
SHEET_COLUMNS = [*TEXT_COLUMNS, *CHOICE_COLUMNS, NOTES]
EXCEL_CELL_MAX = 32767  # characters per cell (Excel limit)
_GUIDE_START = "## The three roles"
_GUIDE_LAST = "## Rules"  # included; the guide sheet ends before the next "## " heading


class LabelSheetError(RuntimeError):
    """Refusal. Messages name columns, row numbers and counts, never cell contents."""


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        return list(reader.fieldnames or []), list(reader)


def guide_text(path: Path) -> list[str]:
    """Verbatim from '## The three roles' through the end of '## Rules' (up to the next
    '## ' heading, or the end of the file)."""
    lines = path.read_text(encoding="utf-8").splitlines()
    start = next((i for i, ln in enumerate(lines) if ln.startswith(_GUIDE_START)), None)
    rules = next((i for i, ln in enumerate(lines) if ln.startswith(_GUIDE_LAST)), None)
    if start is None or rules is None or rules <= start:
        raise LabelSheetError(f"{path}: '{_GUIDE_START}' / '{_GUIDE_LAST}' sections not found")
    end = next((i for i in range(rules + 1, len(lines)) if lines[i].startswith("## ")),
               len(lines))  # fmt: skip
    return lines[start:end]


def _protect(ws: Any) -> None:
    """Lock the sheet (only unlocked cells editable) but allow resizing rows/columns.
    openpyxl SheetProtection: formatRows/formatColumns True = that action is PROTECTED."""
    ws.protection.sheet = True
    ws.protection.formatRows = False
    ws.protection.formatColumns = False


def _check_cell_text(value: str, where: str) -> None:
    from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE

    if len(value) > EXCEL_CELL_MAX:
        raise LabelSheetError(f"{where}: longer than an Excel cell allows ({len(value)} chars)")
    if ILLEGAL_CHARACTERS_RE.search(value):
        raise LabelSheetError(f"{where}: contains control characters xlsx cannot store")
    if "\r" in value:
        raise LabelSheetError(f"{where}: contains CR (would not round-trip)")


def _set_text(cell: Any, value: str) -> None:
    """Store as a plain string even if it starts with '=' (no formula injection)."""
    cell.value = value
    cell.data_type = "s"


def export(csv_path: Path, out: Path, guide: Path) -> int:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, Protection
    from openpyxl.worksheet.datavalidation import DataValidation

    if out.exists():
        raise LabelSheetError(f"{out} exists; refusing to overwrite (it may hold your labels)")
    header, rows = read_csv(csv_path)
    if header != TEST_COLUMNS:
        raise LabelSheetError(f"{csv_path}: header differs from the blind test columns")
    wb = Workbook()
    ws = wb.active
    ws.title = "label"
    for j, name in enumerate(SHEET_COLUMNS, start=1):
        cell = ws.cell(row=1, column=j)
        _set_text(cell, name)
        cell.font = Font(bold=True)
    choices = ",".join(ALLOWED_VALUES)
    dv = DataValidation(type="list", formula1=f'"{choices}"', allow_blank=True,
                        showErrorMessage=True, errorTitle="Not allowed",
                        error=f"Use one of: {choices}")  # fmt: skip
    ws.add_data_validation(dv)
    wrap = Alignment(wrap_text=True, vertical="top")
    for i, row in enumerate(rows, start=2):
        for j, name in enumerate(SHEET_COLUMNS, start=1):
            cell = ws.cell(row=i, column=j)
            if name in TEXT_COLUMNS:
                _check_cell_text(row[name], f"row {i} column {name}")
                _set_text(cell, row[name])
                cell.alignment = wrap
                cell.protection = Protection(locked=True)
            else:
                existing = row.get("note_a" if name == NOTES else name, "") or ""
                if existing:
                    _set_text(cell, existing)
                cell.protection = Protection(locked=False)
                if name in CHOICE_COLUMNS:
                    dv.add(cell.coordinate)
    for j, width in enumerate((16, 24, 70, 70, 16, 16, 16, 14, 40), start=1):
        ws.column_dimensions[ws.cell(row=1, column=j).column_letter].width = width
    ws.freeze_panes = "B2"
    _protect(ws)  # only label + notes cells editable; rows/columns resizable
    g = wb.create_sheet("guide")
    g.column_dimensions["A"].width = 120
    for i, line in enumerate(guide_text(guide), start=1):
        cell = g.cell(row=i, column=1)
        _set_text(cell, line)
        cell.alignment = Alignment(wrap_text=True, vertical="top")
    _protect(g)
    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)
    return len(rows)


def _cell_str(value: Any) -> str:
    return "" if value is None else str(value)


def read_xlsx(path: Path) -> list[dict[str, str]]:
    from openpyxl import load_workbook

    wb = load_workbook(path, read_only=True, data_only=False)
    if "label" not in wb.sheetnames:
        raise LabelSheetError(f"{path}: no sheet named 'label'")
    it = wb["label"].iter_rows(values_only=True)
    header = [_cell_str(v) for v in next(it, ())]
    if header[: len(SHEET_COLUMNS)] != SHEET_COLUMNS or any(header[len(SHEET_COLUMNS) :]):
        raise LabelSheetError(f"{path}: 'label' sheet columns differ from {SHEET_COLUMNS}")
    out: list[dict[str, str]] = []
    for values in it:
        cells = [_cell_str(v) for v in values][: len(SHEET_COLUMNS)]
        cells += [""] * (len(SHEET_COLUMNS) - len(cells))
        if not any(cells):
            continue  # trailing empty rows
        out.append(dict(zip(SHEET_COLUMNS, cells, strict=True)))
    wb.close()
    return out


def merge(csv_rows: list[dict[str, str]], xlsx_rows: list[dict[str, str]], labeler: str
          ) -> list[dict[str, str]]:  # fmt: skip
    """Validated merge (pure; raises LabelSheetError on any problem)."""
    if not labeler.strip() or "\n" in labeler or "\r" in labeler:
        raise LabelSheetError("--labeler must be a non-empty single line")
    ids = [r["tool_id"] for r in xlsx_rows]
    dupes = sorted(k for k, n in Counter(ids).items() if n > 1)
    if dupes:
        raise LabelSheetError(f"duplicate tool_id rows in xlsx: {len(dupes)}")
    by_id = {r["tool_id"]: r for r in xlsx_rows}
    want = {r["tool_id"] for r in csv_rows}
    missing, extra = want - set(by_id), set(by_id) - want
    if missing or extra:
        raise LabelSheetError(f"xlsx rows differ from the CSV: {len(missing)} missing, "
                              f"{len(extra)} extra tool_id(s)")  # fmt: skip
    merged: list[dict[str, str]] = []
    for n, row in enumerate(csv_rows, start=2):
        x = by_id[row["tool_id"]]
        for col in TEXT_COLUMNS:
            if x[col] != row[col]:
                raise LabelSheetError(f"CSV line {n}: column {col} differs from the committed CSV")
        new = dict(row)
        for role in ROLES:
            value = x[f"{role}_a"]
            if value not in ALLOWED_VALUES:
                raise LabelSheetError(
                    f"CSV line {n}: {role}_a is not exactly one of {list(ALLOWED_VALUES)}"
                )
            for col in (f"{role}_a", f"{role}_final"):
                if row.get(col, "") not in ("", value):
                    raise LabelSheetError(
                        f"CSV line {n}: existing {col} conflicts with the xlsx value"
                    )
            new[f"{role}_a"] = value
            new[f"{role}_final"] = value
            new[f"{role}_b"] = ""
        unc = x[UNCERTAIN]
        if unc not in ALLOWED_VALUES:
            raise LabelSheetError(
                f"CSV line {n}: {UNCERTAIN} is not exactly one of {list(ALLOWED_VALUES)}"
            )
        if row.get(UNCERTAIN, "") not in ("", unc):
            raise LabelSheetError(
                f"CSV line {n}: existing {UNCERTAIN} conflicts with the xlsx value"
            )
        new[UNCERTAIN] = unc
        new["labeler_a"] = labeler.strip()
        new["note_a"] = x[NOTES]
        merged.append(new)
    return merged


def write_csv(path: Path, header: list[str], rows: list[dict[str, str]]) -> str:
    buf = io.StringIO(newline="")
    w = csv.DictWriter(buf, fieldnames=header, lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    data = buf.getvalue().encode("utf-8")  # no BOM
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def import_(xlsx: Path, csv_path: Path, labeler: str) -> tuple[dict[str, dict[str, int]], str]:
    header, csv_rows = read_csv(csv_path)
    if header != TEST_COLUMNS:
        raise LabelSheetError(f"{csv_path}: header differs from the blind test columns")
    merged = merge(csv_rows, read_xlsx(xlsx), labeler)
    sha = write_csv(csv_path, header, merged)
    counts = {c: dict(sorted(Counter(row[c] for row in merged).items())) for c in CHOICE_COLUMNS}
    return counts, sha


def main(argv: Sequence[str] | None = None) -> int:
    console = Console(stderr=True)
    ap = argparse.ArgumentParser(prog="python -m proveflow.eval.label_sheet")
    sub = ap.add_subparsers(dest="cmd", required=True)
    ex = sub.add_parser("export")
    ex.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    ex.add_argument("--out", type=Path, default=DEFAULT_XLSX)
    ex.add_argument("--guide", type=Path, default=DEFAULT_GUIDE)
    im = sub.add_parser("import")
    im.add_argument("xlsx", type=Path)
    im.add_argument("--labeler", required=True)
    im.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    ns = ap.parse_args(argv)
    try:
        if ns.cmd == "export":
            n = export(ns.csv, ns.out, ns.guide)
            console.print(Text(f"exported {n} rows -> {ns.out}"))
            return 0
        counts, sha = import_(ns.xlsx, ns.csv, ns.labeler)
    except (LabelSheetError, OSError) as exc:
        console.print(Text(f"refused: {exc}", style="red"))
        return 1
    for role, c in counts.items():
        console.print(Text(f"{role}: {c}"))
    console.print(Text(f"wrote {ns.csv} sha256 {sha}"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
