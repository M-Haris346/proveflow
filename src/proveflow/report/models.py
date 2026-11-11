"""Serializable report models for ``discover`` and ``scan`` (JSON output schema)."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from proveflow.core._base import FrozenModel
from proveflow.core.client import ClientConfig, ClientKind, ServerSpec
from proveflow.core.flows import Flow
from proveflow.core.tools import ToolSpec

REPORT_SCHEMA_VERSION = 1


class IntrospectionStatus(StrEnum):
    SKIPPED_NO_LAUNCH = "skipped_no_launch"
    REMOTE_NOT_INTROSPECTED = "remote_not_introspected"
    AUTH_REQUIRED = "auth_required"

    @property
    def text(self) -> str:
        return _STATUS_TEXT[self]


_STATUS_TEXT = {
    IntrospectionStatus.SKIPPED_NO_LAUNCH: "not launched (--no-launch)",
    IntrospectionStatus.REMOTE_NOT_INTROSPECTED: (
        "remote - not introspected (Phase 1 is stdio only)"
    ),
    IntrospectionStatus.AUTH_REQUIRED: "auth required - not introspected",
}


class DiscoverReport(FrozenModel):
    schema_version: Literal[1] = 1
    proveflow_version: str
    project: str
    configs: tuple[ClientConfig, ...]


class ServerReport(FrozenModel):
    key: str
    spec: ServerSpec
    introspection: IntrospectionStatus
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
    mode: Literal["no_launch"]
    profiles: tuple[ProfileReport, ...]
    flows: tuple[Flow, ...]
    unused_overrides: tuple[str, ...] = ()
    limitations: tuple[str, ...]
