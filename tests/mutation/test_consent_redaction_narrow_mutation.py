"""Mutation: remove the `--token X` redaction rule (R-ARG-NEXT) -> the NAMED narrow-wrap
redaction check fails (the planted value leaks into the wrapped consent prompt)."""

from __future__ import annotations

from pathlib import Path

import pytest

from narrowchecks import assert_redaction_survives_narrow_wrap
from proveflow.discover import redact_rules


def test_removing_the_flag_rule_leaks_into_the_wrapped_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ok, mut = tmp_path / "ok", tmp_path / "mut"
    ok.mkdir()
    mut.mkdir()
    with monkeypatch.context() as m:
        assert_redaction_survives_narrow_wrap(ok, m)
    rules = tuple(r for r in redact_rules.RULES if r.id != "R-ARG-NEXT")
    assert len(rules) == len(redact_rules.RULES) - 1
    monkeypatch.setattr(redact_rules, "RULES", rules)
    with pytest.raises(AssertionError, match="planted secret leaked"):
        assert_redaction_survives_narrow_wrap(mut, monkeypatch)
