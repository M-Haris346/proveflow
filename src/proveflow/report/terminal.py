"""Rich terminal rendering. All user-derived text goes through ``Text`` (no markup
interpretation), and only redacted model fields are ever rendered."""

from __future__ import annotations

from rich.console import Console
from rich.table import Table
from rich.text import Text

from proveflow.core.client import ConfigStatus, ServerSpec
from proveflow.core.tools import Granularity, ToolRole
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


_BASELINE_TEXT = {
    "first_seen": "first run (nothing to compare)",
    "compared": "compared with cache",
    "cache_disabled": "no cache (not compared)",
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
        for col in (
            "server",
            "transport",
            "introspection",
            "era",
            "tools",
            "baseline",
            "redacted",
            "roles",
        ):
            table.add_column(col)
        for srv in prof.servers:
            roles = sorted({_ROLE_SHORT[e.role] for t in srv.tools for e in t.roles})
            server_level = any(t.name == "*" for t in srv.tools)
            table.add_row(
                Text(srv.key),
                Text(srv.spec.transport.value),
                Text(srv.introspection.text),
                Text(srv.era or "-"),
                Text("-" if server_level else str(len(srv.tools))),
                Text(_BASELINE_TEXT.get(srv.baseline or "", "-")),
                Text(str(srv.pattern_redactions) if srv.introspection == "ok" else "-"),
                Text((", ".join(roles) or "-") + (" (server-level guess)" if server_level else "")),
            )
        console.print(table)
        for line in (*prof.shadowed, *prof.notes):
            console.print(Text(f"  note: {line}", style="dim"))
        for srv in prof.servers:
            if srv.detail:
                console.print(Text(f"  {srv.key}: {srv.detail}", style="yellow"))
            for change in srv.changes:
                console.print(
                    Text(
                        f"  CHANGED since last scan: {srv.key}/{change.tool} "
                        f"{change.kind.value} (possible rug-pull; review before trusting)",
                        style="bold yellow",
                    )
                )

    if report.skipped:
        skipped = Table(title=f"Skipped servers ({len(report.skipped)}, NOT analyzed)")
        for col in ("server", "client", "scope", "reason", "detail"):
            skipped.add_column(col)
        for sk in report.skipped:
            skipped.add_row(
                Text(sk.server_ref),
                Text(sk.client.value),
                Text(sk.scope.value),
                Text(sk.reason.value),
                Text(sk.detail),
            )
        console.print(skipped)
    console.print(
        Text(
            f"Servers: {report.discovered_servers} discovered, {report.analyzed_servers} "
            f"analyzed, {len(report.skipped)} skipped",
            style="yellow" if report.skipped else "",
        )
    )

    if not report.profiles:
        # Never print a bare "0 flows": with nothing analyzed, zero flows means nothing.
        console.print(
            Text(
                f"No servers analyzed: {report.discovered_servers} discovered, "
                f"{len(report.skipped)} skipped. No flow list was computed; this is NOT a "
                "clean result.",
                style="bold yellow",
            )
        )
        _render_tail(report, console)
        return

    # One row per flow GROUP (ARCHITECTURE §5.3): grouping reduces table rows, not the
    # number of tool paths; every member flow is in --json / --sarif.
    groups = Table(
        title=f"Toxic flows: {len(report.groups)} groups ({len(report.flows)} flows), "
        "all THEORETICAL"
    )
    for col in (
        "id",
        "class",
        "source",
        "private",
        "sink",
        "cross",
        "worst sink kind",
        "max conf",
        "#flows",
        "#profiles",
    ):
        groups.add_column(col)
    for g in report.groups[:limit]:
        server_only = tuple(g.granularities) == (Granularity.SERVER,)
        groups.add_row(
            Text(g.id),
            Text(g.flow_class.value),
            Text(g.source_server or "-"),
            Text(g.private_server or "-"),
            Text(g.sink_server),
            Text("yes" if g.cross_server else "no"),
            Text(g.worst_sink_severity.value),
            Text(f"{g.max_confidence:.2f}" + (" (server)" if server_only else "")),
            Text(str(len(g.member_ids))),
            Text(str(len(g.profiles))),
        )
    console.print(groups)
    if len(report.groups) > limit:
        console.print(
            Text(f"... {len(report.groups) - limit} more groups (use --limit, --json or --sarif)")
        )
    _render_tail(report, console)


def _render_tail(report: ScanReport, console: Console) -> None:
    if report.findings:
        notes = Table(title="Supply-chain notes (PF-UNPINNED)")
        for col in ("server", "launcher", "package", "status", "reason"):
            notes.add_column(col)
        for fnd in report.findings:
            notes.add_row(
                Text(fnd.server),
                Text(fnd.launcher),
                Text(fnd.package or "-"),
                Text(fnd.status),
                Text(fnd.reason),
            )
        console.print(notes)
    for o in report.unused_overrides:
        console.print(Text(f"unused override: {o}", style="yellow"))
    for lim in report.limitations:
        console.print(Text(f"limitation: {lim}", style="dim"))
