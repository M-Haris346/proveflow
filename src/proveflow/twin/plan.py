"""``proveflow twin``: one twin script and one proxy session per server of a scanned profile
(Phase 4 D10, R-C6/R-C7). No network, nothing launched; the CLI only prints to stderr.

Input is a ``scan --json`` report in introspection mode. A ``--no-launch`` scan is refused:
it has no tool lists, only server-level guesses, and a twin needs the real tool surface.

Output, all inside ``out_dir``, which must resolve under ``proxy.policy.TWIN_ROOT`` (layer A
only accepts twin scripts there, so a session pointing elsewhere would be refused at load):
* ``pftwin-<slug>.py``             the generated twin (``twin.generator``)
* ``pftwin-<slug>.session.json``   a ``ProxySession`` (schema 3): the scan's classified tools,
                                   the twin's sha256 and honey, no attack, never markers
* the session's cassette path ``pftwin-<slug>.cassette.jsonl`` must not exist yet.
Every target path is checked BEFORE anything is written; any existing file refuses the whole
run (no overwrite, no partial output).

A server that was not introspected successfully, or has no tool list, is skipped with its
reason. ``[[twin_override]]`` entries (server, tool, archetype) choose archetypes; an entry
naming an unknown archetype is an error, one naming no planned tool is reported as unused.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from proveflow.config import TwinOverride
from proveflow.proxy.policy import TwinUpstream, under_twin_root
from proveflow.proxy.session import MAX_SESSION_FILE, ProxySession
from proveflow.report.models import IntrospectionStatus, ScanReport, ServerReport
from proveflow.twin.archetypes import ARCHETYPES
from proveflow.twin.generator import TwinBuild, generate_twin, twin_slug, write_twin

MAX_SCAN_FILE = 64 * 1024 * 1024


class TwinPlanError(ValueError):
    """The request cannot be planned; nothing was written."""


@dataclass(frozen=True)
class SkippedServer:
    server: str
    reason: str


@dataclass(frozen=True)
class PlannedTwin:
    server: str
    build: TwinBuild
    twin_path: Path
    session_path: Path
    cassette_path: Path
    report: ServerReport


@dataclass(frozen=True)
class TwinPlan:
    profile: str
    twins: tuple[PlannedTwin, ...]
    skipped: tuple[SkippedServer, ...]
    unused_overrides: tuple[TwinOverride, ...]


def load_scan(path: Path) -> ScanReport:
    if path.stat().st_size > MAX_SCAN_FILE:
        raise TwinPlanError(f"scan report larger than {MAX_SCAN_FILE} bytes")
    report = ScanReport.model_validate_json(path.read_bytes())
    if report.mode != "introspect":
        raise TwinPlanError(
            "the scan was made with --no-launch: it has no tool lists, only server-level "
            "guesses. Run `proveflow scan --json` with introspection first"
        )
    return report


def _skip_reason(server: ServerReport) -> str | None:
    if server.introspection is not IntrospectionStatus.OK:
        return f"not introspected ({server.introspection.value})"
    if not server.tools or all(t.name == "*" for t in server.tools):
        return "no tool list"
    return None


def plan_twins(
    report: ScanReport,
    profile_id: str,
    out_dir: Path,
    *,
    seed: str,
    overrides: Sequence[TwinOverride] = (),
) -> TwinPlan:
    profile = next((p for p in report.profiles if p.id == profile_id), None)
    if profile is None:
        ids = ", ".join(sorted(p.id for p in report.profiles)) or "(none)"
        raise TwinPlanError(f"no profile {profile_id!r} in the scan; profiles: {ids}")
    if not under_twin_root(out_dir):
        raise TwinPlanError(
            "--out-dir must be inside the proveflow twin directory (TWIN_ROOT); the proxy "
            "refuses any twin script outside it"
        )
    known = set(ARCHETYPES)
    for o in overrides:
        if o.archetype not in known:
            raise TwinPlanError(
                f"twin_override {o.server}/{o.tool}: unknown archetype {o.archetype!r} "
                f"(known: {', '.join(sorted(known))})"
            )
    used: set[TwinOverride] = set()
    twins: list[PlannedTwin] = []
    skipped: list[SkippedServer] = []
    slugs: dict[str, str] = {}
    for server in profile.servers:
        reason = _skip_reason(server)
        if reason is not None:
            skipped.append(SkippedServer(server=server.key, reason=reason))
            continue
        slug = twin_slug(server.key)
        if slug in slugs:
            raise TwinPlanError(
                f"servers {slugs[slug]!r} and {server.key!r} map to the same file name"
            )
        slugs[slug] = server.key
        names = {t.name for t in server.tools}
        mine = {o.tool: o.archetype for o in overrides if o.server == server.key}
        used |= {o for o in overrides if o.server == server.key and o.tool in names}
        build = generate_twin(server.key, server.tools, seed=seed, overrides=mine)
        twins.append(
            PlannedTwin(
                server=server.key,
                build=build,
                twin_path=out_dir / build.filename,
                session_path=out_dir / f"pftwin-{slug}.session.json",
                cassette_path=(out_dir / f"pftwin-{slug}.cassette.jsonl").resolve(),
                report=server,
            )
        )
    unused = tuple(o for o in overrides if o not in used)
    return TwinPlan(profile=profile_id, twins=tuple(twins), skipped=tuple(skipped),
                    unused_overrides=unused)  # fmt: skip


def write_plan(plan: TwinPlan, out_dir: Path) -> list[Path]:
    """Refuse if ANY target exists, then write every twin, then every session."""
    targets = [p for t in plan.twins for p in (t.twin_path, t.session_path, t.cassette_path)]
    existing = [p for p in targets if p.exists()]
    if existing:
        raise TwinPlanError(
            f"refusing to overwrite {len(existing)} existing file(s), e.g. {existing[0].name}"
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for t in plan.twins:
        written.append(write_twin(t.build, out_dir))
    for t in plan.twins:
        session = ProxySession(
            session_id=f"twin-{twin_slug(t.server)}",
            upstream=TwinUpstream(
                name=twin_slug(t.server), argv=(sys.executable, str(t.twin_path.resolve()))
            ),
            twin_sha256=t.build.sha256,
            tools=t.report.tools,
            honey=t.build.honey,
            cassette_path=t.cassette_path,
        )
        data = session.model_dump_json(indent=2).encode("utf-8")
        if len(data) > MAX_SESSION_FILE:
            raise TwinPlanError(f"session for {t.server!r} exceeds {MAX_SESSION_FILE} bytes")
        with t.session_path.open("xb") as fh:
            fh.write(data)
        written.append(t.session_path)
    return written


def summary_rows(plan: TwinPlan) -> list[tuple[str, int, int, int, int, int]]:
    """(server, tools, honey, sinks, dual-role, skipped-keyword tools) per planned twin."""
    from proveflow.proxy.policy import session_dual_role_names, session_sink_names

    rows: list[tuple[str, int, int, int, int, int]] = []
    for t in plan.twins:
        tools = t.report.tools
        sinks = session_sink_names(tools)
        dual = session_dual_role_names(tools)
        pure_sinks = len(sinks - dual)
        skipped = sum(1 for v in t.build.skipped.values() if v)
        rows.append((t.server, len(tools), len(t.build.honey), pure_sinks, len(dual), skipped))
    return rows


__all__ = [
    "PlannedTwin",
    "SkippedServer",
    "TwinPlan",
    "TwinPlanError",
    "load_scan",
    "plan_twins",
    "summary_rows",
    "write_plan",
]
