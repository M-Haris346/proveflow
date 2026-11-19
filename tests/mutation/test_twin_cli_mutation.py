"""Mutation (Phase 4 step 11): remove one refusal of ``proveflow twin`` -> its NAMED check
fails.

* the --no-launch refusal removed           -> assert_no_launch_scan_refused fails
* the TWIN_ROOT check on --out-dir removed  -> assert_out_dir_outside_twin_root_refused fails
* the all-targets pre-check removed         -> assert_existing_target_refuses_whole_run fails
"""

from __future__ import annotations

from pathlib import Path

import pytest

from proveflow.report.models import ScanReport
from proveflow.twin import plan
from proxyhelpers import proxy_twin_root  # noqa: F401
from twincli import (
    assert_existing_target_refuses_whole_run,
    assert_no_launch_scan_refused,
    assert_out_dir_outside_twin_root_refused,
)


def _dirs(tmp_path: Path) -> tuple[Path, Path]:
    ok, mut = tmp_path / "ok", tmp_path / "mut"
    ok.mkdir()
    mut.mkdir()
    return ok, mut


def test_accepting_a_no_launch_scan_fails_the_named_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ok, mut = _dirs(tmp_path)
    assert_no_launch_scan_refused(ok)

    def load_any(path: Path) -> ScanReport:
        return ScanReport.model_validate_json(path.read_bytes())

    monkeypatch.setattr(plan, "load_scan", load_any)
    # The CLI imports load_scan from the module at call time.
    with pytest.raises(AssertionError, match="--no-launch scan was not refused"):
        assert_no_launch_scan_refused(mut)


def test_dropping_the_twin_root_check_fails_the_named_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ok, mut = _dirs(tmp_path)
    assert_out_dir_outside_twin_root_refused(ok)
    monkeypatch.setattr(plan, "under_twin_root", lambda path: True)
    with pytest.raises(AssertionError, match="outside TWIN_ROOT was accepted"):
        assert_out_dir_outside_twin_root_refused(mut)


def test_dropping_the_all_targets_precheck_fails_the_named_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import proveflow.proxy.policy as policy_module

    existing = "pftwin-gmail.session.json"
    root = policy_module.TWIN_ROOT
    monkeypatch.setattr(policy_module, "TWIN_ROOT", root / "ok")
    assert_existing_target_refuses_whole_run(tmp_path / "ok", existing)
    monkeypatch.setattr(policy_module, "TWIN_ROOT", root / "mut")
    real_exists = Path.exists

    def precheck_blind(self: Path) -> bool:
        # Mutant: the pre-check sees no existing target; the later "xb" open still refuses
        # the session file, so twins are written first: partial output.
        if self.name.startswith("pftwin-") and self.parent.name == "run1":
            return False
        return real_exists(self)

    monkeypatch.setattr(plan.Path, "exists", precheck_blind)
    with pytest.raises(AssertionError, match="did not refuse the whole run"):
        assert_existing_target_refuses_whole_run(tmp_path / "mut", existing)
