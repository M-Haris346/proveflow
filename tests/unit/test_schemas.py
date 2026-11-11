"""JSON Schema snapshot tests: an accidental model schema change fails the suite.

Regenerate snapshots intentionally with:

    uv run python tests/unit/test_schemas.py --update

then review the diff before committing.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from pydantic import BaseModel

from proveflow.core import (
    Attack,
    ClientConfig,
    Flow,
    Mitigation,
    Payload,
    RedactedText,
    RedactedValue,
    RoleEvidence,
    RunMeta,
    ServerSpec,
    ToolRef,
    ToolSpec,
    Trial,
    Verdict,
)
from proveflow.report.models import (
    DiscoverReport,
    IntrospectionResult,
    RawTool,
    ScanReport,
    ToolChange,
)

MODELS: list[type[BaseModel]] = [
    RedactedValue,
    RedactedText,
    ServerSpec,
    ClientConfig,
    RoleEvidence,
    ToolSpec,
    ToolRef,
    Flow,
    Payload,
    Attack,
    Trial,
    Verdict,
    RunMeta,
    Mitigation,
    DiscoverReport,
    ScanReport,
    IntrospectionResult,
    RawTool,
    ToolChange,
]

SNAPSHOT_DIR = Path(__file__).parent / "schemas"


def _schema_json(model: type[BaseModel]) -> str:
    return json.dumps(model.model_json_schema(), indent=2, sort_keys=True) + "\n"


@pytest.mark.parametrize("model", MODELS, ids=lambda m: m.__name__)
def test_schema_matches_snapshot(model: type[BaseModel]) -> None:
    snapshot_path = SNAPSHOT_DIR / f"{model.__name__}.json"
    if not snapshot_path.exists():
        pytest.fail(
            f"missing snapshot {snapshot_path.name}; run "
            "`uv run python tests/unit/test_schemas.py --update` and review the diff"
        )
    assert _schema_json(model) == snapshot_path.read_text(encoding="utf-8"), (
        f"schema of {model.__name__} changed; if intended, regenerate the snapshot "
        "and review the diff"
    )


def write_snapshots(directory: Path) -> list[Path]:
    """Write every snapshot with LF line endings (never CRLF, even on Windows)."""
    directory.mkdir(parents=True, exist_ok=True)
    written = []
    for m in MODELS:
        path = directory / f"{m.__name__}.json"
        path.write_text(_schema_json(m), encoding="utf-8", newline="\n")
        written.append(path)
    return written


def test_write_snapshots_uses_lf(tmp_path: Path) -> None:
    for path in write_snapshots(tmp_path):
        data = path.read_bytes()
        assert b"\r\n" not in data
        assert data.endswith(b"\n")


if __name__ == "__main__":
    if "--update" not in sys.argv:
        sys.exit("usage: python tests/unit/test_schemas.py --update")
    for p in write_snapshots(SNAPSHOT_DIR):
        print(f"wrote {p.name}")
