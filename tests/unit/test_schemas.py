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
    RedactedValue,
    RoleEvidence,
    RunMeta,
    ServerSpec,
    ToolSpec,
    Trial,
    Verdict,
)

MODELS: list[type[BaseModel]] = [
    RedactedValue,
    ServerSpec,
    ClientConfig,
    RoleEvidence,
    ToolSpec,
    Flow,
    Payload,
    Attack,
    Trial,
    Verdict,
    RunMeta,
    Mitigation,
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


if __name__ == "__main__":
    if "--update" not in sys.argv:
        sys.exit("usage: python tests/unit/test_schemas.py --update")
    SNAPSHOT_DIR.mkdir(exist_ok=True)
    for m in MODELS:
        (SNAPSHOT_DIR / f"{m.__name__}.json").write_text(_schema_json(m), encoding="utf-8")
        print(f"wrote {m.__name__}.json")
