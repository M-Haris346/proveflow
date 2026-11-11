"""LaunchSpec never exposes values; build_launch_spec refuses changed configs (T2/T12)."""

from __future__ import annotations

import copy
import io
import json
import logging
import pickle
import traceback
from pathlib import Path

import pytest

from fakehome import full_setup
from proveflow.core.client import ClientKind, ConfigScope
from proveflow.discover import run_discovery
from proveflow.discover.readers import read_explicit
from proveflow.introspect.launchspec import (
    ConfigChangedError,
    LaunchSpec,
    LaunchSpecError,
    build_launch_spec,
)

SECRET = "PLANTEDlaunchSecret0001"


def make() -> LaunchSpec:
    return LaunchSpec("srv", "npx", ["--token", SECRET], {"API_KEY": SECRET})


def test_repr_str_format_hide_values() -> None:
    spec = make()
    for text in (repr(spec), str(spec), f"{spec}", f"{spec!r}", f"{spec} {spec!r}"):
        assert SECRET not in text
        assert "API_KEY" in text
        assert "<values hidden>" in text


@pytest.mark.parametrize(
    "attempt",
    [
        lambda s: pickle.dumps(s),
        lambda s: copy.copy(s),
        lambda s: copy.deepcopy(s),
        lambda s: json.dumps(s),
        lambda s: vars(s),
    ],
    ids=["pickle", "copy", "deepcopy", "json", "vars"],
)
def test_cannot_be_serialized_or_copied(attempt) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(TypeError):
        attempt(make())


def test_logging_does_not_leak() -> None:
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    log = logging.getLogger("proveflow.test.launchspec")
    log.addHandler(handler)
    log.setLevel(logging.DEBUG)
    try:
        log.info("spec %s %r", make(), make())
        log.info("spec", extra={"spec": make()})
    finally:
        log.removeHandler(handler)
    assert SECRET not in buf.getvalue()


def test_traceback_with_locals_does_not_leak() -> None:
    def boom(spec: LaunchSpec) -> None:
        local_copy = spec  # noqa: F841 - deliberately in locals
        raise RuntimeError("boom")

    try:
        boom(make())
    except RuntimeError as exc:
        tb = traceback.TracebackException.from_exception(exc, capture_locals=True)
        rendered = "".join(tb.format())
    assert "LaunchSpec(" in rendered
    assert SECRET not in rendered


def test_wipe_and_context_manager() -> None:
    spec = make()
    with spec as s:
        assert s.env == {"API_KEY": SECRET}
    with pytest.raises(LaunchSpecError):
        _ = spec.env
    assert SECRET not in repr(spec)


def test_secret_values_sorted_and_min_length() -> None:
    spec = LaunchSpec(
        "s", "npx", ["--token", SECRET, "x"], {"A": SECRET, "B": "1", "C": "longer-value"}
    )
    values = spec.secret_values()
    assert values[0] == SECRET
    assert "1" not in values
    assert "longer-value" in values


def _servers_file(tmp_path: Path, env_value: str = SECRET) -> Path:
    path = tmp_path / "servers.json"
    path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "srv": {"command": "npx", "args": ["-y", "pkg"], "env": {"K": env_value}}
                }
            }
        ),
        encoding="utf-8",
    )
    return path


def test_build_from_matching_config(tmp_path: Path) -> None:
    [cfg] = read_explicit(_servers_file(tmp_path))
    with build_launch_spec(cfg.servers[0]) as spec:
        assert spec.command == "npx"
        assert spec.args == ("-y", "pkg")
        assert spec.env == {"K": SECRET}


def test_config_changed_since_discover_is_refused(tmp_path: Path) -> None:
    path = _servers_file(tmp_path)
    [cfg] = read_explicit(path)
    _servers_file(tmp_path, env_value="PLANTEDchangedValue001")
    with pytest.raises(ConfigChangedError) as exc:
        build_launch_spec(cfg.servers[0])
    assert "PLANTED" not in str(exc.value)


def test_server_removed_is_refused(tmp_path: Path) -> None:
    path = _servers_file(tmp_path)
    [cfg] = read_explicit(path)
    path.write_text(json.dumps({"mcpServers": {}}), encoding="utf-8")
    with pytest.raises(ConfigChangedError):
        build_launch_spec(cfg.servers[0])


def test_remote_server_is_not_launchable(tmp_path: Path) -> None:
    path = tmp_path / "r.json"
    path.write_text(json.dumps({"mcpServers": {"r": {"url": "https://x.example/mcp"}}}), "utf-8")
    [cfg] = read_explicit(path)
    with pytest.raises(LaunchSpecError):
        build_launch_spec(cfg.servers[0])


def test_claude_code_local_scope_entry(tmp_path: Path) -> None:
    s = full_setup(tmp_path)
    configs = run_discovery(s.host, s.project)
    local = next(
        c
        for c in configs
        if c.kind is ClientKind.CLAUDE_CODE
        and c.scope is ConfigScope.LOCAL
        and c.project
        and c.project != "D:/work/other"
    )
    slack = next(sp for sp in local.servers if sp.name == "slack")
    with build_launch_spec(slack) as spec:
        assert spec.command == "node"
        assert spec.env == {"X": "PLANTEDccLocalEnv0001"}
