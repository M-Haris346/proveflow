"""proveflow CLI.

Unimplemented subcommands are honest stubs: they name the phase that will implement
them (docs/ARCHITECTURE.md §9) and exit with code 2. No fake output, ever.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Literal

import typer
from rich.console import Console
from rich.text import Text

from proveflow import __version__, logging_setup
from proveflow.config import ConfigError, ProveflowConfig, load_config
from proveflow.core.client import ClientConfig, ConfigScope, ServerSpec
from proveflow.discover import HostEnv, run_discovery
from proveflow.discover.profiles import build_profiles
from proveflow.report.json_out import to_json
from proveflow.report.models import DiscoverReport, IntrospectionResult
from proveflow.report.sarif import write_sarif
from proveflow.report.terminal import command_line, render_discover, render_scan
from proveflow.scan import build_scan, stdio_specs

Consent = Literal["yes", "no", "unavailable"]

app = typer.Typer(
    name="proveflow",
    help="Find, prove, fix, and verify cross-server toxic flows in your MCP tool setup.",
    no_args_is_help=True,
    # Never render local variables in tracebacks: locals can hold config contents.
    # (Typer docs: default is already off since 0.23.0; set explicitly anyway.)
    pretty_exceptions_show_locals=False,
)

NOT_IMPLEMENTED_EXIT_CODE = 2
USAGE_ERROR_EXIT_CODE = 1
DEFAULT_CONFIG_NAME = "proveflow.toml"


def _console() -> Console:
    # Created per invocation so width/env (e.g. COLUMNS) are read at run time.
    return Console()


def _host() -> HostEnv:
    """The only place the real host environment is read (tests replace this)."""
    return HostEnv.current()


def _stub(command: str, phase: str) -> None:
    _console().print(
        f"[yellow]{command}[/yellow]: not implemented yet ({phase}). "
        "See docs/ARCHITECTURE.md section 9 for the build plan."
    )
    raise typer.Exit(code=NOT_IMPLEMENTED_EXIT_CODE)


def _version_callback(value: bool) -> None:
    if value:
        _console().print(f"proveflow {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option("--version", callback=_version_callback, is_eager=True),
    ] = False,
    log_level: Annotated[
        str,
        typer.Option("--log-level", help="Logging level (DEBUG, INFO, WARNING, ERROR)."),
    ] = "WARNING",
) -> None:
    """Configure logging before any subcommand runs."""
    logging_setup.configure(log_level)


ProjectOpt = Annotated[
    Path | None,
    typer.Option(
        "--project",
        help="Project directory for project-scoped configs (default: cwd).",
        file_okay=False,
    ),
]
ServersOpt = Annotated[
    Path | None,
    typer.Option(
        "--servers",
        help="Extra MCP servers JSON file (mcpServers or servers shape).",
        exists=True,
        dir_okay=False,
    ),
]
JsonOpt = Annotated[bool, typer.Option("--json", help="Print JSON instead of tables.")]


def _project(project: Path | None) -> Path:
    return (project or Path.cwd()).resolve()


def _emit_machine_output(text: str) -> None:
    """Machine-readable stdout (``--json``) is always UTF-8 with LF line endings, whatever
    the locale or console code page. A redirected stdout on Windows otherwise encodes with
    the ANSI code page (e.g. cp1252: an em dash becomes byte 0x97, non-BMP text raises).
    The human-readable Rich output keeps the stream's own encoding."""
    stream = sys.stdout
    buffer = getattr(stream, "buffer", None)
    if buffer is None:  # text-only stream without a byte layer (nothing to encode)
        stream.write(text)
        stream.flush()
        return
    stream.flush()
    buffer.write(text.encode("utf-8"))
    buffer.flush()


@app.command()
def discover(
    project: ProjectOpt = None, servers: ServersOpt = None, json_output: JsonOpt = False
) -> None:
    """Find MCP client configs on this machine (secrets redacted)."""
    proj = _project(project)
    configs = run_discovery(_host(), proj, servers)
    report = DiscoverReport(
        proveflow_version=__version__, project=str(proj), configs=tuple(configs)
    )
    if json_output:
        _emit_machine_output(to_json(report))
    else:
        render_discover(report, _console())


def _interactive() -> bool:
    """Can we ask a human? The prompt is written to STDERR and read from STDIN, so both must
    be terminals. STDOUT is irrelevant: `scan --json > out.json` still prompts. If stderr
    is redirected the prompt would be invisible, so we do not ask (consent_required)."""
    return _isatty(sys.stdin) and _isatty(sys.stderr)


def _isatty(stream: object) -> bool:
    isatty = getattr(stream, "isatty", None)
    try:
        return bool(isatty()) if callable(isatty) else False
    except (ValueError, OSError):  # closed or detached stream
        return False


def consent_prompt_text(spec: ServerSpec) -> str:
    """The exact consent prompt (stderr). Only redacted values are shown."""
    lines = [
        f"Launch MCP server {spec.name!r} to read its tool list (tools/list only, never "
        "tools/call)?",
        f"  command:  {command_line(spec)}",
        f"  env keys: {', '.join(sorted(spec.env)) or '(none)'} (values hidden)",
        f"  config:   {spec.source_file} [{spec.scope.value} scope]",
    ]
    if spec.scope is ConfigScope.PROJECT:
        lines.append(
            "  WARNING: this server is defined in the scanned project (repository-controlled),"
            " not by you."
        )
    lines.append(
        "  The server's own code will run on this machine with its configured environment,"
        " as your MCP client would run it."
    )
    return "\n".join(lines)


def _consent_prompt(yes: bool, yes_project: bool) -> Callable[[ServerSpec], Consent]:
    """--yes covers user/local/explicit servers only; project-scoped servers (from the
    scanned repository) need --yes-project or an interactive answer (THREAT_MODEL T15)."""
    err = Console(stderr=True)

    def ask(spec: ServerSpec) -> Consent:
        project_scoped = spec.scope is ConfigScope.PROJECT
        if yes_project and project_scoped:
            return "yes"
        if yes and not project_scoped:
            return "yes"
        if not _interactive():
            return "unavailable"
        err.print(Text(consent_prompt_text(spec)))
        return "yes" if typer.confirm("  Launch?", default=False, err=True) else "no"

    return ask


def _introspect(
    configs: list[ClientConfig],
    host: HostEnv,
    project: Path,
    *,
    yes: bool,
    yes_project: bool,
    timeout: float,
    cache_dir: Path | None,
    write_cache: bool,
    protocol: Literal["auto", "legacy"],
) -> dict[str, IntrospectionResult]:
    # Lazy: the MCP SDK is imported only when servers are actually launched.
    from proveflow.introspect.cache import ToolCache, default_cache_dir
    from proveflow.introspect.runner import introspect_specs

    root = cache_dir if cache_dir is not None else default_cache_dir(host)
    cache = ToolCache(root, write=write_cache) if root is not None else None
    specs = stdio_specs(build_profiles(configs, host, project))
    return introspect_specs(
        specs,
        consent=_consent_prompt(yes, yes_project),
        timeout=timeout,
        cache=cache,
        untrusted_dirs=[project],
        protocol=protocol,
    )


@app.command()
def scan(
    project: ProjectOpt = None,
    servers: ServersOpt = None,
    no_launch: Annotated[
        bool, typer.Option("--no-launch", help="Do not start any server; infer roles from config.")
    ] = False,
    config: Annotated[
        Path | None,
        typer.Option(
            "--config",
            help=f"Role overrides file (default: <project>/{DEFAULT_CONFIG_NAME} if present).",
            dir_okay=False,
        ),
    ] = None,
    json_output: JsonOpt = False,
    sarif: Annotated[
        Path | None,
        typer.Option("--sarif", help="Also write SARIF 2.1.0 to this path.", dir_okay=False),
    ] = None,
    limit: Annotated[
        int, typer.Option("--limit", min=0, help="Flow groups shown in the table.")
    ] = 50,
    yes: Annotated[
        bool,
        typer.Option(
            "--yes",
            help="Consent to launching your own (user/local/--servers) stdio servers. "
            "Does NOT cover servers defined in the scanned project.",
        ),
    ] = False,
    yes_project: Annotated[
        bool,
        typer.Option(
            "--yes-project",
            help="Also consent to launching servers defined in the scanned project's own "
            "config files (repository-controlled code).",
        ),
    ] = False,
    timeout: Annotated[
        float, typer.Option("--timeout", min=1.0, help="Seconds per server before kill.")
    ] = 20.0,
    cache_dir: Annotated[
        Path | None,
        typer.Option(
            "--cache-dir", help="Tool cache dir (default: per-user cache dir).", file_okay=False
        ),
    ] = None,
    protocol: Annotated[
        str,
        typer.Option(
            "--protocol",
            help="auto: send the 2026 server/discover probe, fall back to initialize "
            "(SDK default); legacy: initialize handshake only.",
            case_sensitive=False,
        ),
    ] = "auto",
    no_cache_write: Annotated[
        bool, typer.Option("--no-cache-write", help="Compare with the cache but do not update it.")
    ] = False,
) -> None:
    """Toxic-flow map of the discovered setup, no LLM.

    By default each stdio server is launched (after per-server consent) and asked for
    tools/list only - never tools/call. --no-launch never starts anything.
    """
    console = _console()
    protocol = protocol.lower()
    if protocol not in ("auto", "legacy"):
        console.print(Text("error: --protocol must be 'auto' or 'legacy'", style="red"))
        raise typer.Exit(code=USAGE_ERROR_EXIT_CODE)
    proj = _project(project)
    cfg_path = config if config is not None else proj / DEFAULT_CONFIG_NAME
    try:
        cfg = (
            load_config(cfg_path)
            if (config is not None or cfg_path.is_file())
            else ProveflowConfig()
        )
    except ConfigError as exc:
        console.print(Text(f"error: {exc}", style="red"))
        raise typer.Exit(code=USAGE_ERROR_EXIT_CODE) from None
    host = _host()
    configs = run_discovery(host, proj, servers)
    introspection = None
    if not no_launch:
        introspection = _introspect(
            configs,
            host,
            proj,
            yes=yes,
            yes_project=yes_project,
            protocol="legacy" if protocol == "legacy" else "auto",
            timeout=timeout,
            cache_dir=cache_dir,
            write_cache=not no_cache_write,
        )
    report = build_scan(configs, host, proj, cfg, introspection)
    if sarif is not None:
        write_sarif(report, sarif)
    if json_output:
        _emit_machine_output(to_json(report))
    else:
        render_scan(report, console, limit)
        if sarif is not None:
            console.print(Text(f"SARIF written to {sarif}"))


@app.command()
def proxy(
    session: Annotated[
        Path,
        typer.Option(
            "--session",
            help=(
                "Proxy session JSON (twin upstream + sha256 pin, classified tools, "
                "optional attack, cassette)."
            ),
            exists=True,
            dir_okay=False,
        ),
    ],
) -> None:
    """Serve ONE twin upstream to an agent as a stdio MCP server (twin mode only).

    The upstream must be this Python interpreter running a .py script inside the proveflow
    twin directory (per-user data dir/twins), whose sha256 matches the session pin; npx,
    uvx, node, docker, URLs and any other .py file are refused. The session lists classified
    tools, never allow/deny decisions: the proxy computes the policy itself and also runs its
    own classifier on what the twin advertises. Every tools/call it does not allow (sink by
    either opinion, unknown, unclassified, server-level, look-alike names) gets a sandbox
    response and is never forwarded. No flag, env var or session field disables this.
    Residual: a sink that both the session and the proxy's classifier miss is forwarded to
    the twin. Everything is recorded in the session's cassette (JSONL, hash-chained).
    """
    # Lazy: the proxy (and the MCP SDK) load only for this command. stdout is the MCP
    # channel, so every message here goes to stderr.
    from pydantic import ValidationError

    from proveflow.proxy.server import run_proxy
    from proveflow.proxy.session import SessionFileError, load_session

    err = Console(stderr=True)
    try:
        loaded = load_session(session)
    except (SessionFileError, ValidationError, OSError) as exc:
        message = (
            f"invalid session file ({exc.error_count()} errors)"
            if isinstance(exc, ValidationError)
            else str(exc)
        )
        err.print(Text(f"error: {message}", style="red"))
        if isinstance(exc, ValidationError):
            for error in exc.errors(include_input=False, include_url=False):
                loc = ".".join(str(p) for p in error["loc"])
                err.print(Text(f"  {loc}: {error['msg']}"))
        raise typer.Exit(code=USAGE_ERROR_EXIT_CODE) from None
    import anyio

    outcome = anyio.run(run_proxy, loaded)
    if outcome.reason not in ("agent_closed", "sigterm"):
        err.print(Text(f"proxy ended: {outcome.reason}", style="yellow"))
        raise typer.Exit(code=USAGE_ERROR_EXIT_CODE)


@app.command()
def twin(
    from_scan: Annotated[
        Path,
        typer.Option(
            "--from",
            help="A `proveflow scan --json` report made WITH introspection (not --no-launch).",
            exists=True,
            dir_okay=False,
        ),
    ],
    profile: Annotated[str, typer.Option("--profile", help="Profile id from the scan.")],
    out_dir: Annotated[
        Path,
        typer.Option(
            "--out-dir",
            help="Where to write; must be inside the proveflow twin directory (TWIN_ROOT).",
            file_okay=False,
        ),
    ],
    config_path: Annotated[
        Path | None,
        typer.Option(
            "--config",
            help="proveflow.toml with twin_override tables (server, tool, archetype).",
            exists=True,
            dir_okay=False,
        ),
    ] = None,
    seed: Annotated[
        str, typer.Option("--seed", help="Seed for the twins' synthetic data (default 0).")
    ] = "0",
) -> None:
    """Generate one schema twin and one proxy session per server of a scanned profile.

    Nothing is launched and nothing goes to the network. Each twin is a self-contained
    script with the servers' real tool names, descriptions and input schemas and synthetic,
    deterministic responses (one canned response per tool). Existing files are never
    overwritten. All output goes to stderr.
    """
    from pydantic import ValidationError

    from proveflow.twin.plan import (
        TwinPlanError,
        load_scan,
        plan_twins,
        summary_rows,
        write_plan,
    )

    err = Console(stderr=True)
    try:
        overrides = load_config(config_path).twin_override if config_path else ()
        report = load_scan(from_scan)
        plan = plan_twins(report, profile, out_dir, seed=seed, overrides=overrides)
        if not plan.twins:
            raise TwinPlanError("no server in this profile has an introspected tool list")
        written = write_plan(plan, out_dir)
    except (TwinPlanError, ConfigError, OSError) as exc:
        err.print(Text(f"error: {exc}", style="red"))
        raise typer.Exit(code=USAGE_ERROR_EXIT_CODE) from None
    except ValidationError as exc:
        err.print(Text(f"error: invalid scan report ({exc.error_count()} errors)", style="red"))
        raise typer.Exit(code=USAGE_ERROR_EXIT_CODE) from None
    for server, tools, honey, sinks, dual, skipped in summary_rows(plan):
        err.print(
            Text(
                f"{server}: {tools} tools, {honey} honey, {sinks} pure sink, {dual} dual-role, "
                f"{skipped} with unvalidated schema keywords"
            )
        )
        if sinks + dual == 0:
            err.print(
                Text(
                    f"  {server} has no sink tool: it cannot be attacked for exfiltration "
                    "(a finding about the server)",
                    style="yellow",
                )
            )
    for s in plan.skipped:
        err.print(Text(f"skipped {s.server}: {s.reason}", style="yellow"))
    for o in plan.unused_overrides:
        err.print(Text(f"unused twin_override {o.server}/{o.tool}", style="yellow"))
    err.print(Text(f"wrote {len(written)} files to {out_dir}"))


@app.command()
def prove() -> None:
    """Attack flows in a safe schema twin and report confirmed exploits."""
    _stub("prove", "Phase 7")


@app.command()
def fix(
    from_scan: Annotated[
        Path,
        typer.Option(
            "--from", help="A `proveflow scan --json` report.", exists=True, dir_okay=False
        ),
    ],
    flow: Annotated[str, typer.Option("--flow", help="Flow id from the scan (F-<8 hex>).")],
    mitigation: Annotated[
        str,
        typer.Option(
            "--mitigation",
            help="m1 (remove the sink's server) or m3 (Claude "
            "Code approval rule). m2, m4, m5 and m6 are refused with a reason.",
        ),
    ],
    out_dir: Annotated[
        Path, typer.Option("--out-dir", help="Where the fix directory is created.", file_okay=False)
    ],
) -> None:
    """Write a mitigation patch for a flow, for review. NEVER applied: proveflow never edits a
    client config. The only input is the scan report; existing fixes are never overwritten."""
    from pydantic import ValidationError

    from proveflow.fix.render import FixRefused, load_scan, render
    from proveflow.fix.writer import FixTargetExists, write_bundle
    from proveflow.runner.verify import ALIASES

    err = Console(stderr=True)
    if mitigation not in ALIASES:
        err.print(Text(f"error: --mitigation must be one of {sorted(ALIASES)}", style="red"))
        raise typer.Exit(code=USAGE_ERROR_EXIT_CODE)
    try:
        bundle = render(load_scan(from_scan), flow, ALIASES[mitigation])
        target = write_bundle(bundle, out_dir)
    except (FixRefused, FixTargetExists, OSError, ValidationError) as exc:
        err.print(Text(f"error: {exc}", style="red"))
        raise typer.Exit(code=USAGE_ERROR_EXIT_CODE) from None
    err.print(Text(f"wrote {target} ({len(bundle.edits)} patch file(s), "
                   f"{len(bundle.refused)} entry/entries not patched). NOT applied."))  # fmt: skip


@app.command(context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def verify(ctx: typer.Context) -> None:
    """Paired verify against the CONTROL (offline, $0): the same arguments as
    `python -m proveflow.runner.verify PLAN --mitigation m1|m3 --root DIR`."""
    from proveflow.runner.verify import main

    raise typer.Exit(code=main(list(ctx.args)))


@app.command()
def replay() -> None:
    """Deterministically re-check a stored run from its cassette."""
    _stub("replay", "Phase 7")
