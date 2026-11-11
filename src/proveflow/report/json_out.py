"""Deterministic JSON rendering: sorted keys, LF, no timestamps."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel


def to_json(data: BaseModel | dict[str, Any]) -> str:
    obj = data.model_dump(mode="json") if isinstance(data, BaseModel) else data
    return json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
