"""Corpus ingest (Phase 6 step 3) on committed SYNTHETIC fixtures. Offline: no test fetches."""

from __future__ import annotations

from pathlib import Path

from ingestchecks import (
    assert_a_record_without_the_table_licence_fails,
    assert_agentdojo_goals_resolve_from_constants_only,
    assert_agentdojo_resolves_by_upstreams_table,
    assert_an_unreadable_table_fails_closed,
    assert_an_unresolvable_version_is_counted_not_defaulted,
    assert_bipia_refuses_every_context_path,
    assert_dataset_hosts_are_refused,
    assert_dedup_follows_the_stated_rule,
    assert_fetch_enforces_the_pinned_checksum,
    assert_llmail_is_not_ingested,
    assert_records_are_verbatim_and_hashed,
    assert_stats_pins_equal_the_sources,
    assert_tests_cannot_fetch,
    fixture_ingest,
    stats_of,
)
from proveflow.corpus.sources import AGENTDOJO, BIPIA, INJECAGENT, SOURCES


def test_bipia_refuses_every_context_path() -> None:
    assert_bipia_refuses_every_context_path()


def test_records_are_verbatim_and_hashed(tmp_path: Path) -> None:
    assert_records_are_verbatim_and_hashed(tmp_path)


def test_a_record_without_the_table_licence_fails() -> None:
    assert_a_record_without_the_table_licence_fails()


def test_fetch_enforces_the_pinned_checksum(tmp_path: Path) -> None:
    assert_fetch_enforces_the_pinned_checksum(tmp_path)


def test_tests_cannot_fetch(tmp_path: Path) -> None:
    assert_tests_cannot_fetch(tmp_path)


def test_dataset_hosts_are_refused() -> None:
    assert_dataset_hosts_are_refused()


def test_dedup_follows_the_stated_rule(tmp_path: Path) -> None:
    assert_dedup_follows_the_stated_rule(tmp_path)


def test_agentdojo_goals_resolve_from_constants_only(tmp_path: Path) -> None:
    assert_agentdojo_goals_resolve_from_constants_only(tmp_path)


def test_llmail_is_not_ingested() -> None:
    assert_llmail_is_not_ingested()


def test_the_pins_are_the_reviewed_sources() -> None:
    """The pinned sources are exactly the three approved ones; BIPIA pins only its four attack
    files and LICENSE; InjecAgent's licence is fetched by its exact name LICENCE."""
    assert set(SOURCES) == {"injecagent", "bipia", "agentdojo"}
    assert set(BIPIA.files) == {"LICENSE", "benchmark/text_attack_train.json",
                                "benchmark/text_attack_test.json",
                                "benchmark/code_attack_train.json",
                                "benchmark/code_attack_test.json"}  # fmt: skip
    assert INJECAGENT.licence_file == "LICENCE" and "LICENCE" in INJECAGENT.files
    assert "LICENSE" not in INJECAGENT.files
    for source in (INJECAGENT, BIPIA, AGENTDOJO):
        assert source.licence_file in source.files
        assert len(source.revision) == 40 and all(len(v) == 64 for v in source.files.values())


def test_the_loader_reads_the_licence_by_its_exact_name(tmp_path: Path) -> None:
    from ingestchecks import fixture_reader
    from proveflow.corpus.loaders import load_injecagent

    read_paths: list[str] = []
    real = fixture_reader(INJECAGENT)

    def spy(path: str) -> bytes:
        read_paths.append(path)
        return real(path)

    load_injecagent(spy)
    assert read_paths[0] == "LICENCE"


def test_stats_are_measured_before_and_after_dedup(tmp_path: Path) -> None:
    stats = stats_of(tmp_path)
    assert stats["before_dedup"]["per_source"] == {"agentdojo": 6, "bipia": 7, "injecagent": 3}
    assert stats["after_dedup"]["per_source"] == {"agentdojo": 6, "bipia": 6, "injecagent": 3}
    assert stats["duplicates_dropped"] == 1 and stats["dedup_rate"] == 1 / 16
    assert stats["licenses_present"] == ["MIT"]
    assert stats["before_dedup"]["per_language"] == {"und": 16}
    assert stats["before_dedup"]["per_attack_family"]["bipia/Memory Scanning"] == 2


def test_a_corpus_record_instantiates_an_attack(tmp_path: Path) -> None:
    """A corpus record becomes the verbatim Payload of an Attack (step 1's instantiate, which
    re-verifies the sha256)."""
    from proveflow.core.attacks import Carrier, HijackGoal
    from proveflow.corpus.instantiate import instantiate

    record = fixture_ingest(tmp_path).dedup.kept[0]
    attack = instantiate(record.payload(), Carrier.PLAIN, HijackGoal())
    assert attack.payload.text == record.text and attack.payload.license == "MIT"


def test_agentdojo_resolves_by_upstreams_table(tmp_path: Path) -> None:
    assert_agentdojo_resolves_by_upstreams_table(tmp_path)


def test_an_unresolvable_version_is_counted_not_defaulted(tmp_path: Path) -> None:
    assert_an_unresolvable_version_is_counted_not_defaulted(tmp_path)


def test_an_unreadable_table_fails_closed() -> None:
    assert_an_unreadable_table_fails_closed()


def test_stats_pins_equal_the_sources() -> None:
    """The committed measured evidence names exactly the pinned bytes."""
    assert_stats_pins_equal_the_sources()


def test_agentdojo_pins_every_default_suite_file_and_the_table() -> None:
    from proveflow.corpus.sources import AGENTDOJO_TABLE

    tasks = [p for p in AGENTDOJO.files if p.endswith("injection_tasks.py")]
    assert len(tasks) == 11 and all(p.startswith("src/agentdojo/default_suites/") for p in tasks)
    assert AGENTDOJO_TABLE in AGENTDOJO.files
    assert not any(p.startswith("examples/") for p in AGENTDOJO.files)
