"""Mutations of the patch writers (Phase 8): one weakening per rule, each killed by its named
check (tests/fixchecks.py). Each test runs the check unmutated first, then under the mutant."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import fixchecks
from proveflow.core.client import ClientKind
from proveflow.discover import readers
from proveflow.fix import render, writer


def _ok_then(tmp_path: Path, mp: pytest.MonkeyPatch, check: Callable[[Path], None],
             patch: Callable[[pytest.MonkeyPatch], None], message: str) -> None:  # fmt: skip
    check(tmp_path / "ok")
    with mp.context() as m:
        patch(m)
        with pytest.raises(AssertionError, match=message):
            check(tmp_path / "mut")


def test_dropping_the_shadowed_entries_fails_the_coverage_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mutant: M1 removes only the winning entry; the shadowed one would take over."""
    _ok_then(tmp_path, monkeypatch, fixchecks.assert_m1_removes_every_entry_that_would_connect,
             lambda m: m.setattr(render, "shadowed_entries", lambda *a: []),
             "did not cover the shadowed user entry")  # fmt: skip


def test_a_wrong_vscode_key_fails_the_pointer_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mutant: VS Code's key is taken as ``mcpServers`` (it is ``servers``)."""
    _ok_then(tmp_path, monkeypatch, lambda p: fixchecks.assert_m1_pointers_are_the_readers_keys(),
             lambda m: m.setitem(readers.SERVERS_KEY, ClientKind.VSCODE, "mcpServers"),
             "vscode project: pointer")  # fmt: skip


def test_no_name_normalisation_fails_the_rule_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mutant: the server name goes into the rule as configured (``.`` and space kept)."""
    _ok_then(tmp_path, monkeypatch, fixchecks.assert_m3_rule_form_is_the_cited_one,
             lambda m: m.setattr(render, "rule_token", lambda name: name),
             r"m3_rule\('my.server'")  # fmt: skip


def test_rendering_m3_for_cursor_fails_the_refusal_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mutant: Cursor is treated as a client with a cited per-tool approval syntax."""
    _ok_then(tmp_path, monkeypatch, lambda p: fixchecks.assert_m3_is_refused_for_cursor(),
             lambda m: m.setattr(render, "M3_CLIENTS",
                                 frozenset({ClientKind.CLAUDE_CODE, ClientKind.CURSOR})),
             "not refused for Cursor")  # fmt: skip


def test_an_overwriting_writer_fails_the_writer_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mutant: the existing-target refusal is gone."""
    _ok_then(tmp_path, monkeypatch,
             fixchecks.assert_the_writer_never_overwrites_and_leaves_no_partial_output,
             lambda m: m.setattr(writer, "refuse_existing", lambda target: None),
             "not refused as FixTargetExists|was accepted")  # fmt: skip


def test_a_writer_that_keeps_partial_output_fails_the_writer_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mutant: a failed write's temp directory is not removed."""
    _ok_then(tmp_path, monkeypatch,
             fixchecks.assert_the_writer_never_overwrites_and_leaves_no_partial_output,
             lambda m: m.setattr(writer, "shutil", SimpleNamespace(rmtree=lambda *a, **k: None)),
             "left partial output")  # fmt: skip


def test_a_fix_that_writes_into_a_config_fails_the_safety_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mutant: writing the bundle also appends to the first config file it patches."""
    real = writer.write_bundle

    def touching(bundle: Any, out_dir: Path) -> Path:
        for e in bundle.edits:
            if e.file:
                with Path(e.file).open("ab") as fh:
                    fh.write(b" ")
                break
        return real(bundle, out_dir)

    _ok_then(tmp_path, monkeypatch, fixchecks.assert_fix_never_touches_a_config,
             lambda m: m.setattr(writer, "write_bundle", touching),
             "fix changed a client config")  # fmt: skip


def test_an_m3_patch_without_the_syntax_header_fails_the_rule_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mutant (Haris's ruling, 2026-11-26): the M3 patch is plain JSON with no FOR-REVIEW
    header, so a wrong rule syntax would apply cleanly and silently protect nothing."""
    import json

    def bare(rule: str) -> bytes:
        return (json.dumps({"permissions": {"ask": [rule]}}) + "\n\n{}\n").encode()

    _ok_then(tmp_path, monkeypatch, fixchecks.assert_m3_rule_form_is_the_cited_one,
             lambda m: m.setattr(render, "m3_patch_text", bare),
             "does not start with the syntax-verification header")  # fmt: skip
