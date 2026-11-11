"""Typed domain models used at every proveflow boundary."""

from proveflow.core.attacks import (
    ActionGoal,
    Attack,
    Carrier,
    ExfilGoal,
    Goal,
    HijackGoal,
    Payload,
)
from proveflow.core.client import (
    ClientConfig,
    ClientKind,
    ConfigScope,
    ConfigStatus,
    ServerSpec,
    TransportKind,
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
