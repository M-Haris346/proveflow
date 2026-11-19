"""twin/archetypes.py and twin/select.py (D6): guarantees per archetype, determinism, the
render verification, and the selection rules."""

from __future__ import annotations

import pytest

from proveflow.twin import archetypes
from proveflow.twin.archetypes import ARCHETYPES, ArchetypeError, render
from proveflow.twin.rng import Rng
from proveflow.twin.select import FALLBACK, RULES, choose_archetype
from twinchecks import (
    SELECTION_SAMPLES,
    assert_archetype_guarantees,
    assert_selection_samples,
    sample_honey,
)


def test_exactly_the_six_archetypes() -> None:
    assert set(ARCHETYPES) == {
        "email_list", "document_text", "db_rows", "web_page", "issue_ticket", "generic_json",
    }  # fmt: skip


@pytest.mark.parametrize("name", sorted(ARCHETYPES))
def test_guarantees(name: str) -> None:
    assert_archetype_guarantees(name)


@pytest.mark.parametrize("name", sorted(ARCHETYPES))
def test_deterministic(name: str) -> None:
    honey = sample_honey()
    a = render(name, Rng("s").derive(name), "t", honey)  # type: ignore[arg-type]
    b = render(name, Rng("s").derive(name), "t", honey)  # type: ignore[arg-type]
    assert a == b
    assert render(name, Rng("other").derive(name), "t", honey) != a  # type: ignore[arg-type]


@pytest.mark.parametrize("name", sorted(ARCHETYPES))
def test_without_honey_there_is_still_a_text_block_and_no_honey(name: str) -> None:
    content = render(name, Rng("s"), "t", ())
    assert content and all(c["type"] == "text" for c in content)
    assert all("pfhoney_" not in c["text"] for c in content)


def test_render_refuses_unknown_and_broken_archetypes(monkeypatch: pytest.MonkeyPatch) -> None:
    honey = sample_honey()
    with pytest.raises(ArchetypeError, match="unknown archetype"):
        render("nope", Rng("s"), "t", honey)  # type: ignore[arg-type]
    monkeypatch.setitem(archetypes.ARCHETYPES, "generic_json", lambda r, t, h: [])
    with pytest.raises(ArchetypeError, match="no text block"):
        render("generic_json", Rng("s"), "t", honey)  # type: ignore[arg-type]
    monkeypatch.setitem(
        archetypes.ARCHETYPES, "generic_json", lambda r, t, h: [{"type": "text", "text": "x"}]
    )
    with pytest.raises(ArchetypeError, match="honey value h01 missing"):
        render("generic_json", Rng("s"), "t", honey)  # type: ignore[arg-type]
    monkeypatch.setitem(
        archetypes.ARCHETYPES,
        "generic_json",
        lambda r, t, h: [{"type": "text", "text": "card 4111111111111111"}],
    )
    with pytest.raises(ArchetypeError, match="T4"):
        render("generic_json", Rng("s"), "t", ())


# --- selection --------------------------------------------------------------------------


def test_selection_samples() -> None:
    assert_selection_samples()
    assert {r for r, _ in RULES} | {FALLBACK} == set(ARCHETYPES)
    assert set(SELECTION_SAMPLES) == {r for r, _ in RULES}


def test_fallback_and_reason() -> None:
    assert choose_archetype("get_current_time", "Returns the time.", {}) == (
        "generic_json",
        "no keyword hit",
    )
    archetype, reason = choose_archetype("fetch", "Fetch a URL.", {"properties": {"url": {}}})
    assert archetype == "web_page" and reason.startswith("heuristic")


def test_camel_case_and_schema_property_names_count() -> None:
    assert choose_archetype("readFile", "", {})[0] == "document_text"
    assert choose_archetype("run", "", {"properties": {"sql": {}, "table": {}}})[0] == "db_rows"


def test_ties_go_to_the_earlier_rule() -> None:
    # one hit each for email_list ("mail") and document_text ("file"): earlier rule wins
    assert choose_archetype("mail_file", "", {})[0] == "email_list"


def test_overrides() -> None:
    assert choose_archetype("fetch", "", {}, overrides={"fetch": "db_rows"}) == (
        "db_rows",
        "override",
    )
    with pytest.raises(ValueError, match="unknown archetype"):
        choose_archetype("fetch", "", {}, overrides={"fetch": "nope"})
