"""PF-UNPINNED: stdio servers fetched at launch by npx / uvx / pipx without an exact version.

Static, no network. Only forms documented in the cited docs are parsed (docs/PINNING.md);
anything else is reported as ``unknown``, never guessed. Only plain (unredacted) argument
segments are inspected.

- npx: ``npx -- <pkg>[@<version>] [args...]``; ``-p/--package`` names the package(s)
  explicitly; a spec without a version uses npm's ``tag`` config (default ``latest``).
  Pinned = an exact SemVer 2.0.0 version.
- uvx: ``command@<version>`` (exact only), ``command@latest``, ``--from 'pkg==X'`` or a range.
- pipx: ``pipx run --spec PACKAGE==VERSION APP``; ``pipx run APP`` runs "the latest version".
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PureWindowsPath
from typing import Literal

from proveflow.core.client import ServerSpec, TransportKind

PinStatus = Literal["pinned", "unpinned", "unknown"]

# SemVer 2.0.0 rules 2, 9, 10: X.Y.Z without leading zeros, optional -pre and +build.
_SEMVER = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
# PEP 440 requirement: name[extras] then a specifier set.
_PY_REQ = re.compile(r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]*\])?\s*(?P<spec>.*)$")
_NPX_VALUE_OPTS = frozenset({"-p", "--package", "-c", "--call"})
_NPX_FLAGS = frozenset({"-y", "--yes", "--no"})
_UVX_VALUE_OPTS = frozenset({"--from", "--with"})


@dataclass(frozen=True)
class PinCheck:
    launcher: str
    package: str | None
    status: PinStatus
    reason: str


def launcher_of(spec: ServerSpec) -> str | None:
    if spec.transport is not TransportKind.STDIO or spec.command is None:
        return None
    if spec.command.is_redacted:
        return None
    name = PureWindowsPath(str(spec.command)).name.lower()
    for suffix in (".cmd", ".exe", ".bat"):
        name = name.removesuffix(suffix)
    return name if name in {"npx", "uvx", "pipx"} else None


def is_exact_semver(version: str) -> bool:
    return _SEMVER.match(version) is not None


def is_floating_npm_tag(version: str) -> bool:
    """A dist-tag such as ``latest`` / ``next``: resolved at run time, never a pin."""
    return (
        not is_exact_semver(version)
        and re.fullmatch(r"[A-Za-z][A-Za-z0-9._-]*", version) is not None
    )


# npm package-spec page: git URLs (git+ssh://..., git@github.com:..., https://...git),
# the `github:` shorthand and `<user>/<project>` (both may carry `#ref`), tarball files/URLs,
# folders, and `<alias>@npm:<name>` aliases. A plain name that merely starts with "git"
# (github-mcp, gitlab-mcp) is a registry package, not a git spec.
_NPM_NON_REGISTRY_PREFIXES = (
    "git+",
    "git:",
    "git@",
    "github:",
    "http:",
    "https:",
    "file:",
    ".",
    "/",
    "~",
)


def _npm_spec(spec: str) -> tuple[PinStatus, str]:
    if spec.startswith(_NPM_NON_REGISTRY_PREFIXES) or "npm:" in spec or "#" in spec:
        return "unknown", "alias, git, tarball or folder spec (not checked)"
    body = spec[1:] if spec.startswith("@") else spec
    if "@" not in body:
        if "/" in body and not spec.startswith("@"):
            return "unknown", "looks like a <user>/<project> git spec (not checked)"
        return "unpinned", "no version: npm uses its `tag` config (default `latest`)"
    version = body.rsplit("@", 1)[1]
    if is_exact_semver(version):
        return "pinned", f"exact version {version}"
    if is_floating_npm_tag(version):
        return "unpinned", f"dist-tag @{version} resolves at run time"
    return "unpinned", f"version range @{version} (not an exact version)"


def _py_requirement(req: str) -> tuple[PinStatus, str]:
    text = req.strip()
    # VCS / URL / path requirements (git+https://..., "pkg @ https://...", ./dir) are
    # not version specifiers: report unknown rather than guess.
    if "://" in text or " @ " in text or text.startswith(("git+", ".", "/", "~")):
        return "unknown", "VCS, URL or path requirement (not checked)"
    m = _PY_REQ.match(text)
    if m is None:
        return "unknown", "unrecognized requirement"
    clauses = [c.strip() for c in m.group("spec").split(",") if c.strip()]
    if not clauses:
        return "unpinned", "no version specifier"
    if len(clauses) == 1:
        clause = clauses[0]
        if clause.startswith("===") and len(clause) > 3:
            return "pinned", f"arbitrary equality {clause}"
        if clause.startswith("==") and not clause.endswith(".*") and len(clause) > 2:
            return "pinned", f"exact version {clause}"
    return "unpinned", f"version range {', '.join(clauses)}"


_REDACTED = "\x00redacted\x00"


def _plain_args(spec: ServerSpec) -> list[str]:
    """Plain args; a redacted arg becomes a marker that is never parsed as a package."""
    return [_REDACTED if a.is_redacted else str(a) for a in spec.args]


def _check_npx(args: list[str]) -> PinCheck:
    packages: list[str] = []
    first: str | None = None
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--":
            first = args[i + 1] if i + 1 < len(args) else None
            break
        if a in ("-p", "--package"):
            if i + 1 >= len(args):
                return PinCheck("npx", None, "unknown", "-p without a value")
            packages.append(args[i + 1])
            i += 2
            continue
        if a.startswith("--package="):
            packages.append(a.split("=", 1)[1])
        elif a in _NPX_VALUE_OPTS:
            i += 2
            continue
        elif a in _NPX_FLAGS:
            pass
        elif a.startswith("-"):
            return PinCheck("npx", None, "unknown", f"unrecognized npx option {a!r}")
        else:
            first = a
            break
        i += 1
    targets = packages or ([first] if first else [])
    if not targets:
        return PinCheck("npx", None, "unknown", "no package argument found")
    for pkg in targets:
        status, reason = _npm_spec(pkg)
        if status != "pinned":
            return PinCheck("npx", pkg, status, reason)
    return PinCheck("npx", ", ".join(targets), "pinned", "exact version")


def _check_uvx(args: list[str]) -> PinCheck:
    from_value: str | None = None
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--from":
            if i + 1 >= len(args):
                return PinCheck("uvx", None, "unknown", "--from without a value")
            from_value = args[i + 1]
            i += 2
            continue
        if a.startswith("--from="):
            from_value = a.split("=", 1)[1]
        elif a in _UVX_VALUE_OPTS:
            i += 2
            continue
        elif a.startswith("-"):
            return PinCheck("uvx", None, "unknown", f"unrecognized uvx option {a!r}")
        else:
            if from_value is not None:
                status, reason = _py_requirement(from_value)
                return PinCheck("uvx", from_value, status, reason)
            if "://" in a or a.startswith(("git+", ".", "/", "~")):
                return PinCheck("uvx", a, "unknown", "VCS, URL or path command (not checked)")
            if "@" in a:
                name, version = a.rsplit("@", 1)
                if version == "latest":
                    return PinCheck("uvx", a, "unpinned", "@latest resolves at run time")
                # uv docs: "the @ syntax cannot be used for anything other than an exact version"
                return PinCheck("uvx", a, "pinned", f"exact version {version} of {name}")
            return PinCheck("uvx", a, "unpinned", "no version: resolved at launch")
        i += 1
    return PinCheck("uvx", None, "unknown", "no command argument found")


def _check_pipx(args: list[str]) -> PinCheck | None:
    if not args or args[0] != "run":
        return None
    spec_value: str | None = None
    i = 1
    while i < len(args):
        a = args[i]
        if a == "--spec":
            if i + 1 >= len(args):
                return PinCheck("pipx", None, "unknown", "--spec without a value")
            spec_value = args[i + 1]
            i += 2
            continue
        if a.startswith("--spec="):
            spec_value = a.split("=", 1)[1]
        elif a.startswith("-"):
            return PinCheck("pipx", None, "unknown", f"unrecognized pipx option {a!r}")
        else:
            if spec_value is not None:
                status, reason = _py_requirement(spec_value)
                return PinCheck("pipx", spec_value, status, reason)
            return PinCheck("pipx", a, "unpinned", "pipx run APP runs the latest version")
        i += 1
    return PinCheck("pipx", None, "unknown", "no app argument found")


def check_pinning(spec: ServerSpec) -> PinCheck | None:
    """None when the server is not launched through npx / uvx / pipx run."""
    launcher = launcher_of(spec)
    if launcher is None:
        return None
    args = _plain_args(spec)
    if launcher == "npx":
        result: PinCheck | None = _check_npx(args)
    elif launcher == "uvx":
        result = _check_uvx(args)
    else:
        result = _check_pipx(args)
    if result is not None and result.package is not None and _REDACTED in result.package:
        return PinCheck(launcher, None, "unknown", "package argument contains redacted segments")
    return result
