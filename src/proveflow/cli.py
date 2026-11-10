"""proveflow CLI skeleton.

Every subcommand is an honest stub: it names the phase that will implement it
(docs/ARCHITECTURE.md §9) and exits with code 2. No fake output, ever.
"""

from __future__ import annotations

from typing import Annotated

import typer
from rich.console import Console

from proveflow import __version__, logging_setup

app = typer.Typer(
    name="proveflow",
    help="Find, prove, fix, and verify cross-server toxic flows in your MCP tool setup.",
    no_args_is_help=True,
)
console = Console()

NOT_IMPLEMENTED_EXIT_CODE = 2


def _stub(command: str, phase: str) -> None:
    console.print(
        f"[yellow]{command}[/yellow]: not implemented yet ({phase}). "
        "See docs/ARCHITECTURE.md section 9 for the build plan."
    )
    raise typer.Exit(code=NOT_IMPLEMENTED_EXIT_CODE)


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"proveflow {__version__}")
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


@app.command()
def discover() -> None:
    """Find MCP client configs on this machine (secrets redacted)."""
    _stub("discover", "Phase 1")


@app.command()
def scan() -> None:
    """Static toxic-flow map of the discovered setup, no LLM."""
    _stub("scan", "Phase 1")


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
