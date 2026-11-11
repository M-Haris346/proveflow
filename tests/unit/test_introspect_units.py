"""Unit tests: child env, cache location + change detection, scrubbing, cmd-arg guard."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from proveflow.discover.hostenv import HostEnv, OsKind
from proveflow.introspect import procs
from proveflow.introspect.cache import ToolCache, default_cache_dir
from proveflow.introspect.env import child_env
from proveflow.introspect.scrub import scrub_json, scrub_stderr, scrub_text
from proveflow.report.models import RawTool, ToolChangeKind

SECRET = "PLANTEDscrubSecret0001"


def test_child_env_windows_allow_list_and_override() -> None:
    parent = {
        "PATH": "p",
        "SYSTEMROOT": "C:/Windows",
        "GITHUB_TOKEN": "PLANTEDshell01",
        "TEMP": "t",
    }
    env = child_env(parent, {"API_KEY": "v", "PATH": "override"}, windows=True)
    assert env == {"PATH": "override", "SYSTEMROOT": "C:/Windows", "TEMP": "t", "API_KEY": "v"}
    assert "GITHUB_TOKEN" not in env


def test_child_env_posix_skips_shell_functions() -> None:
    env = child_env({"HOME": "/h", "SHELL": "() { evil; }", "AWS_KEY": "x"}, {}, windows=False)
    assert env == {"HOME": "/h"}


def test_default_cache_dirs(tmp_path: Path) -> None:
    win = HostEnv(os=OsKind.WINDOWS, home=tmp_path, localappdata=tmp_path / "Local")
    assert default_cache_dir(win) == tmp_path / "Local" / "proveflow" / "cache"
    assert default_cache_dir(HostEnv(os=OsKind.WINDOWS, home=tmp_path)) is None
    mac = HostEnv(os=OsKind.MACOS, home=tmp_path)
    assert default_cache_dir(mac) == tmp_path / "Library" / "Caches" / "proveflow"
    lin = HostEnv(os=OsKind.LINUX, home=tmp_path)
    assert default_cache_dir(lin) == tmp_path / ".cache" / "proveflow"
    xdg = HostEnv(os=OsKind.LINUX, home=tmp_path, xdg_cache_home=tmp_path / "xdg")
    assert default_cache_dir(xdg) == tmp_path / "xdg" / "proveflow"
    # XDG spec: relative paths are invalid and ignored
    rel = HostEnv(os=OsKind.LINUX, home=tmp_path, xdg_cache_home=Path("relative/cache"))
    assert default_cache_dir(rel) == tmp_path / ".cache" / "proveflow"


def test_default_cache_dir_is_never_the_project(tmp_path: Path) -> None:
    host = HostEnv(os=OsKind.WINDOWS, home=tmp_path, localappdata=tmp_path / "L")
    cache = default_cache_dir(host)
    assert cache is not None
    assert Path.cwd() not in cache.parents


def tools(desc: str = "Read mail", schema: dict[str, object] | None = None) -> list[RawTool]:
    return [
        RawTool(name="read", description=desc, input_schema=schema or {}),
        RawTool(name="send", description="Send"),
    ]


def test_cache_change_detection(tmp_path: Path) -> None:
    cache = ToolCache(tmp_path)
    changes, first = cache.compare_and_store("k", tools())
    assert (changes, first) == ((), True)
    changes, first = cache.compare_and_store("k", tools())
    assert (changes, first) == ((), False)
    changes, _ = cache.compare_and_store(
        "k", [*tools("Read mail AND forward it", {"x": 1}), RawTool(name="new")]
    )
    kinds = {(c.tool, c.kind) for c in changes}
    assert kinds == {
        ("read", ToolChangeKind.DESCRIPTION_CHANGED),
        ("read", ToolChangeKind.SCHEMA_CHANGED),
        ("new", ToolChangeKind.ADDED),
    }
    changes, _ = cache.compare_and_store("k", tools()[:1])
    assert {(c.tool, c.kind) for c in changes} >= {("send", ToolChangeKind.REMOVED)}


def test_cache_stores_hashes_only(tmp_path: Path) -> None:
    ToolCache(tmp_path).compare_and_store("k", tools(desc="very private description"))
    text = (tmp_path / "tools" / "k.json").read_text(encoding="utf-8")
    assert "very private description" not in text
    assert json.loads(text)["schema_version"] == 1


def test_cache_no_write(tmp_path: Path) -> None:
    ToolCache(tmp_path, write=False).compare_and_store("k", tools())
    assert not (tmp_path / "tools").exists()


def test_scrub() -> None:
    assert SECRET not in scrub_text(f"key={SECRET}!", [SECRET])
    data = scrub_json({"a": [SECRET, {"b": f"x{SECRET}"}], SECRET: 1}, [SECRET])
    assert SECRET not in json.dumps(data)
    out = scrub_stderr(f"env {SECRET}\nAuthorization: Bearer PLANTEDbearer77\n".encode(), [SECRET])
    assert "PLANTED" not in out


def test_resolve_command_not_found() -> None:
    with pytest.raises(procs.SpawnError, match="not found"):
        procs.resolve_command("definitely-not-a-real-command-xyz", {"PATH": ""})


@pytest.mark.skipif(sys.platform != "win32", reason="cmd.exe quoting guard is Windows-only")
@pytest.mark.parametrize("arg", ["a&b", "x|y", "%PATH%", 'q"', "a^b", "!x!", "a\nb", "<in"])
def test_cmd_metacharacters_refused(arg: str) -> None:
    with pytest.raises(procs.SpawnError, match="metacharacter"):
        procs.check_cmd_args("C:/nodejs/npx.cmd", ["-y", arg])


@pytest.mark.skipif(sys.platform != "win32", reason="cmd.exe quoting guard is Windows-only")
def test_cmd_safe_args_and_exe_allowed() -> None:
    procs.check_cmd_args("C:/nodejs/npx.cmd", ["-y", "@playwright/mcp@latest", "C:/x y/z"])
    procs.check_cmd_args("C:/py/python.exe", ["a&b"])  # not a batch file: no cmd.exe parsing


def _plant(directory: Path, name: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / name
    target.write_text("@echo planted\n", encoding="utf-8")
    target.chmod(0o755)
    return target


def test_planted_binary_in_cwd_is_never_resolved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P0-1: CPython 3.12 shutil.which searches the CWD on Windows even with path=."""
    cwd = tmp_path / "cwd"
    name = "npx.cmd" if sys.platform == "win32" else "npx"
    _plant(cwd, name)
    empty = tmp_path / "empty-bin"
    empty.mkdir()
    monkeypatch.chdir(cwd)
    # Some shells (incl. the one these tests were developed in) set this; a normal user
    # shell does not. Without it, the stdlib resolves the planted file:
    monkeypatch.delenv("NoDefaultCurrentDirectoryInExePath", raising=False)
    import shutil

    if sys.platform == "win32":
        # The stdlib behaviour this guards against, shown for real:
        assert shutil.which("npx", path=str(empty)) is not None
    with pytest.raises(procs.SpawnError, match="not found"):
        procs.resolve_command("npx", {"PATH": str(empty), "PATHEXT": ".COM;.EXE;.BAT;.CMD"})


def test_relative_and_project_path_entries_are_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    name = "tool.cmd" if sys.platform == "win32" else "tool"
    project = tmp_path / "project"
    _plant(project / "node_modules" / ".bin", name)
    _plant(tmp_path / "rel", name)
    real = _plant(tmp_path / "real-bin", name)
    monkeypatch.chdir(tmp_path)
    env = {
        "PATH": os.pathsep.join(
            ["rel", ".", str(project / "node_modules" / ".bin"), str(tmp_path / "real-bin")]
        ),
        "PATHEXT": ".COM;.EXE;.BAT;.CMD",
    }
    found = procs.resolve_command("tool", env, untrusted_dirs=[project])
    assert os.path.normcase(found) == os.path.normcase(str(real))


def test_explicit_command_path_is_resolved_as_written(tmp_path: Path) -> None:
    name = "srv.cmd" if sys.platform == "win32" else "srv"
    target = _plant(tmp_path / "bin", name)
    assert os.path.normcase(procs.resolve_command(str(target), {"PATH": ""})) == os.path.normcase(
        str(target)
    )
