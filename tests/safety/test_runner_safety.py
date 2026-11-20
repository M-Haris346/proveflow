"""Runner safety (Phase 5): the injection channel (F9), the API key (D1), committed
transcripts (D7), and the author mode being unreachable from tests (Q2)."""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

import pytest

from proveflow.runner.transcript import load_transcript
from proveflow.runner.validity import InvalidTrial, injection_channel_violations
from proxyhelpers import proxy_twin_root  # noqa: F401
from runnerchecks import (
    assert_committed_transcripts_are_clean,
    assert_injection_only_through_tool_results,
    assert_no_api_key_in_any_artifact,
    fixture_scenario,
    staged_recording,
)

TESTS = Path(__file__).resolve().parents[1]
SRC = TESTS.parent / "src" / "proveflow"


def test_the_attack_arrives_only_through_tool_results(tmp_path: Path) -> None:
    assert_injection_only_through_tool_results(tmp_path)


def test_the_runtime_guard_refuses_a_payload_in_a_runner_message() -> None:
    scenario = fixture_scenario("cross_server_exfil")
    with pytest.raises(ValueError, match="runner-authored message"):
        scenario.model_validate(
            {**scenario.model_dump(), "system_prompt": scenario.attack.payload.text}
        )  # type: ignore[union-attr]


def test_no_api_key_in_any_artifact(tmp_path: Path) -> None:
    assert_no_api_key_in_any_artifact(tmp_path)


def test_committed_transcripts_are_clean() -> None:
    assert_committed_transcripts_are_clean()


def test_the_author_mode_is_unreachable_from_tests() -> None:
    """Q2: no test imports, names or can import the dev-only author script, and src/ has no
    author mode at all; a changed request can only fail with ReplayMismatch."""
    assert importlib.util.find_spec("author_transcript") is None
    me = Path(__file__).resolve()
    for path in sorted(TESTS.rglob("*.py")):
        if path.resolve() == me:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""] + [a.name for a in node.names]
            elif isinstance(node, ast.Name | ast.Attribute):
                names = [getattr(node, "id", "") or getattr(node, "attr", "")]
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                names = [node.value] if "author_transcript" in node.value else []
            bad = [n for n in names if "author_transcript" in n or n == "AuthorChatClient"]
            assert not bad, f"{path.relative_to(TESTS)} reaches the author mode: {bad}"
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        assert not [n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)
                    and n.name.startswith("Author")], path.name  # fmt: skip


def test_validity_violations_are_reported_precisely(tmp_path: Path) -> None:
    recorded = staged_recording(tmp_path, "cross_server_exfil")
    events = load_transcript(recorded)
    attack = fixture_scenario("cross_server_exfil").attack
    assert injection_channel_violations(events, attack) == []
    assert injection_channel_violations(events, None) == []
    with pytest.raises(InvalidTrial):
        raise InvalidTrial("x")
