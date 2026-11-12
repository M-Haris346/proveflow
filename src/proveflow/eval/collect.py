"""Collect tools/list from the eval servers into JSONL with provenance per tool.

    python -m proveflow.eval.collect --servers data/eval/roles/servers.json \\
        --out out/tools.jsonl --yes [--timeout 180] [--ignore-scripts] [--no-build]
        [--protocol auto]

Meant to run ONLY in the ephemeral runner (.github/workflows/eval-collect.yml), never on a
developer laptop: the eval servers are third-party code. It reuses proveflow's
introspection runner unchanged (tools/list only, method allowlist, process-tree kill,
minimal env, empty temp cwd, scrubbing). Per run:

1. a fresh temp work dir; each server's ``setup`` steps run there (``mkdir:<rel>``,
   ``git-init:<rel>``); ``{workdir}`` in args/env is replaced by that dir;
2. ``--ignore-scripts`` adds ``npm_config_ignore_scripts=true`` to every server's env (npm
   config docs: npm_config_* env vars are config; ignore-scripts "If true, npm does not run
   scripts specified in package.json files");
   ``--no-build`` adds ``UV_NO_BUILD=1`` (uv docs: "If set, uv will not build source
   distributions"). Both go into each SERVER's env on purpose: a launched server gets only
   the minimal allow-list plus its own env (introspect/env.py), so a job-level variable
   would never reach npx/uvx;
3. a concrete ``mcpServers`` file is written into the work dir and read with the normal
   ``--servers`` reader, so LaunchSpec / TOCTOU / redaction all apply as in ``scan``;
4. one JSONL record per tool (sorted by server id, tool name) + a summary JSON listing
   every server's status. No timestamps in the JSONL (byte-reproducible for the same
   tools/list answers); the summary carries ``collected_at``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from datetime import UTC, datetime
from importlib.metadata import version as dist_version
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, ValidationError, model_validator
from rich.console import Console
from rich.text import Text

from proveflow import __version__
from proveflow.core._base import FrozenModel
from proveflow.discover.readers import read_explicit
from proveflow.introspect.cache import spec_key
from proveflow.report.models import IntrospectionResult, IntrospectionStatus

SCHEMA_VERSION = 1
WORKDIR = "{workdir}"


class CollectError(RuntimeError):
    """Bad spec or setup; message never contains env values."""


class PackageRef(FrozenModel):
    registry: Literal["npm", "pypi"]
    name: str
    version: str


class EvalServer(FrozenModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")
    source: Literal["reference", "popular", "registry", "fake"]
    package: PackageRef | None = None
    license: str
    repo: str | None = None
    command: str
    args: tuple[str, ...] = ()
    env: dict[str, str] = Field(default_factory=dict)
    setup: tuple[str, ...] = ()
    notes: str | None = None


class EvalServerSet(FrozenModel):
    schema_version: Literal[1]
    comment: str | None = Field(default=None, alias="_comment")
    servers: tuple[EvalServer, ...]

    @model_validator(mode="after")
    def _unique(self) -> EvalServerSet:
        ids = [s.id for s in self.servers]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate server id")
        return self


def load_server_set(path: Path) -> EvalServerSet:
    try:
        return EvalServerSet.model_validate_json(path.read_text(encoding="utf-8"))
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}"
            for e in exc.errors(include_input=False, include_url=False)
        )
        raise CollectError(f"{path}: {problems}") from None


def _run_setup(step: str, workdir: Path) -> None:
    kind, _, rel = step.partition(":")
    target = (workdir / rel).resolve()
    if not rel or workdir.resolve() not in target.parents:
        raise CollectError(f"setup step {step!r} must name a path inside the work dir")
    if kind == "mkdir":
        target.mkdir(parents=True, exist_ok=True)
    elif kind == "git-init":
        git = shutil.which("git")
        if git is None:
            raise CollectError("setup git-init needs git on PATH")
        target.mkdir(parents=True, exist_ok=True)
        subprocess.run([git, "init", "-q", str(target)], check=True)  # noqa: S603
    else:
        raise CollectError(f"unknown setup step {kind!r}")


def materialize(
    servers: Sequence[EvalServer],
    workdir: Path,
    *,
    ignore_scripts: bool,
    no_build: bool = False,
) -> dict[str, Any]:
    """Run setup steps and return a concrete ``mcpServers`` mapping (no placeholders)."""
    root = str(workdir)
    out: dict[str, Any] = {}
    for srv in servers:
        for step in srv.setup:
            _run_setup(step, workdir)
        env = {k: v.replace(WORKDIR, root) for k, v in srv.env.items()}
        if ignore_scripts:
            env["npm_config_ignore_scripts"] = "true"
        if no_build:
            env["UV_NO_BUILD"] = "1"
        out[srv.id] = {
            "command": srv.command,
            "args": [a.replace(WORKDIR, root) for a in srv.args],
            "env": env,
        }
    return out


def tool_sha256(name: str, description: str, schema: dict[str, Any]) -> str:
    body = json.dumps(
        {"name": name, "description": description, "input_schema": schema},
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _sdk_version() -> str:
    try:
        return dist_version("mcp")
    except Exception:
        return "unknown"


def records_for(srv: EvalServer, result: IntrospectionResult) -> list[dict[str, Any]]:
    provenance = {
        "source": srv.source,
        "package": srv.package.model_dump() if srv.package else None,
        "license": srv.license,
        "repo": srv.repo,
        "collected_by": "tools/list via proveflow.eval.collect",
        "protocol_version": result.protocol_version,
        "era": result.era,
        "pattern_redactions": result.pattern_redactions,
        "proveflow_version": __version__,
        "mcp_sdk_version": _sdk_version(),
    }
    return [
        {
            "schema_version": SCHEMA_VERSION,
            "server_id": srv.id,
            "tool_name": t.name,
            "description": t.description,
            "input_schema": t.input_schema,
            "tool_sha256": tool_sha256(t.name, t.description, t.input_schema),
            "provenance": provenance,
        }
        for t in sorted(result.tools, key=lambda t: t.name)
    ]


def collect(
    server_set: EvalServerSet,
    *,
    timeout: float,
    ignore_scripts: bool,
    no_build: bool = False,
    protocol: Literal["auto", "legacy"] = "auto",
    only: Sequence[str] = (),
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    # Lazy: imports the MCP SDK.
    from proveflow.introspect.runner import introspect_specs

    chosen = [s for s in server_set.servers if not only or s.id in only]
    unknown = set(only) - {s.id for s in server_set.servers}
    if unknown:
        raise CollectError(f"unknown server ids: {sorted(unknown)}")
    with tempfile.TemporaryDirectory(prefix="proveflow-eval-") as tmp:
        workdir = Path(tmp)
        concrete = materialize(chosen, workdir, ignore_scripts=ignore_scripts, no_build=no_build)
        cfg_path = workdir / "servers.json"
        cfg_path.write_text(json.dumps({"mcpServers": concrete}, indent=2), encoding="utf-8")
        [cfg] = read_explicit(cfg_path)
        if cfg.entry_errors:
            raise CollectError("; ".join(cfg.entry_errors))
        specs = {spec.name: spec for spec in cfg.servers}
        results = introspect_specs(
            [specs[s.id] for s in chosen],
            consent=lambda _spec: "yes",
            timeout=timeout,
            cache=None,
            protocol=protocol,
        )
    records: list[dict[str, Any]] = []
    servers_summary: list[dict[str, Any]] = []
    for srv in sorted(chosen, key=lambda s: s.id):
        res = results.get(spec_key(specs[srv.id]))
        if res is None:  # pragma: no cover - every stdio spec gets a result
            res = IntrospectionResult(status=IntrospectionStatus.FAILED, detail="no result")
        if res.status is IntrospectionStatus.OK:
            records += records_for(srv, res)
        servers_summary.append(
            {
                "server_id": srv.id,
                "status": res.status.value,
                "tools": len(res.tools),
                "protocol_version": res.protocol_version,
                "detail": res.detail,
                "stderr_tail": res.stderr_tail,
            }
        )
    summary = {
        "schema_version": SCHEMA_VERSION,
        "collected_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "proveflow_version": __version__,
        "mcp_sdk_version": _sdk_version(),
        "ignore_scripts": ignore_scripts,
        "no_build": no_build,
        "protocol": protocol,
        "timeout_s": timeout,
        "servers": servers_summary,
        "tools_total": len(records),
    }
    return records, summary


def write_outputs(out: Path, records: list[dict[str, Any]], summary: dict[str, Any]) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(r, sort_keys=True, ensure_ascii=False) for r in records]
    out.write_text("".join(line + "\n" for line in lines), encoding="utf-8", newline="\n")
    summary_path = out.with_suffix(out.suffix + ".summary.json")
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    return summary_path


def main(argv: Sequence[str] | None = None) -> int:
    console = Console(stderr=True)
    parser = argparse.ArgumentParser(prog="python -m proveflow.eval.collect")
    parser.add_argument("--servers", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--yes", action="store_true", help="consent to launching every server")
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--ignore-scripts", action="store_true")
    parser.add_argument("--no-build", action="store_true", help="UV_NO_BUILD=1 for servers")
    parser.add_argument("--protocol", choices=["auto", "legacy"], default="auto")
    parser.add_argument("--only", action="append", default=[])
    ns = parser.parse_args(argv)
    if not ns.yes:
        console.print(
            Text(
                "refusing to launch eval servers without --yes (this runs third-party code; "
                "use it only in the ephemeral runner)",
                style="red",
            )
        )
        return 2
    try:
        server_set = load_server_set(ns.servers)
        records, summary = collect(
            server_set,
            timeout=ns.timeout,
            ignore_scripts=ns.ignore_scripts,
            no_build=ns.no_build,
            protocol=ns.protocol,
            only=ns.only,
        )
    except CollectError as exc:
        console.print(Text(f"error: {exc}", style="red"))
        return 1
    summary_path = write_outputs(ns.out, records, summary)
    for row in summary["servers"]:
        console.print(Text(f"{row['server_id']}: {row['status']}, {row['tools']} tools"))
    console.print(Text(f"{summary['tools_total']} tools -> {ns.out} (summary: {summary_path})"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
