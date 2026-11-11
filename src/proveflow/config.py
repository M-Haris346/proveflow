"""``proveflow.toml``: user role overrides (highest priority, ARCHITECTURE §5.3).

```toml
[[override]]
server = "github"            # profile member key (server name)
tool = "create_issue"        # optional; omitted = the server-level pseudo tool "*"
roles = ["sink"]             # replaces heuristic roles entirely; [] = no roles
sink_severity = "remote_write"  # optional; default network_egress (worst case)
```
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from pydantic import Field, ValidationError

from proveflow.core._base import FrozenModel
from proveflow.core.tools import SinkSeverity, ToolRole


class ConfigError(ValueError):
    """proveflow.toml is invalid. Message carries locations only, never values."""


class RoleOverride(FrozenModel):
    server: str
    tool: str | None = None
    roles: tuple[ToolRole, ...]
    sink_severity: SinkSeverity | None = None


class ProveflowConfig(FrozenModel):
    override: tuple[RoleOverride, ...] = Field(default_factory=tuple)


def load_config(path: Path) -> ProveflowConfig:
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    except OSError as exc:
        raise ConfigError(f"{path}: cannot read ({type(exc).__name__})") from None
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: invalid TOML: {exc}") from None
    try:
        return ProveflowConfig.model_validate(data)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}"
            for err in exc.errors(include_input=False, include_url=False)
        )
        raise ConfigError(f"{path}: {problems}") from None
