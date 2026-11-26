"""Agent profiles: the set of servers one agent is actually connected to.

Flows only exist inside a profile — a source in Claude Desktop and a sink in Cursor
share no agent. proveflow over-approximates: every configured server is treated as
connected (client-side approval / disabled flags are not modeled; they are not in
docs/CLIENT_CONFIGS.md).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from proveflow.core._base import FrozenModel
from proveflow.core.client import ClientConfig, ClientKind, ConfigScope, ConfigStatus, ServerSpec
from proveflow.discover.hostenv import HostEnv
from proveflow.discover.readers import normalize_project_key
from proveflow.report.models import SkippedServer, SkipReason

OUT_OF_PROJECT_DETAIL = (
    "Claude Code local-scope entry for a different project path; Claude Code uses it only "
    "when run in that project. Scan that project (--project) to analyze it."
)
NO_PROJECT_KEY_DETAIL = "Claude Code local-scope entry without a project path"


class ProfileMember(FrozenModel):
    """``key`` is unique within the profile (name, plus scope when names collide)."""

    key: str
    spec: ServerSpec


class Profile(FrozenModel):
    id: str
    client: ClientKind
    members: tuple[ProfileMember, ...] = ()
    shadowed: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


def _found(configs: list[ClientConfig], kind: ClientKind) -> list[ClientConfig]:
    return [c for c in configs if c.kind is kind and c.status is ConfigStatus.FOUND]


def _keep_all(specs: list[ServerSpec]) -> tuple[ProfileMember, ...]:
    """No documented precedence: keep every entry; disambiguate duplicate names."""
    counts: dict[str, int] = {}
    for s in specs:
        counts[s.name] = counts.get(s.name, 0) + 1
    members = [
        ProfileMember(key=s.name if counts[s.name] == 1 else f"{s.name} [{s.scope}]", spec=s)
        for s in specs
    ]
    return tuple(sorted(members, key=lambda m: m.key))


def _skip(spec: ServerSpec, kind: ClientKind, reason: SkipReason, detail: str) -> SkippedServer:
    return SkippedServer(
        server_ref=spec.name,
        client=kind,
        scope=spec.scope,
        source_file=spec.source_file,
        project=spec.project,
        reason=reason,
        detail=detail,
    )


def _claude_code_profile(
    configs: list[ClientConfig], host: HostEnv, project: Path
) -> tuple[Profile | None, list[SkippedServer]]:
    """Precedence local > project > user; the whole entry from the highest source is
    used, fields never merged (official rule quoted in CLIENT_CONFIGS.md §2).

    Returns the profile and every Claude Code server left out of it (other projects'
    local entries, shadowed names), so none disappears silently (THREAT_MODEL T16)."""
    kind = ClientKind.CLAUDE_CODE
    found = _found(configs, kind)
    want = normalize_project_key(str(project), host)
    skipped: list[SkippedServer] = []
    local: list[ClientConfig] = []
    for c in found:
        if c.scope is not ConfigScope.LOCAL:
            continue
        if c.project is not None and normalize_project_key(c.project, host) == want:
            local.append(c)
            continue
        detail = OUT_OF_PROJECT_DETAIL if c.project is not None else NO_PROJECT_KEY_DETAIL
        skipped.extend(_skip(s, kind, SkipReason.OUT_OF_PROJECT, detail) for s in c.servers)
    project_cfgs = [c for c in found if c.scope is ConfigScope.PROJECT]
    user = [c for c in found if c.scope is ConfigScope.USER]
    chosen: dict[str, ServerSpec] = {}
    shadowed: list[str] = []
    for group in (local, project_cfgs, user):
        for cfg in group:
            for spec in cfg.servers:
                if spec.name in chosen:
                    winner = chosen[spec.name].scope
                    shadowed.append(f"{spec.name} [{spec.scope}] shadowed by {winner}")
                    skipped.append(
                        _skip(
                            spec,
                            kind,
                            SkipReason.SHADOWED,
                            f"shadowed by the {winner} entry of the same name "
                            "(Claude Code precedence: local > project > user)",
                        )
                    )
                else:
                    chosen[spec.name] = spec
    if not chosen:
        return None, skipped
    members = tuple(ProfileMember(key=n, spec=chosen[n]) for n in sorted(chosen))
    profile = Profile(
        id=f"claude_code@{project}",
        client=kind,
        members=members,
        shadowed=tuple(sorted(shadowed)),
    )
    return profile, skipped


def build_profiles(configs: list[ClientConfig], host: HostEnv, project: Path) -> list[Profile]:
    return partition_profiles(configs, host, project)[0]


def canonical_path(path: Path) -> str:
    """The FILE a path names, for comparing two configs: symlinks and junctions followed
    (``os.path.realpath``), and case folded where the OS's paths are case-insensitive
    (``os.path.normcase``: Windows; identity on POSIX)."""
    return os.path.normcase(os.path.realpath(path))


@dataclass(frozen=True)
class Collapse:
    """Two configs of the SAME client that read the same key of the same file: ``dropped`` was
    read once, as ``kept``."""

    kept: ClientConfig
    dropped: ClientConfig
    shared: str  # the canonical path they share


def _read_key(c: ClientConfig) -> tuple[ClientKind, str, str | None]:
    """Same client, same file, same key inside it. Claude Code's local scope reads
    ``projects["<path>"].mcpServers`` of the file its user scope also reads, so its project key
    is part of the identity: user and local are NOT the same read."""
    if c.path is None:
        raise ValueError("a config without a path has no file to compare")
    return (c.kind, canonical_path(c.path), c.project if c.scope is ConfigScope.LOCAL else None)


def collapse_same_file(configs: list[ClientConfig]) -> tuple[list[ClientConfig], list[Collapse]]:
    """Phase 9 fix (measured defect, docs/BACKLOG.md): when the project directory IS the home
    directory, Cursor's user and project scope name ONE file; keeping both counted every server
    twice (4 entries, 16 flows where the file held 2 servers and 3 flows). Configs of the SAME
    client kind that read the same key of the same file are read ONCE (the first, in discovery
    order, is kept) and every collapse is returned so the report can SAY it. Different client
    kinds are never collapsed: two clients reading one file are two agents."""
    seen: dict[tuple[ClientKind, str, str | None], ClientConfig] = {}
    kept: list[ClientConfig] = []
    collapsed: list[Collapse] = []
    for c in configs:
        if c.status is ConfigStatus.FOUND and c.path is not None:
            key = _read_key(c)
            if key in seen:
                collapsed.append(Collapse(seen[key], c, key[1]))
                continue
            seen[key] = c
        kept.append(c)
    return kept, collapsed


def collapse_note(c: Collapse) -> str:
    """The profile note that SAYS a collapse happened: which config was kept, which was
    collapsed into it, and the file they share."""
    kind = c.kept.kind.value
    return (f"{kind} {c.dropped.scope.value} config {c.dropped.path} is the same file as {kind} "
            f"{c.kept.scope.value} config {c.kept.path} ({c.shared}): read once, as the "
            f"{c.kept.scope.value} entry; the {c.dropped.scope.value} entry was collapsed into "
            "it")  # fmt: skip


def _with_collapse_notes(profiles: list[Profile], collapses: list[Collapse]) -> list[Profile]:
    out = []
    for p in profiles:
        notes = [collapse_note(c) for c in collapses if c.kept.kind is p.client]
        out.append(p.model_copy(update={"notes": (*p.notes, *notes)}) if notes else p)
    return out


def partition_profiles(
    configs: list[ClientConfig], host: HostEnv, project: Path
) -> tuple[list[Profile], list[SkippedServer]]:
    """Profiles plus every discovered server that is in none of them, with the reason.
    Configs of one client that are the same file are read once (``collapse_same_file``), and
    the profile's notes say so."""
    configs, collapses = collapse_same_file(configs)
    profiles: list[Profile] = []

    for cfg in _found(configs, ClientKind.CLAUDE_DESKTOP):
        if cfg.servers:
            profiles.append(
                Profile(id="claude_desktop", client=cfg.kind, members=_keep_all(list(cfg.servers)))
            )

    cc, skipped = _claude_code_profile(configs, host, project)
    if cc is not None:
        profiles.append(cc)

    for kind, name in ((ClientKind.CURSOR, "cursor"), (ClientKind.VSCODE, "vscode")):
        specs = [s for c in _found(configs, kind) for s in c.servers]
        if specs:
            profiles.append(
                Profile(
                    id=f"{name}@{project}",
                    client=kind,
                    members=_keep_all(specs),
                    notes=(
                        "precedence between scopes not documented; all entries kept, "
                        "except where two scopes name the same file (reported as a collapse)",
                    )
                    if kind is ClientKind.CURSOR
                    else (),
                )
            )

    # Windsurf: one profile per file (relationship between new and legacy files is
    # not documented, so they are not merged).
    for kind, name in ((ClientKind.WINDSURF, "windsurf"), (ClientKind.EXPLICIT_FILE, "explicit")):
        for cfg in _found(configs, kind):
            if cfg.servers:
                profiles.append(
                    Profile(
                        id=f"{name}:{cfg.path}", client=kind, members=_keep_all(list(cfg.servers))
                    )
                )

    skipped.sort(key=lambda s: (s.client, str(s.source_file), s.scope, s.server_ref, s.reason))
    profiles = _with_collapse_notes(profiles, collapses)
    return sorted(profiles, key=lambda p: p.id), skipped
