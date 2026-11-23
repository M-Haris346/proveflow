"""Mutations of corpus ingest (Phase 6 step 3): each weakening makes a NAMED check fail. The
first is the share-alike gate: BIPIA's context directories no longer refused by name."""

from __future__ import annotations

import ast
import socket
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

import ingestchecks as ic
from proveflow.corpus import dedup, fetch, ingest, loaders, records


def _ok_then(check: Callable[..., None], mp: pytest.MonkeyPatch, patch: Callable[[Any], None],
             message: str, tmp_path: Path | None = None) -> None:  # fmt: skip
    if tmp_path is not None:
        (tmp_path / "ok").mkdir()
        (tmp_path / "mut").mkdir()
    check(*([tmp_path / "ok"] if tmp_path else []))
    patch(mp)
    with pytest.raises(AssertionError, match=message):
        check(*([tmp_path / "mut"] if tmp_path else []))


def test_removing_the_bipia_context_refusal_fails_the_share_alike_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ok_then(ic.assert_bipia_refuses_every_context_path, monkeypatch,
             lambda m: m.setattr(fetch, "BIPIA_REFUSED_CONTEXTS", ()),
             "was not refused by name")  # fmt: skip


_REAL_MAKE = records.make_record


def _altered_after_hashing(**kw: Any) -> Any:
    """Mutant: the text is changed AFTER its sha256 was computed."""
    record = _REAL_MAKE(**kw)
    return records.CorpusRecord.model_validate({**record.model_dump(), "text": record.text + " "})


def test_altering_text_after_hashing_fails_the_verbatim_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ok_then(ic.assert_records_are_verbatim_and_hashed, monkeypatch,
             lambda m: m.setattr(loaders, "make_record", _altered_after_hashing),
             "text does not match its sha256", tmp_path)  # fmt: skip


def test_skipping_the_licence_check_fails_the_named_check(monkeypatch: pytest.MonkeyPatch) -> None:
    _ok_then(ic.assert_a_record_without_the_table_licence_fails, monkeypatch,
             lambda m: m.setattr(records.CorpusRecord, "_check_license", lambda self: None),
             "was accepted")  # fmt: skip


def _unchecked_fetch(source: Any, path: str, cache_dir: Path, get: Any = None) -> bytes:
    """Mutant: the pinned sha256 is never compared."""
    fetch.check_path(source, path)
    cached = cache_dir / source.name / source.revision / Path(*path.split("/"))
    if cached.is_file():
        return cached.read_bytes()
    data: bytes = get(source.raw_url(path))
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_bytes(data)
    return data


def test_skipping_the_checksum_fails_the_named_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ok_then(ic.assert_fetch_enforces_the_pinned_checksum, monkeypatch,
             lambda m: m.setattr(fetch, "fetch_pinned", _unchecked_fetch),
             "wrong sha256 were accepted", tmp_path)  # fmt: skip


def test_without_the_network_guard_the_fetch_check_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mutant: the guard is gone (resolution then fails for some OTHER reason, simulated, so
    this test never touches the network either)."""

    def unguarded(host: Any, *args: Any, **kwargs: Any) -> Any:
        raise OSError("simulated resolver failure: the guard is not installed")

    _ok_then(ic.assert_tests_cannot_fetch, monkeypatch,
             lambda m: m.setattr(socket, "getaddrinfo", unguarded),
             "not at the network guard", tmp_path)  # fmt: skip


def test_a_guard_that_lets_github_through_fails_the_host_check() -> None:
    import netguard

    def leaky(underlying: Any) -> Any:
        real = netguard.guarded(underlying)
        return lambda host, *a, **k: (
            None if host == "raw.githubusercontent.com" else real(host, *a, **k)
        )

    ic.assert_dataset_hosts_are_refused()
    with pytest.raises(
        AssertionError, match=r"let corpus host raw\.githubusercontent\.com through"
    ):
        ic.assert_dataset_hosts_are_refused(leaky)


def test_reversed_source_priority_fails_the_dedup_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ok_then(ic.assert_dedup_follows_the_stated_rule, monkeypatch,
             lambda m: m.setattr(dedup, "SOURCE_PRIORITY", tuple(reversed(dedup.SOURCE_PRIORITY))),
             "did not follow the stated rule", tmp_path)  # fmt: skip


def test_a_case_folding_dedup_key_fails_the_dedup_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = dedup.dedup_key
    _ok_then(ic.assert_dedup_follows_the_stated_rule, monkeypatch,
             lambda m: m.setattr(dedup, "dedup_key", lambda text: real(text).casefold()),
             "did not follow the stated rule", tmp_path)  # fmt: skip


_REAL_RENDER = loaders.render_goal


def _guessing(node: ast.expr, scope: dict[str, str]) -> str | None:
    """Mutant: an unresolvable GOAL is guessed (its source text) instead of counted."""
    return _REAL_RENDER(node, scope) or ast.unparse(node)


def test_guessing_an_unresolved_goal_fails_the_named_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ok_then(ic.assert_agentdojo_goals_resolve_from_constants_only, monkeypatch,
             lambda m: m.setattr(loaders, "render_goal", _guessing),
             "were guessed or miscounted", tmp_path)  # fmt: skip


def test_ingesting_llmail_fails_the_named_check(monkeypatch: pytest.MonkeyPatch) -> None:
    _ok_then(ic.assert_llmail_is_not_ingested, monkeypatch,
             lambda m: m.setattr(ingest, "INGESTED", (*ingest.INGESTED, "llmail_inject")),
             "was not refused as not-ingested")  # fmt: skip


_REAL_VERSION_OF = loaders._version_of


def _defaulting(node: Any, scope: dict[str, Any]) -> Any:
    """Mutant: an unresolvable decorator version defaulted to 1.0.0 instead of counted."""
    return _REAL_VERSION_OF(node, scope) or loaders.BASE_VERSION


def test_defaulting_an_unresolvable_version_fails_the_named_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ok_then(ic.assert_an_unresolvable_version_is_counted_not_defaulted, monkeypatch,
             lambda m: m.setattr(loaders, "_version_of", _defaulting),
             r"was ingested \(defaulted\)", tmp_path)  # fmt: skip


_REAL_TABLE = loaders.benchmark_table


def _uniform(data: bytes) -> Any:
    """Mutant: one uniform target (the highest version) instead of upstream's per-suite table."""
    label, table = _REAL_TABLE(data)
    top = max(table.values())
    return label, {suite: top for suite in table}


def test_a_uniform_target_fails_the_upstream_table_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ok_then(ic.assert_agentdojo_resolves_by_upstreams_table, monkeypatch,
             lambda m: m.setattr(loaders, "benchmark_table", _uniform),
             "not upstream's per-suite table", tmp_path)  # fmt: skip


def _forgiving(data: bytes) -> Any:
    """Mutant: an unreadable table is swallowed and a guessed table used."""
    try:
        return _REAL_TABLE(data)
    except loaders.AgentDojoTableError:
        return "v?", {s: (1, 2, 2) for s in ("workspace", "travel", "banking", "slack")}


def test_swallowing_an_unreadable_table_fails_the_named_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ok_then(ic.assert_an_unreadable_table_fails_closed, monkeypatch,
             lambda m: m.setattr(loaders, "benchmark_table", _forgiving),
             "an unreadable benchmark table was accepted")  # fmt: skip


def test_drifted_stats_pins_fail_the_named_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mutant: the stats file records a pin that is not the source's (one sha256 changed)."""
    import json

    real = Path(ic.__file__).resolve().parents[1] / "docs" / "results" / "corpus-stats.json"
    body = json.loads(real.read_text(encoding="utf-8"))
    body["pins"]["bipia"]["files"]["LICENSE"] = "0" * 64
    drifted = tmp_path / "corpus-stats.json"
    drifted.write_text(json.dumps(body), encoding="utf-8")
    ic.assert_stats_pins_equal_the_sources(real)
    with pytest.raises(AssertionError, match=r"pins differ from sources\.SOURCES"):
        ic.assert_stats_pins_equal_the_sources(drifted)
