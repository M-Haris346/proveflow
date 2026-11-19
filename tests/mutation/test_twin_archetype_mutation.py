"""Mutation: break one archetype's guarantee, or remove one selection rule -> the NAMED check
fails. And the render verification is load-bearing: with it disabled, a broken archetype is
no longer caught."""

from __future__ import annotations

import pytest

from proveflow.twin import archetypes, select
from twinchecks import SELECTION_SAMPLES, assert_archetype_guarantees, assert_selection_samples


@pytest.mark.parametrize("name", sorted(archetypes.ARCHETYPES))
def test_archetype_dropping_honey_fails_its_named_check(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    assert_archetype_guarantees(name)
    original = archetypes.ARCHETYPES[name]

    def drops_honey(rng, tool, honey):  # type: ignore[no-untyped-def]
        return original(rng, tool, ())

    monkeypatch.setitem(archetypes.ARCHETYPES, name, drops_honey)
    with pytest.raises(AssertionError, match=f"archetype {name} broke a guarantee"):
        assert_archetype_guarantees(name)


@pytest.mark.parametrize("name", sorted(archetypes.ARCHETYPES))
def test_archetype_dropping_its_text_block_fails_its_named_check(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    monkeypatch.setitem(archetypes.ARCHETYPES, name, lambda rng, tool, honey: [])
    with pytest.raises(AssertionError, match="no text block"):
        assert_archetype_guarantees(name)


def test_render_verification_is_load_bearing(monkeypatch: pytest.MonkeyPatch) -> None:
    """With the honey check in render removed AND an archetype dropping honey, only the
    named check's own scan remains to catch it."""
    original = archetypes.ARCHETYPES["db_rows"]
    monkeypatch.setitem(archetypes.ARCHETYPES, "db_rows", lambda r, t, h: original(r, t, ()))
    monkeypatch.setattr(archetypes, "render", lambda n, rng, tool, honey: original(rng, tool, ()))
    with pytest.raises(AssertionError, match="lost honey"):
        assert_archetype_guarantees("db_rows")


@pytest.mark.parametrize("archetype", sorted(SELECTION_SAMPLES))
def test_removing_a_selection_rule_fails_the_named_check(
    monkeypatch: pytest.MonkeyPatch, archetype: str
) -> None:
    assert_selection_samples()
    monkeypatch.setattr(select, "RULES", [r for r in select.RULES if r[0] != archetype])
    with pytest.raises(AssertionError, match=f"want {archetype}"):
        assert_selection_samples()
