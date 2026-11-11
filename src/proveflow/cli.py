"""proveflow CLI.

Unimplemented subcommands are honest stubs: they name the phase that will implement
them (docs/ARCHITECTURE.md §9) and exit with code 2. No fake output, ever.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.text import Text

from proveflow import __version__, logging_setup
from proveflow.config import ConfigError, ProveflowConfig, load_config
from proveflow.discover import HostEnv, run_discovery
from proveflow.report.json_out import to_json
from proveflow.report.models import DiscoverReport
from proveflow.report.sarif import write_sarif
from proveflow.report.terminal import render_discover, render_scan
from proveflow.scan import build_scan

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
) -> None:
    """Static toxic-flow map of the discovered setup, no LLM."""
    console = _console()
    if not no_launch:
        console.print(
            Text(
                "scan: introspection (launching servers for tools/list) is not implemented yet "
                "(Phase 1, checkpoint 1b). Use --no-launch for a config-only scan."
            )
        )
        raise typer.Exit(code=NOT_IMPLEMENTED_EXIT_CODE)
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
    configs = run_discovery(_host(), proj, servers)
    report = build_scan(configs, _host(), proj, cfg)
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
