"""Typed domain models used at every proveflow boundary.

The client-config models (``proveflow.core.client``: ``ServerSpec`` & co.) are loaded
lazily on first attribute access, so importing a sibling module such as
``proveflow.core.attacks`` does not load them. The proxy's import guard (ADR-006) relies on
this: ``import proveflow.proxy`` must leave ``proveflow.core.client`` out of ``sys.modules``.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

from proveflow.core.attacks import (
    ActionGoal,
    Attack,
    Carrier,
    ExfilGoal,
    Goal,
    HijackGoal,
    Payload,
)
from proveflow.core.flows import Flow, FlowClass, FlowVerdictKind, ToolRef
from proveflow.core.mitigations import Mitigation, MitigationKind
from proveflow.core.redact import RedactedText, RedactedValue
from proveflow.core.tools import (
    Granularity,
    RoleEvidence,
    RoleSource,
    SinkSeverity,
    ToolRole,
    ToolSpec,
)
from proveflow.core.trials import RuleHit, RunMeta, Trial, Verdict

if TYPE_CHECKING:
    from proveflow.core.client import (
        ClientConfig,
        ClientKind,
        ConfigScope,
        ConfigStatus,
        ServerSpec,
        TransportKind,
    )

_LAZY_CLIENT = frozenset(
    {"ClientConfig", "ClientKind", "ConfigScope", "ConfigStatus", "ServerSpec", "TransportKind"}
)


def __getattr__(name: str) -> Any:
    if name in _LAZY_CLIENT:
        return getattr(importlib.import_module("proveflow.core.client"), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "ActionGoal",
    "Attack",
    "Carrier",
    "ClientConfig",
    "ClientKind",
    "ConfigScope",
    "ConfigStatus",
    "ExfilGoal",
    "Flow",
    "FlowClass",
    "FlowVerdictKind",
    "Goal",
    "Granularity",
    "HijackGoal",
    "Mitigation",
    "MitigationKind",
    "Payload",
    "RedactedText",
    "RedactedValue",
    "RoleEvidence",
    "RoleSource",
    "RuleHit",
    "RunMeta",
    "ServerSpec",
    "SinkSeverity",
    "ToolRef",
    "ToolRole",
    "ToolSpec",
    "TransportKind",
    "Trial",
    "Verdict",
]
