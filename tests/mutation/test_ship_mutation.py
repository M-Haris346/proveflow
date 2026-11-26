"""Mutations of Phase 9's new behaviour: one weakening per rule, each killed by its named check
(tests/shipchecks.py, tests/safety/test_control_never_imported.py). Each test runs the check
unmutated first, then under the mutant."""

from __future__ import annotations

import shutil
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

import shipchecks
from proveflow import gate


def _ok_then(tmp_path: Path, mp: pytest.MonkeyPatch, check: Callable[[Path], None],
             patch: Callable[[pytest.MonkeyPatch], None], message: str) -> None:  # fmt: skip
    check(tmp_path / "ok")
    with mp.context() as m:
        patch(m)
        with pytest.raises(AssertionError, match=message):
            check(tmp_path / "mut")


def test_a_gate_that_ignores_its_class_fails_the_gate_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mutant: src/proveflow/gate.py line 48, `matched` returns no flow, so --fail-on matches
    nothing and the toxic fixture passes the gate."""
    _ok_then(tmp_path, monkeypatch,
             lambda p: shipchecks.assert_fail_on_exits_3_only_for_matched_flows(p, monkeypatch),
             lambda m: m.setattr(gate, "matched", lambda flows, fail_on: []),
             r"toxic --fail-on exfil: exit 0, want 3")  # fmt: skip


def test_an_error_turned_into_a_pass_fails_the_error_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mutant (Ruling B): src/proveflow/gate.py line 36, `if c.status in UNREAD:` never fires
    (`unread_configs` returns []), so the fail-closed check sees no unread config: a malformed
    servers file with the toxic flows elsewhere is a pass (0) or a finding (3), never the error
    (1)."""
    _ok_then(tmp_path, monkeypatch,
             lambda p: shipchecks.assert_an_error_is_never_a_finding(
                 p, monkeypatch, "servers_parse_error"),
             lambda m: m.setattr(gate, "unread_configs", lambda configs: []),
             r"servers_parse_error: exit [03], want 1")  # fmt: skip


def test_a_second_importer_of_the_control_fails_the_guard() -> None:
    """Planted violation: another src module imports the control. Killed by tests/shipchecks.py
    line 240, `stray = [...]`, which must name it."""
    good = {"src/proveflow/runner/verify.py": "from proveflow.runner.control import X"}
    shipchecks.assert_only_verify_imports_the_control(good)
    bad = {**good, "src/proveflow/cli.py": "from proveflow.runner import control"}
    with pytest.raises(AssertionError, match=r"imported outside runner\.verify"):
        shipchecks.assert_only_verify_imports_the_control(bad)


def test_a_tag_check_that_compares_nothing_fails_the_tag_check(tmp_path: Path) -> None:
    """Mutant: scripts/check_tag_version.py line 27, `if tag != want:` becomes `if False:`, so
    every tag passes."""
    shipchecks.assert_a_tag_must_equal_the_package_version(tmp_path / "ok")
    text = shipchecks.TAG_SCRIPT.read_text(encoding="utf-8")
    mutant = tmp_path / "check_tag_version.py"
    mutant.write_text(text.replace("    if tag != want:", "    if False:"), encoding="utf-8")
    assert mutant.read_text(encoding="utf-8") != text  # premise: the mutation applied
    (tmp_path / "mut").mkdir()
    with pytest.raises(AssertionError, match=r"tag 'v0.1.0': exit 0, want 1"):
        shipchecks.assert_a_tag_must_equal_the_package_version(tmp_path / "mut", mutant)


def test_an_unpinned_action_reference_fails_the_pin_check() -> None:
    """Planted violation: the Action's setup-uv reference moves from a commit SHA to a tag.
    Killed by tests/shipchecks.py line 266, the `PINNED.match` test."""
    files = {p.relative_to(shipchecks.REPO).as_posix(): p.read_text(encoding="utf-8")
             for p in shipchecks.action_files()}  # fmt: skip
    shipchecks.assert_the_action_is_pinned_static_and_gating(files)
    action = files["action/action.yml"]
    mutated = {**files, "action/action.yml": "\n".join(
        (line.split("@")[0] + "@v10") if shipchecks.USES.match(line) else line
        for line in action.splitlines()
    )}  # fmt: skip
    with pytest.raises(AssertionError, match="not pinned by commit SHA"):
        shipchecks.assert_the_action_is_pinned_static_and_gating(mutated)


def _installer_mutant(tmp_path: Path, original: Path, old: str, new: str) -> Path:
    text = original.read_text(encoding="utf-8")
    assert text.count(old) == 1, f"premise: the mutated line is not exactly once in {original.name}"
    mutant = tmp_path / original.name
    mutant.write_bytes(text.replace(old, new).encode("utf-8"))
    return mutant


@pytest.mark.skipif(shutil.which("sh") is None, reason="no sh on this machine")
def test_install_sh_without_its_version_check_fails_the_installer_check(tmp_path: Path) -> None:
    """Mutant: install/install.sh line 66, the version mismatch becomes a plain message
    (`*) fail "installed version ..."` -> `*) say ...`), so a wrong version installs green."""
    shipchecks.assert_the_installer_installs_exactly_its_route(tmp_path / "ok", "sh")
    mutant = _installer_mutant(tmp_path, shipchecks.INSTALL_SH, '  *) fail "installed version',
                               '  *) say "installed version')  # fmt: skip
    with pytest.raises(AssertionError, match="sh wrong version: exit 0"):
        shipchecks.assert_the_installer_installs_exactly_its_route(tmp_path / "mut", "sh", mutant)


@pytest.mark.skipif(sys.platform != "win32", reason="install.ps1 is the Windows installer")
def test_install_ps1_without_its_version_check_fails_the_installer_check(tmp_path: Path) -> None:
    """Mutant: install/install.ps1 line 64, the version mismatch becomes a plain message
    (`Fail "installed version ..."` -> `Say ...`), so a wrong version installs green."""
    shipchecks.assert_the_installer_installs_exactly_its_route(tmp_path / "ok", "ps1")
    mutant = _installer_mutant(tmp_path, shipchecks.INSTALL_PS1, '    Fail "installed version',
                               '    Say "installed version')  # fmt: skip
    with pytest.raises(AssertionError, match="ps1 wrong version: exit 0"):
        shipchecks.assert_the_installer_installs_exactly_its_route(tmp_path / "mut", "ps1", mutant)


def test_a_scan_silent_about_unread_configs_fails_the_warning_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mutant: src/proveflow/cli.py line 347, `_warn_unread(unread)` does nothing, so a scan
    without --fail-on stays silent about the configs it could not read."""
    import proveflow.cli as cli

    _ok_then(tmp_path, monkeypatch,
             lambda p: shipchecks.assert_scan_names_an_unread_config_without_fail_on(
                 p, monkeypatch),
             lambda m: m.setattr(cli, "_warn_unread", lambda unread: None),
             "did not name both unread configs")  # fmt: skip
