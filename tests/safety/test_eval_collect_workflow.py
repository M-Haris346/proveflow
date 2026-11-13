"""eval-collect must not silently collect the wrong server file (run #2, 2026-11-13, 016e39d,
was dispatched with default inputs and collected the v1 set instead of servers_v2.json).

- verify_collection: the id check the workflow runs after collection fails on a mismatch.
- The workflow file: the check step runs that exact module on the resolved inputs, and the
  first step's bash (extracted from the YAML and executed) prints the inputs and derives the
  artifact name from out_dir.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from proveflow.eval import verify_collection as vc

REPO = Path(__file__).resolve().parents[2]
WORKFLOW = REPO / ".github" / "workflows" / "eval-collect.yml"
V1 = REPO / "data" / "eval" / "roles" / "servers.json"
V2 = REPO / "data" / "eval" / "roles" / "servers_v2.json"


def _summary(tmp: Path, ids: list[str]) -> Path:
    p = tmp / "tools.jsonl.summary.json"
    p.write_text(json.dumps({"servers": [{"server_id": i, "status": "ok"} for i in ids]}), "utf-8")
    return p


def _ids(path: Path) -> list[str]:
    return [s["id"] for s in json.loads(path.read_text(encoding="utf-8"))["servers"]]


def test_id_check_fails_on_the_run2_mismatch(tmp_path: Path) -> None:
    """The exact incident: a v1 collection summary checked against servers_v2.json."""
    summary = _summary(tmp_path, _ids(V1))
    assert vc.main(["--servers", str(V2), "--summary", str(summary)]) == 1
    problems = vc.check(V2, summary)
    assert any("not collected" in p for p in problems)
    assert any("collected but not in" in p for p in problems)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda ids: ids[:-1],  # one server missing (even a failed one must be in the summary)
        lambda ids: [*ids, "extra-server"],  # one unexpected server
        lambda ids: [*ids, ids[0]],  # duplicate id
    ],
    ids=["missing", "unexpected", "duplicate"],
)
def test_id_check_fails_on_any_mismatch(tmp_path: Path, mutate) -> None:  # type: ignore[no-untyped-def]
    summary = _summary(tmp_path, mutate(_ids(V2)))
    assert vc.main(["--servers", str(V2), "--summary", str(summary)]) == 1


def test_id_check_passes_on_exact_match(tmp_path: Path) -> None:
    summary = _summary(tmp_path, list(reversed(_ids(V2))))  # order does not matter
    assert vc.main(["--servers", str(V2), "--summary", str(summary)]) == 0


def test_id_check_fails_on_unreadable_summary(tmp_path: Path) -> None:
    bad = tmp_path / "s.json"
    bad.write_text("{not json", encoding="utf-8")
    assert vc.main(["--servers", str(V2), "--summary", str(bad)]) == 1
    assert vc.main(["--servers", str(V2), "--summary", str(tmp_path / "missing.json")]) == 1


# --- the workflow file itself ---------------------------------------------------------


def _step(name: str) -> str:
    """Text of one step (from its '- name:' line to the next step at the same indent)."""
    text = WORKFLOW.read_text(encoding="utf-8")
    m = re.search(rf"^(\s*)- name: {re.escape(name)}\n", text, re.MULTILINE)
    assert m is not None, f"step {name!r} not found"
    indent = m.group(1)
    rest = text[m.end() :]
    nxt = re.search(rf"^{indent}- ", rest, re.MULTILINE)
    return m.group(0) + (rest[: nxt.start()] if nxt else rest)


def _run_block(step: str) -> str:
    m = re.search(r"^(\s*)run: \|\n", step, re.MULTILINE)
    assert m is not None
    base = len(m.group(1))
    lines = []
    for line in step[m.end() :].splitlines():
        if line.strip() and len(line) - len(line.lstrip()) <= base:
            break
        lines.append(line[base + 2 :])
    return "\n".join(lines) + "\n"


def test_workflow_runs_the_id_check_on_the_resolved_inputs() -> None:
    step = _step("Verify the summary covers exactly the chosen server file")
    assert "uv run python -m proveflow.eval.verify_collection" in step
    assert '--servers "$SERVERS"' in step
    assert '--summary "$OUT_DIR/tools.jsonl.summary.json"' in step
    assert "SERVERS: ${{ steps.resolve.outputs.servers }}" in step
    assert "OUT_DIR: ${{ steps.resolve.outputs.out_dir }}" in step
    assert "continue-on-error" not in step and "if:" not in step  # a mismatch fails the job
    text = WORKFLOW.read_text(encoding="utf-8")
    # the check runs after collection and before the upload
    collect = text.index("- name: Collect tools/list")
    verify = text.index("- name: Verify the summary covers exactly")
    upload = text.index("- name: Upload collected tool metadata")
    assert collect < verify < upload
    upload_step = _step("Upload collected tool metadata")
    assert "name: ${{ steps.resolve.outputs.artifact }}" in upload_step
    assert "inputs.out_dir" not in upload_step and "'-v2'" not in upload_step


def _probe(bash: Path) -> bool:
    """True only for a working POSIX bash (the WSL launcher stub prints a UTF-16 notice and
    exits 1 when no distribution is installed: CI run 43436655254, windows-2025)."""
    try:
        res = subprocess.run(
            [str(bash), "-c", "printf ok"], capture_output=True, text=True, timeout=30
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return res.returncode == 0 and res.stdout == "ok"


def _real_bash() -> str | None:
    """A bash that actually runs scripts. On Windows a bare `bash` on PATH is often the WSL
    launcher (System32 / WindowsApps), so Git for Windows' own bash next to `git` is tried
    first (git.exe lives in <root>/cmd, bash.exe in <root>/bin). Every candidate must pass
    the probe; None -> see require_bash()."""
    candidates: list[Path] = []
    git = shutil.which("git")
    if git:
        root = Path(git).resolve().parent.parent
        candidates += [root / "bin" / "bash.exe", root / "usr" / "bin" / "bash.exe"]
    on_path = shutil.which("bash")
    if on_path:
        candidates.append(Path(on_path))
    return next((str(c) for c in candidates if c.is_file() and _probe(c)), None)


BASH = _real_bash()
NO_BASH = "no working bash found (only a WSL stub or none)"


def require_bash(found: str | None) -> str:
    """Use the bash if there is one. Without one: on CI (env CI set, as GitHub Actions does)
    the test FAILS, so the resolve-step tests can never silently vanish from CI; locally it
    is a visible skip (-rs)."""
    if found is not None:
        return found
    if os.environ.get("CI"):
        pytest.fail(f"{NO_BASH} on CI: the eval-collect resolve-step tests must run here")
    pytest.skip(NO_BASH)


@pytest.fixture
def bash() -> str:
    return require_bash(BASH)


def test_missing_bash_fails_on_ci(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CI", "true")
    with pytest.raises(pytest.fail.Exception, match="on CI"):
        require_bash(None)


def test_missing_bash_skips_locally(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CI", raising=False)
    with pytest.raises(pytest.skip.Exception, match="no working bash"):
        require_bash(None)


def test_found_bash_is_used_regardless_of_ci(monkeypatch: pytest.MonkeyPatch) -> None:
    for ci in ("true", None):
        if ci is None:
            monkeypatch.delenv("CI", raising=False)
        else:
            monkeypatch.setenv("CI", ci)
        assert require_bash("/some/bash") == "/some/bash"


@pytest.mark.parametrize(
    ("servers", "out_dir", "artifact"),
    [
        ("data/eval/roles/servers.json", "out", "eval-tools"),
        ("data/eval/roles/servers_v2.json", "out/v2", "eval-tools-v2"),
        ("data/eval/roles/servers_v2.json", "out/heldout", "eval-tools-heldout"),
    ],
)
def test_resolve_step_prints_inputs_and_derives_artifact_from_out_dir(
    tmp_path: Path, bash: str, servers: str, out_dir: str, artifact: str
) -> None:
    script = tmp_path / "resolve.sh"
    script.write_text(_run_block(_step("Resolve and print inputs")), encoding="utf-8", newline="\n")
    out, summary = tmp_path / "gh_output", tmp_path / "gh_summary"
    env = {**os.environ, "SERVERS": servers, "OUT_DIR": out_dir,
           "GITHUB_OUTPUT": str(out), "GITHUB_STEP_SUMMARY": str(summary)}  # fmt: skip
    res = subprocess.run([bash, "-e", str(script)], env=env, capture_output=True, text=True)
    assert res.returncode == 0, res.stdout + res.stderr
    assert f"servers file : {servers}" in res.stdout
    assert f"out_dir      : {out_dir}" in res.stdout
    assert f"artifact     : {artifact}" in res.stdout
    outputs = dict(line.split("=", 1) for line in out.read_text(encoding="utf-8").splitlines())
    assert outputs == {"servers": servers, "out_dir": out_dir, "artifact": artifact}
    assert servers in summary.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("servers", "out_dir", "message"),
    [("../secrets.json", "out", "bad servers input"),
     ("data/eval/roles/servers_v2.json", "out/../x", "bad out_dir input"),
     ("data/eval/roles/x.json\n::set-output name=a::b", "out", "bad servers input")],
)  # fmt: skip
def test_resolve_step_rejects_bad_inputs_before_printing(
    tmp_path: Path, bash: str, servers: str, out_dir: str, message: str
) -> None:
    script = tmp_path / "resolve.sh"
    script.write_text(_run_block(_step("Resolve and print inputs")), encoding="utf-8", newline="\n")
    out = tmp_path / "gh_output"
    env = {**os.environ, "SERVERS": servers, "OUT_DIR": out_dir,
           "GITHUB_OUTPUT": str(out), "GITHUB_STEP_SUMMARY": str(tmp_path / "s")}  # fmt: skip
    res = subprocess.run([bash, "-e", str(script)], env=env, capture_output=True, text=True)
    assert res.returncode != 0
    # the script's OWN rejection message: proves the step ran (a broken bash also exits != 0)
    assert res.stdout.strip() == message, res.stdout + res.stderr
    assert "servers file :" not in res.stdout  # nothing printed before validation
    assert not out.exists()


def _inputs_block() -> str:
    text = WORKFLOW.read_text(encoding="utf-8")
    m = re.search(r"^    inputs:\n((?:      .*\n|\s*\n)+)", text, re.MULTILINE)
    assert m is not None, "workflow_dispatch inputs block not found"
    return m.group(1)


def test_dispatch_inputs_are_required_with_no_default() -> None:
    """An empty dispatch must not start (run #2 used the then-default v1 set)."""
    block = _inputs_block()
    inputs = re.findall(r"^      ([A-Za-z_]+):\n((?:        .*\n)+)", block, re.MULTILINE)
    assert {name for name, _ in inputs} == {"servers", "out_dir"}
    for name, body in inputs:
        assert re.search(r"^        required: true$", body, re.MULTILINE), name
    assert not re.search(r"^\s*default:", block, re.MULTILINE)
