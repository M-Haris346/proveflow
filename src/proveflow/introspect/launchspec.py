"""LaunchSpec: the ONLY place raw launch values (command, args, env) live. Security-critical.

Design (docs/REDACTION.md, THREAT_MODEL T2/T12):
- Plain class, not pydantic; ``__slots__`` only (``vars()`` fails); repr/str/format show
  the server name and env KEYS, never values; pickle / copy / deepcopy raise.
- Built only by ``build_launch_spec``, which re-reads the config file and requires the
  re-read entry to redact to exactly the discovered ``ServerSpec`` (TOCTOU guard: a config
  edited after ``discover`` is never launched with values the user did not see).
- Used as a context manager; ``wipe()`` drops every reference on exit.

Honest limit: Python cannot stop *deliberate* attribute access or zero string memory. This
type prevents *accidental* exposure (repr/str/f-strings, logging, pickle, copy, JSON,
pydantic dumps, traceback locals).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from types import TracebackType
from typing import Any, NoReturn

from proveflow.core.client import ConfigStatus, ServerSpec, TransportKind
from proveflow.discover._common import EntryError, parse_entry, scalar_to_str
from proveflow.discover._io import load_json_config
from proveflow.discover.redact_rules import raw_secret_segments

MIN_SCRUB_LEN = 6


class LaunchSpecError(RuntimeError):
    """The server cannot be launched safely. Message never contains values."""


class ConfigChangedError(LaunchSpecError):
    """The config entry no longer matches what discover showed."""


class LaunchSpec:
    __slots__ = ("_args", "_command", "_env", "_server", "_wiped")

    def __init__(
        self, server: str, command: str, args: Sequence[str], env: Mapping[str, str]
    ) -> None:
        self._server = server
        self._command = command
        self._args = tuple(args)
        self._env = dict(env)
        self._wiped = False

    # --- never expose values -------------------------------------------------------
    def __repr__(self) -> str:
        keys = sorted(self._env) if not self._wiped else []
        return f"LaunchSpec(server={self._server!r}, env_keys={keys}, <values hidden>)"

    __str__ = __repr__

    def __format__(self, spec: str) -> str:
        return repr(self)

    def _refuse(self, *_: Any) -> NoReturn:
        raise TypeError("LaunchSpec holds raw secrets and cannot be pickled or copied")

    __reduce__ = _refuse
    __reduce_ex__ = _refuse
    __getstate__ = _refuse
    __copy__ = _refuse
    __deepcopy__ = _refuse

    # --- access (launcher only) ------------------------------------------------------
    def _check(self) -> None:
        if self._wiped:
            raise LaunchSpecError("LaunchSpec already wiped")

    @property
    def server(self) -> str:
        return self._server

    @property
    def command(self) -> str:
        self._check()
        return self._command

    @property
    def args(self) -> tuple[str, ...]:
        self._check()
        return self._args

    @property
    def env(self) -> dict[str, str]:
        self._check()
        return dict(self._env)

    def secret_values(self) -> list[str]:
        """Raw values that must be scrubbed from anything the server sends back."""
        self._check()
        values = list(self._env.values())
        values += raw_secret_segments(self._args)
        values += raw_secret_segments([self._command])
        unique = {v for v in values if len(v) >= MIN_SCRUB_LEN}
        return sorted(unique, key=len, reverse=True)

    def wipe(self) -> None:
        self._command = ""
        self._args = ()
        self._env = {}
        self._wiped = True

    def __enter__(self) -> LaunchSpec:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.wipe()


def _find_entry(spec: ServerSpec) -> Mapping[str, Any]:
    loaded = load_json_config(spec.source_file)
    if loaded.status is not ConfigStatus.FOUND or loaded.data is None:
        raise ConfigChangedError(f"config for {spec.name!r} is no longer readable")
    data: Mapping[str, Any] = loaded.data
    if spec.project is not None and spec.scope == "local":
        projects = data.get("projects")
        entry = projects.get(spec.project) if isinstance(projects, dict) else None
        mapping = entry.get("mcpServers") if isinstance(entry, dict) else None
        maps = [mapping]
    else:
        maps = [data.get("mcpServers"), data.get("servers")]
    for mapping in maps:
        if isinstance(mapping, dict) and isinstance(mapping.get(spec.name), dict):
            found: Mapping[str, Any] = mapping[spec.name]
            return found
    raise ConfigChangedError(f"server {spec.name!r} no longer present in its config file")


def build_launch_spec(spec: ServerSpec) -> LaunchSpec:
    """Re-read the config and build a LaunchSpec, only if it matches ``spec`` exactly."""
    if spec.transport is not TransportKind.STDIO or spec.command is None:
        raise LaunchSpecError(f"server {spec.name!r} is not a stdio server")
    if spec.variables:
        raise LaunchSpecError(f"server {spec.name!r} references unresolved variables")
    entry = _find_entry(spec)
    try:
        candidates = [
            parse_entry(
                spec.name,
                entry,
                url_keys=keys,
                source_file=spec.source_file,
                scope=spec.scope,
                project=spec.project,
            )
            for keys in (("url",), ("serverUrl", "url"))
        ]
    except EntryError:
        raise ConfigChangedError(f"server {spec.name!r} entry is now malformed") from None
    # `variables` depends on the client's syntax, not on the values; compare without it.
    bare = spec.model_copy(update={"variables": ()})
    if bare not in [c.model_copy(update={"variables": ()}) for c in candidates]:
        raise ConfigChangedError(f"config for {spec.name!r} changed since discover")
    env_raw = entry.get("env") or {}
    env: dict[str, str] = {}
    for key in sorted(env_raw):
        text = scalar_to_str(env_raw[key])
        if text is None:
            raise ConfigChangedError(f"server {spec.name!r} env changed since discover")
        env[key] = text
    return LaunchSpec(
        server=spec.name,
        command=str(entry["command"]),
        args=[str(a) for a in entry.get("args", [])],
        env=env,
    )
