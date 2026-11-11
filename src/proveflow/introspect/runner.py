"""Consented ``tools/list`` introspection. Imports the MCP SDK; import this module lazily.

Per server: consent -> LaunchSpec (TOCTOU-checked) -> spawn in job/process group ->
``Client(mode="auto")`` (server/discover, falls back to initialize) -> ``tools/list`` pages
-> scrub -> kill tree. Hard timeout around everything. Never ``tools/call`` (allowlist in
``transport``). Remote servers are never contacted in Phase 1.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

import anyio
from mcp import Client
from mcp_types.version import MODERN_PROTOCOL_VERSIONS

from proveflow.core.client import ConfigScope, ServerSpec, TransportKind
from proveflow.discover.redact_rules import redact_text
from proveflow.introspect.cache import ToolCache, spec_key
from proveflow.introspect.launchspec import (
    ConfigChangedError,
    LaunchSpecError,
    build_launch_spec,
)
from proveflow.introspect.scrub import Scrubber, scrub_stderr, scrub_text
from proveflow.introspect.transport import ForbiddenMethod, TransportState, proveflow_stdio
from proveflow.report.models import IntrospectionResult, IntrospectionStatus, RawTool

logger = logging.getLogger(__name__)

# The SDK's own log records could quote server traffic; keep them out of every output.
for _name in ("mcp", "mcp_types"):
    _sdk_logger = logging.getLogger(_name)
    _sdk_logger.addHandler(logging.NullHandler())
    _sdk_logger.propagate = False

PAGE_CAP = 100
DEFAULT_TIMEOUT = 20.0

Consent = Literal["yes", "no", "unavailable"]


def _leaves(exc: BaseException) -> list[BaseException]:
    if isinstance(exc, BaseExceptionGroup):
        out: list[BaseException] = []
        for sub in exc.exceptions:
            out.extend(_leaves(sub))
        return out
    return [exc]


def _describe(exc: BaseException, secrets: Sequence[str]) -> str:
    leaves = _leaves(exc)
    leaf = next((e for e in leaves if isinstance(e, ForbiddenMethod)), leaves[0])
    text = f"{type(leaf).__name__}: {leaf}"
    return str(redact_text(scrub_text(text, secrets)))[:300]


TIMEOUT_HINT = (
    "; a first run may still be downloading the package (npx/uvx/pipx fetch it on first "
    "launch) - retry with a larger --timeout"
)
PROJECT_CONSENT_DETAIL = (
    "project-scoped (repository-controlled) server: --yes does not cover it; "
    "use --yes-project or answer the interactive prompt"
)


async def introspect_one(
    spec: ServerSpec,
    *,
    timeout: float,
    parent_env: Mapping[str, str],
    untrusted_dirs: Sequence[Path] = (),
) -> IntrospectionResult:
    if spec.variables:
        return IntrospectionResult(
            status=IntrospectionStatus.UNRESOLVED_VARIABLES,
            detail="references " + ", ".join(spec.variables) + " (only the client resolves these)",
        )
    try:
        launch = build_launch_spec(spec)
    except ConfigChangedError as exc:
        return IntrospectionResult(status=IntrospectionStatus.CONFIG_CHANGED, detail=str(exc))
    except LaunchSpecError as exc:
        return IntrospectionResult(status=IntrospectionStatus.FAILED, detail=str(exc))
    with launch:
        secrets = launch.secret_values()
        state = TransportState()
        version: str | None = None
        tools: list[Any] = []
        try:
            with anyio.fail_after(timeout):
                transport = proveflow_stdio(launch, state, dict(parent_env), untrusted_dirs)
                async with Client(transport, mode="auto") as client:
                    version = client.protocol_version
                    cursor: str | None = None
                    for _ in range(PAGE_CAP):
                        page = await client.list_tools(cursor=cursor)
                        tools.extend(page.tools)
                        cursor = page.next_cursor
                        if cursor is None:
                            break
        except TimeoutError:
            return IntrospectionResult(
                status=IntrospectionStatus.TIMEOUT,
                detail=f"no tools/list answer within {timeout:g}s{TIMEOUT_HINT}",
                stderr_tail=scrub_stderr(bytes(state.stderr), secrets) or None,
            )
        except Exception as exc:
            return IntrospectionResult(
                status=IntrospectionStatus.FAILED,
                detail=_describe(exc, secrets),
                stderr_tail=scrub_stderr(bytes(state.stderr), secrets) or None,
            )
        scrubber = Scrubber(secrets)
        raw_tools = tuple(
            RawTool(
                name=scrubber.text(t.name),
                description=scrubber.text(t.description or ""),
                input_schema=scrubber.json(dict(t.input_schema or {})),
            )
            for t in tools
        )
        era: Literal["modern", "handshake"] = (
            "modern" if version in MODERN_PROTOCOL_VERSIONS else "handshake"
        )
        return IntrospectionResult(
            status=IntrospectionStatus.OK,
            protocol_version=version,
            era=era,
            tools=raw_tools,
            pattern_redactions=scrubber.pattern_redactions,
        )


def introspect_specs(
    specs: Sequence[ServerSpec],
    *,
    consent: Callable[[ServerSpec], Consent],
    timeout: float = DEFAULT_TIMEOUT,
    cache: ToolCache | None = None,
    parent_env: Mapping[str, str] | None = None,
    untrusted_dirs: Sequence[Path] = (),
) -> dict[str, IntrospectionResult]:
    """Introspect stdio servers one at a time. Keys are ``cache.spec_key(spec)``.

    ``untrusted_dirs`` (the scanned project) are never searched for executables."""
    env = dict(os.environ if parent_env is None else parent_env)
    results: dict[str, IntrospectionResult] = {}
    for spec in specs:
        key = spec_key(spec)
        if key in results or spec.transport is not TransportKind.STDIO:
            continue
        if spec.variables:
            # Never prompt for a server proveflow will not launch anyway.
            results[key] = anyio.run(_run_one, spec, timeout, env, untrusted_dirs)
            continue
        answer = consent(spec)
        if answer == "no":
            results[key] = IntrospectionResult(status=IntrospectionStatus.DECLINED)
            continue
        if answer == "unavailable":
            results[key] = IntrospectionResult(
                status=IntrospectionStatus.CONSENT_REQUIRED,
                detail=PROJECT_CONSENT_DETAIL if spec.scope is ConfigScope.PROJECT else None,
            )
            continue
        logger.info("introspecting server %s", spec.name)
        result = anyio.run(_run_one, spec, timeout, env, untrusted_dirs)
        if result.status is IntrospectionStatus.OK:
            if cache is None:
                result = result.model_copy(update={"baseline": "cache_disabled"})
            else:
                changes, first = cache.compare_and_store(key, result.tools)
                result = result.model_copy(
                    update={"changes": changes, "baseline": "first_seen" if first else "compared"}
                )
        logger.info("server %s: %s, %d tools", spec.name, result.status, len(result.tools))
        results[key] = result
    return results


async def _run_one(
    spec: ServerSpec, timeout: float, env: dict[str, str], untrusted_dirs: Sequence[Path]
) -> IntrospectionResult:
    return await introspect_one(
        spec, timeout=timeout, parent_env=env, untrusted_dirs=untrusted_dirs
    )
