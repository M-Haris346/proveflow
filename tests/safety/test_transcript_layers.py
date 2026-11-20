"""Two INDEPENDENT layers guard every committed transcript (Phase 5, R1/R2):

* D7, the SHAPE scan (``runnerchecks.transcript_problems``): redaction-rule spans beyond the
  trial's own needles, T4, provider prefixes, paths and machine names, over every string at
  every JSON path EXCEPT the exact set STRUCTURAL_PATHS (chain hashes and the provider's
  completion id ``llm_response.body.id``).
* the EXACT-KEY check (``runnerchecks.exact_key_hits``): the real key's value, in any of the
  matcher's 10 encodings, anywhere in the file's text. It knows nothing about JSON paths.

D7 catches SHAPES; the exact-key check catches THE KEY. Excluding a path from the first does
not touch the second: a key placed at an excluded path is still caught (named check below,
and its mutation in tests/mutation/test_transcript_layers_mutation.py).

R2: a transcript from a real provider run is EVIDENCE, committed under
evidence/provider-runs/, never a replay fixture: its cassettes hold absolute interpreter and
twin paths and are not committed, so its check is the hash chain + D7 only and never
resolves cassette references. (The directory is not "runs/": .gitignore ignores every
"runs/" directory as uncommitted runtime output.)
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from runnerchecks import (
    EVENT_KINDS,
    EVIDENCE,
    FIXTURES,
    LIST,
    STRUCTURAL_PATHS,
    _fixture_dir,
    assert_error_body_stays_scanned,
    assert_evidence_runs_are_clean,
    assert_exact_key_check_sees_past_the_path_exclusion,
    committed_transcripts,
    evidence_problems,
)

EXPECTED_STRUCTURAL_PATHS = (
    {(kind, "sha256") for kind in EVENT_KINDS}
    | {(kind, "prev_sha256") for kind in EVENT_KINDS}
    | {("trial_end", "cassettes", LIST, "final_sha256"), ("llm_response", "body", "id")}
)


def test_structural_paths_are_an_exact_set() -> None:
    """Adding a path is a visible diff here. A new path needs a ruling (R1)."""
    assert STRUCTURAL_PATHS == EXPECTED_STRUCTURAL_PATHS
    assert len(STRUCTURAL_PATHS) == 20
    assert ("llm_response", "body", "error", "message") not in STRUCTURAL_PATHS


def test_the_exact_key_check_sees_past_the_path_exclusion(tmp_path: Path) -> None:
    assert_exact_key_check_sees_past_the_path_exclusion(tmp_path)


def test_an_error_body_stays_scanned(tmp_path: Path) -> None:
    assert_error_body_stays_scanned(tmp_path)


def test_committed_evidence_runs_are_clean() -> None:
    """Every committed real-run transcript passes chain + D7 (the call raises otherwise)."""
    # Exactly 0 today: no real provider run is committed yet. This becomes 1 when the first
    # manual run lands (and closes Phase 5); the change is deliberate and must be looked at.
    assert assert_evidence_runs_are_clean() == 0
    assert (EVIDENCE / "README.md").is_file()


def _evidence_copy(root: Path, *, readme: bool = True) -> Path:
    run = root / "groq-example-model-2026-01-01"
    run.mkdir(parents=True)
    for name in ("transcript.jsonl", "scenario.json"):
        shutil.copyfile(FIXTURES / "clean_utility" / name, run / name)
    if readme:
        (run / "README.md").write_text("A record of one real run, not a replay fixture.\n",
                                       encoding="utf-8")  # fmt: skip
    return run / "transcript.jsonl"


def test_the_evidence_check_is_chain_and_d7_only(tmp_path: Path) -> None:
    """A clean transcript with no cassettes next to it passes: references are never resolved.
    A broken chain or a missing README fails."""
    good = _evidence_copy(tmp_path / "a")
    assert evidence_problems(good) == []
    assert assert_evidence_runs_are_clean(tmp_path / "a") == 1
    no_readme = _evidence_copy(tmp_path / "b", readme=False)
    assert any("README" in p for p in evidence_problems(no_readme))
    broken = _evidence_copy(tmp_path / "c")
    lines = broken.read_bytes().splitlines()
    broken.write_bytes(b"\n".join(lines[:1] + lines[2:]) + b"\n")
    assert evidence_problems(broken)


def test_evidence_is_not_reachable_from_the_replay_loader() -> None:
    """R2: nobody can accidentally replay a real-run transcript."""
    fixtures, evidence = FIXTURES.resolve(), EVIDENCE.resolve()
    assert not evidence.is_relative_to(fixtures) and not fixtures.is_relative_to(evidence)
    assert not [p for p in committed_transcripts() if p.resolve().is_relative_to(evidence)]
    for name in ("../../../evidence/provider-runs/x", str(evidence), "evidence", "..", "", "a/b"):
        with pytest.raises(ValueError):
            _fixture_dir(name)
    _fixture_dir("clean_utility")
