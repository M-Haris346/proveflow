"""Mutation: weaken the twin guard by one rule -> the NAMED guard safety check fails."""

from __future__ import annotations

from pathlib import Path

import pytest

from proveflow.twin import generator, guard
from twinchecks import assert_guard_refuses_io_scripts, assert_write_refuses_guard_failing_source


def test_allowing_one_forbidden_import_fails_the_named_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert_guard_refuses_io_scripts()
    monkeypatch.setattr(
        guard, "ALLOWED_FROM_IMPORTS", guard.ALLOWED_FROM_IMPORTS | {("subprocess", "run", None)}
    )
    with pytest.raises(AssertionError, match="subprocess_run"):
        assert_guard_refuses_io_scripts()


def test_allowing_open_fails_the_named_check(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(guard, "FORBIDDEN_BUILTINS", guard.FORBIDDEN_BUILTINS - {"open"})
    with pytest.raises(AssertionError, match="open_write"):
        assert_guard_refuses_io_scripts()


def test_allowing_print_fails_the_named_check(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(guard, "FORBIDDEN_BUILTINS", guard.FORBIDDEN_BUILTINS - {"print"})
    with pytest.raises(AssertionError, match="print_to_stdout"):
        assert_guard_refuses_io_scripts()


def test_dropping_the_dunder_rule_fails_the_named_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """Dunder ATTRIBUTES are also blocked by the object-attribute allowlist (defence in depth);
    the dunder rule is load-bearing for dunder NAMES, e.g. ``__builtins__['open']``."""
    monkeypatch.setattr(guard, "_is_dunder", lambda name: False)
    with pytest.raises(AssertionError, match="builtins_subscript"):
        assert_guard_refuses_io_scripts()


def test_allowing_any_module_attribute_fails_the_named_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        guard,
        "ALLOWED_IMPORTS",
        guard.ALLOWED_IMPORTS | {("os", None)},
    )
    monkeypatch.setitem(guard.ALLOWED_MODULE_ATTRS, "os", frozenset({"remove"}))
    with pytest.raises(AssertionError, match="os_remove"):
        assert_guard_refuses_io_scripts()


def test_write_without_the_guard_step_fails_the_named_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ok, mut = tmp_path / "ok", tmp_path / "mut"
    assert_write_refuses_guard_failing_source(ok)
    monkeypatch.setattr(generator, "check_no_io", lambda source: None)
    with pytest.raises(AssertionError, match="wrote a guard-failing twin"):
        assert_write_refuses_guard_failing_source(mut)
