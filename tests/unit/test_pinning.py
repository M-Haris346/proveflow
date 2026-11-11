"""PF-UNPINNED: documented npx / uvx / pipx package forms (docs/PINNING.md)."""

from __future__ import annotations

from pathlib import Path

import pytest

from proveflow.core.client import ConfigScope, ServerSpec, TransportKind
from proveflow.core.redact import RedactedText, RedactedValue
from proveflow.flows.pinning import check_pinning


def spec(command: str, *args: str | RedactedText) -> ServerSpec:
    return ServerSpec(
        name="srv",
        transport=TransportKind.STDIO,
        command=RedactedText.plain(command),
        args=tuple(a if isinstance(a, RedactedText) else RedactedText.plain(a) for a in args),
        source_file=Path("C:/x/config.json"),
        scope=ConfigScope.USER,
    )


CASES = [
    # npx
    (
        ("npx", "-y", "@modelcontextprotocol/server-github"),
        "unpinned",
        "@modelcontextprotocol/server-github",
    ),
    (("npx", "-y", "@playwright/mcp@latest"), "unpinned", "@playwright/mcp@latest"),
    (("npx", "-y", "@playwright/mcp@0.0.41"), "pinned", None),
    (("npx", "--yes", "some-pkg@1.2.3-beta.1+build.5"), "pinned", None),
    (("npx", "-y", "some-pkg@^1.2.0"), "unpinned", "some-pkg@^1.2.0"),
    (("npx", "-y", "some-pkg@next"), "unpinned", "some-pkg@next"),
    (("npx", "-y", "some-pkg@01.2.3"), "unpinned", "some-pkg@01.2.3"),  # leading zero: not SemVer
    (("npx", "-p", "a@1.0.0", "-p", "b", "cmd"), "unpinned", "b"),
    (("npx", "--package=a@1.0.0", "cmd"), "pinned", None),
    (("npx", "--", "pkg@2.0.0", "--flag"), "pinned", None),
    (("npx", "-y", "./local-folder"), "unknown", None),
    (("npx", "-y", "alias@npm:real@1.0.0"), "unknown", None),
    (("npx", "--weird-option", "pkg"), "unknown", None),
    (("C:\\Program Files\\nodejs\\npx.cmd", "-y", "pkg"), "unpinned", "pkg"),
    (("npx", "-y", "github-mcp"), "unpinned", "github-mcp"),  # registry name, not a git spec
    (("npx", "-y", "gitlab-mcp@1.0.0"), "pinned", None),
    (("npx", "-y", "git+ssh://git@github.com/npm/cli#v6.0.0"), "unknown", None),
    (("npx", "-y", "git@github.com:npm/cli.git"), "unknown", None),
    (("npx", "-y", "github:npm/cli#HEAD"), "unknown", None),
    (("npx", "-y", "npm/cli#c12ea07"), "unknown", None),
    (("npx", "-y", "https://registry.npmjs.org/semver/-/semver-1.0.0.tgz"), "unknown", None),
    # uvx
    (("uvx", "--from", "git+https://github.com/org/repo", "cmd"), "unknown", None),
    (("uvx", "--from", "pkg @ https://example.invalid/pkg.whl", "cmd"), "unknown", None),
    (("uvx", "git+https://github.com/org/repo"), "unknown", None),
    (("uvx", "gitlab-tools"), "unpinned", "gitlab-tools"),
    (("uvx", "mcp-server-fetch"), "unpinned", "mcp-server-fetch"),
    (("uvx", "mcp-server-fetch@latest"), "unpinned", "mcp-server-fetch@latest"),
    (("uvx", "mcp-server-fetch@2025.4.7"), "pinned", None),
    (("uvx", "--from", "mcp-server-git==2025.1.14", "mcp-server-git"), "pinned", None),
    (("uvx", "--from", "pkg>1,<2", "cmd"), "unpinned", "pkg>1,<2"),
    (("uvx", "--from", "pkg==1.*", "cmd"), "unpinned", "pkg==1.*"),
    (("uvx", "--from=pkg===1.0", "cmd"), "pinned", None),
    (("uvx", "--python", "3.12", "pkg"), "unknown", None),
    # pipx
    (("pipx", "run", "some-app"), "unpinned", "some-app"),
    (("pipx", "run", "--spec", "pkg==4.6.2", "app"), "pinned", None),
    (("pipx", "run", "--spec", "pkg", "app"), "unpinned", "pkg"),
]


@pytest.mark.parametrize(("argv", "status", "package"), CASES, ids=lambda v: str(v))
def test_documented_forms(argv: tuple[str, ...], status: str, package: str | None) -> None:
    result = check_pinning(spec(*argv))
    assert result is not None
    assert result.status == status, result.reason
    if package is not None:
        assert result.package == package


@pytest.mark.parametrize(
    "argv", [("node", "server.js"), ("python", "-m", "srv"), ("pipx", "install", "x")]
)
def test_not_applicable(argv: tuple[str, ...]) -> None:
    assert check_pinning(spec(*argv)) is None


def test_remote_server_not_applicable() -> None:
    remote = ServerSpec(
        name="r", transport=TransportKind.HTTP, url=RedactedText.plain("https://x.example"),
        source_file=Path("C:/x.json"),
    )  # fmt: skip
    assert check_pinning(remote) is None


def test_redacted_other_arg_does_not_hide_package() -> None:
    secret = RedactedText(parts=("--api-key=", RedactedValue.from_secret("PLANTEDpin0001")))
    result = check_pinning(spec("npx", "-y", "pkg@1.0.0", secret))
    assert result is not None
    assert result.status == "pinned"


def test_redacted_package_is_unknown() -> None:
    hidden = RedactedText(
        parts=(RedactedValue.from_secret("PLANTEDx9Kq2mZ7vR4tY8wB3nL6pD1sF5hJ0"),)
    )
    result = check_pinning(spec("npx", "-y", hidden))
    assert result is not None
    assert result.status == "unknown"
    assert result.package is None
