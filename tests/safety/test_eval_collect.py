"""`python -m proveflow.eval.collect` with the FAKE MCP server only (never real servers)."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

from fakehome import FAKE_SERVER, logged_methods
from proveflow.discover.readers import read_explicit
from proveflow.eval import collect as col
from proveflow.flows.pinning import check_pinning

REPO = Path(__file__).resolve().parents[2]


def _server(sid: str, mode: str, tmp: Path, **extra: object) -> dict[str, object]:
    return {
        "id": sid,
        "source": "fake",
        "license": "MIT (test fixture)",
        "command": sys.executable,
        "args": [str(FAKE_SERVER), "--mode", mode, "--log", str(tmp / f"{sid}.log"),
                 "--pids", str(tmp / f"{sid}.pids"), "--desc-file", str(tmp / f"{sid}.desc")],
        **extra,
    }  # fmt: skip


def _spec(tmp: Path, servers: list[dict[str, object]]) -> Path:
    p = tmp / "eval_servers.json"
    p.write_text(json.dumps({"schema_version": 1, "servers": servers}), encoding="utf-8")
    return p


def test_collect_writes_jsonl_with_provenance_and_summary(tmp_path: Path) -> None:
    spec = _spec(tmp_path, [_server("b-legacy", "legacy", tmp_path),
                            _server("a-modern", "modern", tmp_path),
                            _server("c-sleep", "sleep", tmp_path)])  # fmt: skip
    out = tmp_path / "out" / "tools.jsonl"
    rc = col.main(["--servers", str(spec), "--out", str(out), "--yes", "--timeout", "8"])
    assert rc == 0
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert [(r["server_id"], r["tool_name"]) for r in rows] == [
        ("a-modern", "read_inbox"), ("a-modern", "send_email"),
        ("b-legacy", "read_inbox"), ("b-legacy", "send_email"),
    ]  # fmt: skip
    for r in rows:
        assert r["schema_version"] == 1
        assert r["tool_sha256"] == col.tool_sha256(
            r["tool_name"], r["description"], r["input_schema"]
        )
        prov = r["provenance"]
        assert prov["collected_by"] == "tools/list via proveflow.eval.collect"
        assert prov["license"] == "MIT (test fixture)"
        assert prov["source"] == "fake"
        assert prov["era"] in ("modern", "handshake")
    eras = {r["server_id"]: r["provenance"]["era"] for r in rows}
    assert eras == {"a-modern": "modern", "b-legacy": "handshake"}
    summary = json.loads((out.parent / "tools.jsonl.summary.json").read_text(encoding="utf-8"))
    status = {s["server_id"]: s["status"] for s in summary["servers"]}
    assert status == {"a-modern": "ok", "b-legacy": "ok", "c-sleep": "timeout"}
    assert summary["tools_total"] == 4
    for sid in ("a-modern", "b-legacy"):
        assert "tools/call" not in (logged_methods(tmp_path, sid) or [])


def test_jsonl_is_byte_reproducible(tmp_path: Path) -> None:
    spec = _spec(tmp_path, [_server("x", "legacy", tmp_path)])
    a, b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    assert col.main(["--servers", str(spec), "--out", str(a), "--yes"]) == 0
    assert col.main(["--servers", str(spec), "--out", str(b), "--yes"]) == 0
    assert a.read_bytes() == b.read_bytes()


@pytest.mark.parametrize("flag", [True, False])
def test_ignore_scripts_reaches_child_env(tmp_path: Path, flag: bool) -> None:
    spec = _spec(tmp_path, [_server("echo", "envecho", tmp_path, env={"FAKE_SECRET": "x"})])
    out = tmp_path / "t.jsonl"
    args = ["--servers", str(spec), "--out", str(out), "--yes"]
    assert col.main([*args, "--ignore-scripts"] if flag else args) == 0
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    read = next(r for r in rows if r["tool_name"] == "read_inbox")
    # Windows env names are case-insensitive and the child sees them upper-cased.
    keys = {k.lower() for k in read["description"].removeprefix("vars|").split(",")}
    assert ("npm_config_ignore_scripts" in keys) is flag


def test_refuses_without_yes(tmp_path: Path) -> None:
    spec = _spec(tmp_path, [_server("x", "legacy", tmp_path)])
    rc = col.main(["--servers", str(spec), "--out", str(tmp_path / "o.jsonl")])
    assert rc == 2
    assert logged_methods(tmp_path, "x") is None  # never started
    assert not (tmp_path / "o.jsonl").exists()


def test_only_filter_and_unknown_id(tmp_path: Path) -> None:
    spec = _spec(tmp_path, [_server("x", "legacy", tmp_path), _server("y", "legacy", tmp_path)])
    out = tmp_path / "o.jsonl"
    assert col.main(["--servers", str(spec), "--out", str(out), "--yes", "--only", "y"]) == 0
    assert logged_methods(tmp_path, "x") is None
    assert col.main(["--servers", str(spec), "--out", str(out), "--yes", "--only", "nope"]) == 1


def test_materialize_replaces_workdir_and_runs_setup(tmp_path: Path) -> None:
    srv = col.EvalServer(
        id="s", source="fake", license="x", command="npx",
        args=("-y", "pkg@1.0.0", "{workdir}/fs"), env={"F": "{workdir}/m/f.jsonl"},
        setup=("mkdir:fs", "mkdir:m"),
    )  # fmt: skip
    concrete = col.materialize([srv], tmp_path, ignore_scripts=True)
    entry = concrete["s"]
    assert entry["args"][-1] == f"{tmp_path}/fs"
    assert entry["env"]["F"] == f"{tmp_path}/m/f.jsonl"
    assert entry["env"]["npm_config_ignore_scripts"] == "true"
    assert (tmp_path / "fs").is_dir() and (tmp_path / "m").is_dir()
    assert "{workdir}" not in json.dumps(concrete)


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_git_init_setup(tmp_path: Path) -> None:
    srv = col.EvalServer(
        id="g",
        source="fake",
        license="x",
        command="uvx",
        args=("--repository", "{workdir}/repo"),
        setup=("git-init:repo",),
    )
    col.materialize([srv], tmp_path, ignore_scripts=False)
    assert (tmp_path / "repo" / ".git").is_dir()


@pytest.mark.parametrize("step", ["mkdir:../escape", "mkdir:", "rm:x"])
def test_bad_setup_steps_rejected(tmp_path: Path, step: str) -> None:
    srv = col.EvalServer(id="s", source="fake", license="x", command="npx", setup=(step,))
    with pytest.raises(col.CollectError):
        col.materialize([srv], tmp_path / "w", ignore_scripts=False)


def test_duplicate_ids_rejected(tmp_path: Path) -> None:
    spec = _spec(tmp_path, [_server("x", "legacy", tmp_path), _server("x", "legacy", tmp_path)])
    with pytest.raises(col.CollectError, match="duplicate"):
        col.load_server_set(spec)


def test_committed_eval_server_set_is_valid_and_exactly_pinned(tmp_path: Path) -> None:
    """data/eval/roles/servers.json: valid, 14 servers, every launch is an exact pin, no
    ${...} variables, every server has a license, and pg-mcp-guard is not in it."""
    server_set = col.load_server_set(REPO / "data" / "eval" / "roles" / "servers.json")
    assert len(server_set.servers) == 14
    assert "pg-mcp-guard" not in {s.id for s in server_set.servers}
    concrete = col.materialize(server_set.servers, tmp_path, ignore_scripts=True)
    cfg = tmp_path / "s.json"
    cfg.write_text(json.dumps({"mcpServers": concrete}), encoding="utf-8")
    [parsed] = read_explicit(cfg)
    assert parsed.entry_errors == ()
    for spec in parsed.servers:
        assert spec.variables == (), spec.name
        check = check_pinning(spec)
        assert check is not None and check.status == "pinned", (spec.name, check)
    assert all(s.license for s in server_set.servers)


@pytest.mark.parametrize("flag", [True, False])
def test_no_build_reaches_child_env(tmp_path: Path, flag: bool) -> None:
    """UV_NO_BUILD must be in the SERVER's env: a job-level variable never reaches it,
    because servers get only the minimal allow-list plus their own env."""
    spec = _spec(tmp_path, [_server("echo", "envecho", tmp_path, env={"FAKE_SECRET": "x"})])
    out = tmp_path / "t.jsonl"
    args = ["--servers", str(spec), "--out", str(out), "--yes"]
    assert col.main([*args, "--no-build"] if flag else args) == 0
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    read = next(r for r in rows if r["tool_name"] == "read_inbox")
    keys = {k.lower() for k in read["description"].removeprefix("vars|").split(",")}
    assert ("uv_no_build" in keys) is flag
    summary = json.loads((tmp_path / "t.jsonl.summary.json").read_text(encoding="utf-8"))
    assert summary["no_build"] is flag


def test_job_level_env_does_not_reach_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pins the bug the flag fixes: UV_NO_BUILD set only on the parent is NOT inherited."""
    monkeypatch.setenv("UV_NO_BUILD", "1")
    spec = _spec(tmp_path, [_server("echo", "envecho", tmp_path, env={"FAKE_SECRET": "x"})])
    out = tmp_path / "t.jsonl"
    assert col.main(["--servers", str(spec), "--out", str(out), "--yes"]) == 0
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    read = next(r for r in rows if r["tool_name"] == "read_inbox")
    keys = {k.lower() for k in read["description"].removeprefix("vars|").split(",")}
    assert "uv_no_build" not in keys


def test_category_is_recorded_in_provenance(tmp_path: Path) -> None:
    spec = _spec(tmp_path, [_server("cat", "legacy", tmp_path, category="messaging")])
    out = tmp_path / "o.jsonl"
    assert col.main(["--servers", str(spec), "--out", str(out), "--yes"]) == 0
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert rows and {r["provenance"]["category"] for r in rows} == {"messaging"}


def test_heldout_v2_server_set_is_valid_pinned_disjoint_and_credential_free(
    tmp_path: Path,
) -> None:
    """data/eval/roles/servers_v2.json (checkpoint 1c Stage C): valid, exact pins, a category
    per server, no package shared with the v1 set, at most 2 browser servers, and no env var
    whose NAME suggests a credential (only store paths / ids are allowed)."""
    v2 = col.load_server_set(REPO / "data" / "eval" / "roles" / "servers_v2.json")
    v1 = col.load_server_set(REPO / "data" / "eval" / "roles" / "servers.json")
    assert len(v2.servers) == 14
    assert all(s.category for s in v2.servers)
    assert sum(s.category == "browser" for s in v2.servers) <= 2
    v1_pkgs = {s.package.name for s in v1.servers if s.package}
    assert not v1_pkgs & {s.package.name for s in v2.servers if s.package}
    credential = ("KEY", "TOKEN", "SECRET", "PASSWORD", "PASS", "USER", "AUTH", "CREDENTIAL")
    for s in v2.servers:
        assert not [k for k in s.env if any(c in k.upper() for c in credential)], s.id
    concrete = col.materialize(v2.servers, tmp_path, ignore_scripts=True)
    cfg = tmp_path / "s.json"
    cfg.write_text(json.dumps({"mcpServers": concrete}), encoding="utf-8")
    [parsed] = read_explicit(cfg)
    assert parsed.entry_errors == ()
    for spec in parsed.servers:
        assert spec.variables == (), spec.name
        check = check_pinning(spec)
        assert check is not None and check.status == "pinned", (spec.name, check)
    assert all(s.license for s in v2.servers)
