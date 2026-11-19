"""F7: redaction in the consent prompt survives hard wrapping at a narrow width
(tests/narrowchecks.py; the one deliberate opt-out from the pinned render width)."""

from __future__ import annotations

from pathlib import Path

import pytest

from narrowchecks import assert_redaction_survives_narrow_wrap


def test_redaction_survives_a_hard_wrapped_consent_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert_redaction_survives_narrow_wrap(tmp_path, monkeypatch)
