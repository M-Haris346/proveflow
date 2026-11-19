"""``proveflow twin`` (Phase 4 step 11, D10, R-C6/R-C7).

Synthetic input only: a scan report built in the test from the fake-home fixture configs,
with introspection results made from STORED tool metadata (data/eval); no server is
launched, no network. Output paths live in the test's TWIN_ROOT (``proxy_twin_root``).
"""

from __future__ import annotations

import hashlib
import json
import socket
from pathlib import Path
from typing import Any

import pytest

from proveflow.config import TwinOverride
from proveflow.proxy import policy as policy_module
from proveflow.proxy.session import load_session
from proveflow.twin.plan import plan_twins
from proxyhelpers import proxy_twin_root, run_in_process  # noqa: F401
from twincli import (
    PROFILE,
    assert_existing_target_refuses_whole_run,
    assert_no_launch_scan_refused,
    assert_out_dir_outside_twin_root_refused,
    files,
    invoke,
    make_scan,
    out_dir,
)


def test_writes_one_twin_and_one_session_per_server(tmp_path: Path) -> None:
    scan, _ = make_scan(tmp_path)
    result = invoke("--from", str(scan), "--profile", PROFILE, "--out-dir", str(out_dir()))
    assert result.exit_code == 0, result.output
    assert result.stdout == ""  # stderr only
    names = set(files(out_dir()))
    for slug in ("brave-search", "filesystem", "gmail"):
        assert {f"pftwin-{slug}.py", f"pftwin-{slug}.session.json"} <= names
    assert not any(n.endswith(".cassette.jsonl") for n in names)  # created by the proxy later
    assert "gmail: 3 tools, 3 honey, 0 pure sink, 0 dual-role" in result.stderr
    assert "gmail has no sink tool: it cannot be attacked for exfiltration" in result.stderr
    assert "brave-search: 1 tools, 0 honey, 0 pure sink, 1 dual-role" in result.stderr


def test_sessions_load_in_the_proxy_and_carry_honey_but_no_marker(tmp_path: Path) -> None:
    scan, _ = make_scan(tmp_path)
    assert (
        invoke("--from", str(scan), "--profile", PROFILE, "--out-dir", str(out_dir())).exit_code
        == 0
    )
    for slug in ("brave-search", "filesystem", "gmail"):
        path = out_dir() / f"pftwin-{slug}.session.json"
        session = load_session(path)  # the proxy's own loader: layer A + schema 3
        twin = Path(session.upstream.argv[1])
        assert hashlib.sha256(twin.read_bytes()).hexdigest() == session.twin_sha256
        text = path.read_text(encoding="utf-8")
        assert "pfmark_" not in text  # F4: markers never enter the session
        assert session.attack is None
        assert all(h.value in twin.read_text(encoding="utf-8") for h in session.honey)
    fs = load_session(out_dir() / "pftwin-filesystem.session.json")
    assert len(fs.honey) == 10


def test_a_generated_session_runs_under_the_real_proxy(tmp_path: Path) -> None:
    scan, _ = make_scan(tmp_path)
    assert (
        invoke("--from", str(scan), "--profile", PROFILE, "--out-dir", str(out_dir())).exit_code
        == 0
    )
    session = load_session(out_dir() / "pftwin-gmail.session.json")

    async def script(client: Any) -> Any:
        listed = await client.list_tools()
        rows = await client.call_tool("run_query", {"sql": "select 1"})
        return listed, rows

    (listed, rows), outcome = run_in_process(session, script)
    assert {t.name for t in listed.tools} == {"list_tables", "describe_table", "run_query"}
    assert rows.content[-1].text.startswith("twin-marker: pfmark_")
    assert outcome.forwarded_calls == 1


def test_refuses_a_no_launch_scan_and_writes_nothing(tmp_path: Path) -> None:
    assert_no_launch_scan_refused(tmp_path)


def test_refuses_an_out_dir_outside_twin_root(tmp_path: Path) -> None:
    assert_out_dir_outside_twin_root_refused(tmp_path)


def test_unknown_profile_lists_the_ids(tmp_path: Path) -> None:
    scan, _ = make_scan(tmp_path)
    result = invoke("--from", str(scan), "--profile", "nope", "--out-dir", str(out_dir()))
    assert result.exit_code == 1
    assert "no profile 'nope'" in result.stderr and PROFILE in result.stderr
    assert files(out_dir()) == {}


def test_refuses_to_overwrite_and_leaves_files_unchanged(tmp_path: Path) -> None:
    scan, _ = make_scan(tmp_path)
    args = ("--from", str(scan), "--profile", PROFILE, "--out-dir", str(out_dir()))
    assert invoke(*args).exit_code == 0
    before = files(out_dir())
    again = invoke(*args)
    assert again.exit_code == 1 and "refusing to overwrite" in again.stderr
    assert files(out_dir()) == before


@pytest.mark.parametrize("existing", ["pftwin-gmail.session.json", "pftwin-gmail.cassette.jsonl"])
def test_one_existing_target_refuses_the_whole_run(tmp_path: Path, existing: str) -> None:
    assert_existing_target_refuses_whole_run(tmp_path, existing)


def test_skipped_servers_are_reported(tmp_path: Path) -> None:
    scan, _ = make_scan(tmp_path)
    profile = next(p["id"] for p in json.loads(scan.read_text(encoding="utf-8"))["profiles"]
                   if p["id"].startswith("vscode@"))  # fmt: skip
    result = invoke("--from", str(scan), "--profile", profile, "--out-dir", str(out_dir()))
    assert result.exit_code == 0, result.output
    assert "skipped context7: not introspected (auth_required)" in result.stderr
    assert "pftwin-playwright.py" in files(out_dir())


def test_twin_override_applies_and_errors(tmp_path: Path) -> None:
    scan, report = make_scan(tmp_path)
    plan = plan_twins(
        report,
        PROFILE,
        out_dir(),
        seed="0",
        overrides=(
            TwinOverride(server="filesystem", tool="read_text_file", archetype="email_list"),
            TwinOverride(server="filesystem", tool="no_such_tool", archetype="db_rows"),
        ),
    )
    fs = next(t for t in plan.twins if t.server == "filesystem")
    assert fs.build.archetypes["read_text_file"][0] == "email_list"
    assert [(o.server, o.tool) for o in plan.unused_overrides] == [("filesystem", "no_such_tool")]
    cfg = tmp_path / "proveflow.toml"
    cfg.write_text(
        '[[twin_override]]\nserver = "gmail"\ntool = "run_query"\narchetype = "nonsense"\n',
        encoding="utf-8",
    )
    result = invoke("--from", str(scan), "--profile", PROFILE, "--out-dir", str(out_dir()),
                    "--config", str(cfg))  # fmt: skip
    assert result.exit_code == 1 and "unknown archetype 'nonsense'" in result.stderr
    assert files(out_dir()) == {}


def test_seed_determinism(tmp_path: Path) -> None:
    scan, _ = make_scan(tmp_path)
    a, b, c = (policy_module.TWIN_ROOT / n for n in ("a", "b", "c"))
    for d, seed in ((a, "7"), (b, "7"), (c, "8")):
        assert invoke("--from", str(scan), "--profile", PROFILE, "--out-dir", str(d),
                      "--seed", seed).exit_code == 0  # fmt: skip
    twin = "pftwin-filesystem.py"
    assert files(a)[twin] == files(b)[twin] != files(c)[twin]


def test_no_network_during_generation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    scan, _ = make_scan(tmp_path)

    class NoSocket:
        def __init__(self, *a: object, **k: object) -> None:
            raise AssertionError("proveflow twin opened a socket")

    monkeypatch.setattr(socket, "socket", NoSocket)
    result = invoke("--from", str(scan), "--profile", PROFILE, "--out-dir", str(out_dir()))
    assert result.exit_code == 0, result.output
