"""Agent profiles: the set of servers one agent is actually connected to.

Flows only exist inside a profile — a source in Claude Desktop and a sink in Cursor
share no agent. proveflow over-approximates: every configured server is treated as
connected (client-side approval / disabled flags are not modeled; they are not in
docs/CLIENT_CONFIGS.md).
"""

from __future__ import annotations

from pathlib import Path

from proveflow.core._base import FrozenModel
from proveflow.core.client import ClientConfig, ClientKind, ConfigScope, ConfigStatus, ServerSpec
from proveflow.discover.hostenv import HostEnv
from proveflow.discover.readers import normalize_project_key


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


def _claude_code_profile(
    configs: list[ClientConfig], host: HostEnv, project: Path
) -> Profile | None:
    """Precedence local > project > user; the whole entry from the highest source is
    used, fields never merged (official rule quoted in CLIENT_CONFIGS.md §2)."""
    found = _found(configs, ClientKind.CLAUDE_CODE)
    want = normalize_project_key(str(project), host)
    local = [
        c
        for c in found
        if c.scope is ConfigScope.LOCAL
        and c.project is not None
        and normalize_project_key(c.project, host) == want
    ]
    project_cfgs = [c for c in found if c.scope is ConfigScope.PROJECT]
    user = [c for c in found if c.scope is ConfigScope.USER]
    chosen: dict[str, ServerSpec] = {}
    shadowed: list[str] = []
    for group in (local, project_cfgs, user):
        for cfg in group:
            for spec in cfg.servers:
                if spec.name in chosen:
                    shadowed.append(
                        f"{spec.name} [{spec.scope}] shadowed by {chosen[spec.name].scope}"
                    )
                else:
                    chosen[spec.name] = spec
    if not chosen:
        return None
    members = tuple(ProfileMember(key=n, spec=chosen[n]) for n in sorted(chosen))
    return Profile(
        id=f"claude_code@{project}",
        client=ClientKind.CLAUDE_CODE,
        members=members,
        shadowed=tuple(sorted(shadowed)),
    )


def build_profiles(configs: list[ClientConfig], host: HostEnv, project: Path) -> list[Profile]:
    profiles: list[Profile] = []

    for cfg in _found(configs, ClientKind.CLAUDE_DESKTOP):
        if cfg.servers:
            profiles.append(
                Profile(id="claude_desktop", client=cfg.kind, members=_keep_all(list(cfg.servers)))
            )

    cc = _claude_code_profile(configs, host, project)
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
                    notes=("precedence between scopes not documented; all entries kept",)
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

    return sorted(profiles, key=lambda p: p.id)
