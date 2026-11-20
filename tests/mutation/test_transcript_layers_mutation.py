"""Mutation (R1): make the exact-key check PATH-AWARE (skip the D7 STRUCTURAL_PATHS, as the
shape scan does) -> the NAMED check fails, because a key placed at llm_response.body.id is
then caught by neither layer. This proves the D7 path exclusion must never leak into the
layer that protects a real key."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import runnerchecks
from runnerchecks import STRUCTURAL_PATHS, assert_exact_key_check_sees_past_the_path_exclusion


def _drop(value: object, path: tuple[str, ...]) -> object:
    if path in STRUCTURAL_PATHS:
        return None
    if isinstance(value, dict):
        return {k: _drop(v, (*path, k)) for k, v in value.items()}
    if isinstance(value, list):
        return [_drop(v, (*path, runnerchecks.LIST)) for v in value]
    return value


def _path_aware_exact_key_hits(files: list[Path], key: str) -> list[str]:
    """Mutant: scans only what D7 scans."""
    from proveflow.oracle.matcher import match

    hits = []
    for f in files:
        events = [json.loads(line) for line in f.read_text(encoding="utf-8").splitlines()]
        kept = [_drop({k: v for k, v in e.items() if k != "kind"}, (e["kind"],)) for e in events]
        if match(key, json.dumps(kept)).found:
            hits.append(f.name)
    return hits


def test_a_path_aware_exact_key_check_fails_the_named_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ok, mut = tmp_path / "ok", tmp_path / "mut"
    ok.mkdir()
    mut.mkdir()
    assert_exact_key_check_sees_past_the_path_exclusion(ok)
    monkeypatch.setattr(runnerchecks, "exact_key_hits", _path_aware_exact_key_hits)
    with pytest.raises(AssertionError, match="exact-key check missed the key"):
        assert_exact_key_check_sees_past_the_path_exclusion(mut)
