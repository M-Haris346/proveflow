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
    ServerSpec,
    TransportKind,
)
from proveflow.core.flows import Flow, FlowClass, FlowVerdictKind
from proveflow.core.mitigations import Mitigation, MitigationKind
from proveflow.core.redact import RedactedValue
from proveflow.core.tools import RoleEvidence, RoleSource, ToolRole, ToolSpec
from proveflow.core.trials import RuleHit, RunMeta, Trial, Verdict

__all__ = [
    "ActionGoal",
    "Attack",
    "Carrier",
    "ClientConfig",
    "ClientKind",
    "ConfigScope",
    "ExfilGoal",
    "Flow",
    "FlowClass",
    "FlowVerdictKind",
    "Goal",
    "HijackGoal",
    "Mitigation",
    "MitigationKind",
    "Payload",
    "RedactedValue",
    "RoleEvidence",
    "RoleSource",
    "RuleHit",
    "RunMeta",
    "ServerSpec",
    "ToolRole",
    "ToolSpec",
    "TransportKind",
    "Trial",
    "Verdict",
]
