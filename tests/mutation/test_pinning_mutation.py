"""Mutation: make the exact-version check accept anything -> the named @latest check fails."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from proveflow.core.client import ServerSpec, TransportKind
from proveflow.core.redact import RedactedText
from proveflow.flows import pinning


def assert_latest_flagged() -> None:
    """Named check: `npx -y pkg@latest` must be reported unpinned."""
    spec = ServerSpec(
        name="s",
        transport=TransportKind.STDIO,
        command=RedactedText.plain("npx"),
        args=(RedactedText.plain("-y"), RedactedText.plain("@playwright/mcp@latest")),
        source_file=Path("C:/x.json"),
    )
    result = pinning.check_pinning(spec)
    assert result is not None
    assert result.status == "unpinned", "@latest was accepted as a pin"


def test_latest_flagged() -> None:
    assert_latest_flagged()


def test_permissive_exact_version_check_makes_named_check_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pinning, "_SEMVER", re.compile(r".*"))
    with pytest.raises(AssertionError, match="accepted as a pin"):
        assert_latest_flagged()
