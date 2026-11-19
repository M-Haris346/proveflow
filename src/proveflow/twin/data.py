"""Synthetic data for twins (D7): small fixed word lists, drawn with ``twin.rng`` only.

Everything is obviously fake: addresses ``@example.invalid``, URLs
``https://example.invalid/...``, surnames that are placeholder words, organisation names
marked fictional. No real person, company or domain. Numbers stay short (ids at most 6
digits) so no generated string can contain a 12-digit run (T4, R8): ``t4_violations`` runs on
every word here (tests/unit/test_twin_data.py) and on every rendered response.
"""

from __future__ import annotations

from proveflow.twin.rng import Rng

DOMAIN = "example.invalid"

FIRST_NAMES: tuple[str, ...] = (
    "Alex", "Blair", "Casey", "Drew", "Emery", "Finley", "Harper", "Jordan", "Kai",
    "Morgan", "Quinn", "Riley", "Sage", "Taylor",
)  # fmt: skip
LAST_NAMES: tuple[str, ...] = (
    "Placeholder", "Sample", "Example", "Fixture", "Dummy", "Mockup", "Stub", "Testcase",
)  # fmt: skip
ORGS: tuple[str, ...] = (
    "Example Org (fictional)", "Sample Works (fictional)", "Placeholder Group (fictional)",
    "Fixture Labs (fictional)",
)  # fmt: skip
WORDS: tuple[str, ...] = (
    "report", "schedule", "update", "review", "draft", "summary", "budget", "meeting",
    "release", "roadmap", "invoice", "contract", "proposal", "feedback", "agenda", "metrics",
    "backlog", "milestone", "workshop", "onboarding",
)  # fmt: skip
STATUSES: tuple[str, ...] = ("open", "closed", "pending", "in review")
LABELS: tuple[str, ...] = ("bug", "feature", "docs", "question", "chore")
SECTIONS: tuple[str, ...] = ("Overview", "Details", "Next steps", "Notes", "Background")

WORD_LISTS: dict[str, tuple[str, ...]] = {
    "FIRST_NAMES": FIRST_NAMES,
    "LAST_NAMES": LAST_NAMES,
    "ORGS": ORGS,
    "WORDS": WORDS,
    "STATUSES": STATUSES,
    "LABELS": LABELS,
    "SECTIONS": SECTIONS,
    "DOMAIN": (DOMAIN,),
}


def person(rng: Rng) -> tuple[str, str]:
    """(display name, email)."""
    first, last = rng.choice(FIRST_NAMES), rng.choice(LAST_NAMES)
    return f"{first} {last}", f"{first.lower()}.{last.lower()}@{DOMAIN}"


def url(rng: Rng, *path: str) -> str:
    parts = "/".join(path) if path else rng.choice(WORDS)
    return f"https://{DOMAIN}/{parts}"


def short_id(rng: Rng, prefix: str) -> str:
    return f"{prefix}-{rng.randrange(100, 1_000_000)}"  # at most 6 digits


def sentence(rng: Rng, words: int = 8) -> str:
    chosen = [rng.choice(WORDS) for _ in range(words)]
    return chosen[0].capitalize() + " " + " ".join(chosen[1:]) + "."


def title(rng: Rng) -> str:
    return f"{rng.choice(WORDS).capitalize()} {rng.choice(WORDS)}"
