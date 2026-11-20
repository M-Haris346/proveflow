"""``proveflow.toml``: user role overrides (highest priority, ARCHITECTURE §5.3).

```toml
[[override]]
server = "github"            # profile member key (server name)
tool = "create_issue"        # optional; omitted = the server-level pseudo tool "*"
roles = ["sink"]             # replaces heuristic roles entirely; [] = no roles
sink_severity = "remote_write"  # optional; default network_egress (worst case)

[[twin_override]]            # Phase 4: response archetype for one tool's twin
server = "github"
tool = "create_issue"
archetype = "issue_ticket"   # one of twin.archetypes.ARCHETYPES (checked by `proveflow twin`)

[[provider]]                 # Phase 5: an OpenAI-compatible chat-completions endpoint
name = "groq"
base_url = "https://api.groq.com/openai/v1"
model = "llama-3.3-70b-versatile"
api_key_env = "GROQ_API_KEY" # the NAME of an env var; the key itself is never in this file
send_seed = true             # only where the provider documents `seed` (docs/PROVIDERS.md)
```
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import Field, ValidationError, field_validator

from proveflow.core._base import FrozenModel
from proveflow.core.tools import SinkSeverity, ToolRole


class ConfigError(ValueError):
    """proveflow.toml is invalid. Message carries locations only, never values."""


class RoleOverride(FrozenModel):
    server: str
    tool: str | None = None
    roles: tuple[ToolRole, ...]
    sink_severity: SinkSeverity | None = None


class TwinOverride(FrozenModel):
    server: str
    tool: str
    archetype: str


LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


class ProviderConfig(FrozenModel):
    """One OpenAI-compatible provider. There is no field for the key: ``api_key_env`` names
    the environment variable that holds it, read at call time (runner.llm). Plain ``http://``
    is accepted only for a loopback host (a local Ollama), so a key never crosses a network
    unencrypted."""

    name: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,31}$")
    base_url: str
    model: str = Field(min_length=1, max_length=200)
    api_key_env: str = Field(pattern=r"^[A-Z_][A-Z0-9_]{0,63}$")
    send_seed: bool = False

    @field_validator("base_url")
    @classmethod
    def _transport_safe(cls, value: str) -> str:
        parts = urlsplit(value)
        if parts.scheme == "https" and parts.hostname:
            return value
        if parts.scheme == "http" and (parts.hostname or "") in LOOPBACK_HOSTS:
            return value
        raise ValueError("base_url must be https://, or http:// to a loopback host only")


class ProveflowConfig(FrozenModel):
    override: tuple[RoleOverride, ...] = Field(default_factory=tuple)
    twin_override: tuple[TwinOverride, ...] = Field(default_factory=tuple)
    provider: tuple[ProviderConfig, ...] = Field(default_factory=tuple)


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
