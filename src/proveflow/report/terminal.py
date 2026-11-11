"""Rich terminal rendering. All user-derived text goes through ``Text`` (no markup
interpretation), and only redacted model fields are ever rendered."""

from __future__ import annotations

from rich.console import Console
from rich.table import Table
from rich.text import Text

from proveflow.core.client import ConfigStatus, ServerSpec
from proveflow.core.tools import ToolRole
from proveflow.report.models import DiscoverReport, ScanReport

_STATUS_STYLE = {
    ConfigStatus.FOUND: "green",
    ConfigStatus.NOT_FOUND: "dim",
    ConfigStatus.PARSE_ERROR: "red",
    ConfigStatus.UNREADABLE: "red",
    ConfigStatus.UNSUPPORTED: "yellow",
}
_ROLE_SHORT = {
    ToolRole.UNTRUSTED_SOURCE: "source",
    ToolRole.PRIVATE_DATA: "private",
    ToolRole.SINK: "sink",
}


def command_line(spec: ServerSpec) -> str:
    if spec.command is not None:
        return " ".join([str(spec.command), *(str(a) for a in spec.args)])
    if spec.url is not None:
        return str(spec.url)
    return ""


def render_discover(report: DiscoverReport, console: Console) -> None:
    configs = Table(title="MCP client configs", show_lines=False)
    for col in ("client", "scope", "status", "servers", "path / detail"):
        configs.add_column(col)
    for cfg in report.configs:
        where = str(cfg.path) if cfg.path else ""
        if cfg.project and cfg.scope == "local":
            where += f"  [project {cfg.project}]"
        if cfg.detail:
            where += f"  ({cfg.detail})"
        if cfg.entry_errors:
            where += f"  ({len(cfg.entry_errors)} bad entries skipped)"
        configs.add_row(
            Text(cfg.kind.value),
            Text(cfg.scope.value),
            Text(cfg.status.value, style=_STATUS_STYLE[cfg.status]),
            Text(str(len(cfg.servers)) if cfg.status is ConfigStatus.FOUND else "-"),
            Text(where),
        )
    console.print(configs)

    servers = Table(title="Configured servers (secrets redacted)")
    for col in (
        "client",
        "scope",
        "server",
        "transport",
        "command / url",
        "env keys",
        "header keys",
    ):
        servers.add_column(col)
    for cfg in report.configs:
        for spec in cfg.servers:
            servers.add_row(
                Text(cfg.kind.value),
                Text(spec.scope.value),
                Text(spec.name),
                Text(spec.transport.value + (" (auth)" if spec.auth_hint else "")),
                Text(command_line(spec)),
                Text(", ".join(sorted(spec.env))),
                Text(", ".join(sorted(spec.headers))),
            )
    console.print(servers)
    for cfg in report.configs:
        for err in cfg.entry_errors:
            console.print(Text(f"entry error in {cfg.path}: {err}", style="red"))
    console.print(
        Text(
            "Values of env/headers are never shown; args/URLs are redacted by pattern "
            "(docs/REDACTION.md).",
            style="dim",
        )
    )


def render_scan(report: ScanReport, console: Console, limit: int) -> None:
    for prof in report.profiles:
        table = Table(title=f"Profile {prof.id}")
        for col in ("server", "transport", "introspection", "roles (server-level guess)"):
            table.add_column(col)
        for srv in prof.servers:
            roles = sorted({_ROLE_SHORT[e.role] for t in srv.tools for e in t.roles})
            table.add_row(
                Text(srv.key),
                Text(srv.spec.transport.value),
                Text(srv.introspection.text),
                Text(", ".join(roles) or "-"),
            )
        console.print(table)
        for line in (*prof.shadowed, *prof.notes):
            console.print(Text(f"  note: {line}", style="dim"))

    flows = Table(title=f"Toxic flows ({len(report.flows)} total, all THEORETICAL)")
    for col in (
        "id",
        "class",
        "profile",
        "source",
        "private",
        "sink",
        "cross",
        "sink kind",
        "conf",
    ):
        flows.add_column(col)
    for f in report.flows[:limit]:
        flows.add_row(
            Text(f.id),
            Text(f.flow_class.value),
            Text(f.profile),
            Text(f.source.label if f.source else "-"),
            Text(f.private.label if f.private else "-"),
            Text(f.sink.label),
            Text("yes" if f.cross_server else "no"),
            Text(f.sink_severity.value),
            Text(f"{f.confidence:.2f}" + (" (server)" if f.granularity == "server" else "")),
        )
    console.print(flows)
    if len(report.flows) > limit:
        console.print(
            Text(f"... {len(report.flows) - limit} more flows (use --limit, --json or --sarif)")
        )
    for o in report.unused_overrides:
        console.print(Text(f"unused override: {o}", style="yellow"))
    for lim in report.limitations:
        console.print(Text(f"limitation: {lim}", style="dim"))
