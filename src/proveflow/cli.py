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
    console = _console()
    if json_output:
        console.out(to_json(report), highlight=False, end="")
    else:
        render_discover(report, console)


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
    limit: Annotated[int, typer.Option("--limit", min=0, help="Flows shown in the table.")] = 50,
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
        console.out(to_json(report), highlight=False, end="")
    else:
        render_scan(report, console, limit)
        if sarif is not None:
            console.print(Text(f"SARIF written to {sarif}"))


@app.command()
def prove() -> None:
    """Attack flows in a safe schema twin and report confirmed exploits."""
    _stub("prove", "Phase 7")


@app.command()
def fix() -> None:
    """Write a mitigation patch for a flow (never applied automatically)."""
    _stub("fix", "Phase 8")


@app.command()
def verify() -> None:
    """Re-run the same attacks with a fix applied and measure the change."""
    _stub("verify", "Phase 8")


@app.command()
def replay() -> None:
    """Deterministically re-check a stored run from its cassette."""
    _stub("replay", "Phase 5")
