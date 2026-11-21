"""Mutation: plant a test that imports, or runs by file name, the dev-only evidence replay
tool -> the NAMED check fails. A test tree without such a file passes."""

from __future__ import annotations

from pathlib import Path

import pytest

from runnerchecks import EVIDENCE_REPLAY_TOOL, assert_no_test_reaches_the_evidence_replay

PLANTED = {
    "import": f"import {EVIDENCE_REPLAY_TOOL}\n",
    "from-import": f"from tools import {EVIDENCE_REPLAY_TOOL}\n",
    "subprocess": "import subprocess\n"
    f"subprocess.run(['python', 'tools/{EVIDENCE_REPLAY_TOOL}' + '.py'])\n"
    f"X = 'tools/{EVIDENCE_REPLAY_TOOL}.py'\n",
}


@pytest.mark.parametrize("how", sorted(PLANTED))
def test_a_planted_reach_fails_the_named_check(tmp_path: Path, how: str) -> None:
    clean = tmp_path / "clean"
    clean.mkdir()
    (clean / "test_ok.py").write_bytes(b"def test_ok() -> None:\n    assert True\n")
    assert_no_test_reaches_the_evidence_replay(clean)
    planted = tmp_path / "planted"
    planted.mkdir()
    (planted / "test_replays.py").write_bytes(PLANTED[how].encode("utf-8"))
    with pytest.raises(AssertionError, match="reaches the evidence replay tool"):
        assert_no_test_reaches_the_evidence_replay(planted)
