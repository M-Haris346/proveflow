"""Serializable report models for ``discover`` and ``scan`` (JSON output schema).

Nothing here may hold a raw secret: tool metadata and stderr are scrubbed before they are
put into these models (introspect/scrub.py).
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from proveflow.core._base import FrozenModel
from proveflow.core.client import ClientConfig, ClientKind, ServerSpec
from proveflow.core.flows import Flow
from proveflow.core.tools import ToolSpec

REPORT_SCHEMA_VERSION = 1


class IntrospectionStatus(StrEnum):
    OK = "ok"
    SKIPPED_NO_LAUNCH = "skipped_no_launch"
    DECLINED = "declined"
    CONSENT_REQUIRED = "consent_required"
    TIMEOUT = "timeout"
    FAILED = "failed"
    CONFIG_CHANGED = "config_changed"
    UNRESOLVED_VARIABLES = "unresolved_variables"
    REMOTE_NOT_INTROSPECTED = "remote_not_introspected"
    AUTH_REQUIRED = "auth_required"

    @property
    def text(self) -> str:
        return _STATUS_TEXT[self]


_STATUS_TEXT = {
    IntrospectionStatus.OK: "introspected (tools/list)",
    IntrospectionStatus.SKIPPED_NO_LAUNCH: "not launched (--no-launch)",
    IntrospectionStatus.DECLINED: "not launched (consent declined)",
    IntrospectionStatus.CONSENT_REQUIRED: "not launched (consent required; use --yes)",
    IntrospectionStatus.TIMEOUT: "timed out - process tree killed",
    IntrospectionStatus.FAILED: "failed - process tree killed",
    IntrospectionStatus.CONFIG_CHANGED: "not launched (config changed since discover)",
    IntrospectionStatus.UNRESOLVED_VARIABLES: (
        "not launched (config uses variables only the client can resolve)"
    ),
    IntrospectionStatus.REMOTE_NOT_INTROSPECTED: (
        "remote - not introspected (Phase 1 is stdio only)"
    ),
    IntrospectionStatus.AUTH_REQUIRED: "auth required - not introspected",
}


class RawTool(FrozenModel):
    """One tool as returned by tools/list, already scrubbed of launch secrets."""

    name: str
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)


class ToolChangeKind(StrEnum):
    ADDED = "added"
    REMOVED = "removed"
    DESCRIPTION_CHANGED = "description_changed"
    SCHEMA_CHANGED = "schema_changed"


class ToolChange(FrozenModel):
    """Difference vs the cached previous tools/list (rug-pull signal, never blocking)."""

    kind: ToolChangeKind
    tool: str


class IntrospectionResult(FrozenModel):
    status: IntrospectionStatus
    protocol_version: str | None = None
    era: Literal["modern", "handshake"] | None = None
    detail: str | None = None
    tools: tuple[RawTool, ...] = ()
    changes: tuple[ToolChange, ...] = ()
    # first_seen: no cached tools/list to compare against; compared: diffed against the
    # cache; cache_disabled: no cache dir (e.g. LOCALAPPDATA unset). None = not introspected.
    baseline: Literal["first_seen", "compared", "cache_disabled"] | None = None
    pattern_redactions: int = 0
    stderr_tail: str | None = None


class Finding(FrozenModel):
    """A non-flow static finding about one configured server (e.g. PF-UNPINNED)."""

    rule_id: str
    server: str
    source_file: Path
    status: Literal["unpinned", "unknown"]
    launcher: str
    package: str | None = None
    reason: str


class DiscoverReport(FrozenModel):
    schema_version: Literal[1] = 1
    proveflow_version: str
    project: str
    configs: tuple[ClientConfig, ...]


class ServerReport(FrozenModel):
    key: str
    spec: ServerSpec
    introspection: IntrospectionStatus
    protocol_version: str | None = None
    era: Literal["modern", "handshake"] | None = None
    detail: str | None = None
    changes: tuple[ToolChange, ...] = ()
    baseline: Literal["first_seen", "compared", "cache_disabled"] | None = None
    stderr_tail: str | None = None
    tools: tuple[ToolSpec, ...] = ()


class ProfileReport(FrozenModel):
    id: str
    client: ClientKind
    servers: tuple[ServerReport, ...]
    shadowed: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


class ScanReport(FrozenModel):
    schema_version: Literal[1] = 1
    proveflow_version: str
    project: str
    mode: Literal["introspect", "no_launch"]
    profiles: tuple[ProfileReport, ...]
    flows: tuple[Flow, ...]
    findings: tuple[Finding, ...] = ()
    unused_overrides: tuple[str, ...] = ()
    limitations: tuple[str, ...]
