"""Tool-name collision detection (L1): names that look alike are denied together.

Key = NFKC, then casefold, then remove every Default_Ignorable_Code_Point. Two different names
with the same key (``send_email`` vs ``send_\\u200bemail`` vs fullwidth ``\\uff33END_email``) are a
collision, and every member of a colliding group is denied (forward=False). This keeps a
twin, or a classifier label, from separating a sink from its look-alike. Separators are NOT
folded: ``send\\u200bemail`` keys to ``sendemail``, which differs from ``send_email``.

DEFAULT_IGNORABLE is copied from the official Unicode Character Database file
``DerivedCoreProperties-15.0.0.txt`` (Date: 2022-08-05), section
``Default_Ignorable_Code_Point``, "# Total code points: 4174":
<https://www.unicode.org/Public/15.0.0/ucd/DerivedCoreProperties.txt> (fetched 2026-11-14).
15.0.0 matches ``unicodedata.unidata_version`` of the pinned Python 3.12. Tests check the
total (4174) and each line's general category against ``unicodedata``.
"""

from __future__ import annotations

import unicodedata
from collections import defaultdict
from collections.abc import Iterable

# (first, last) inclusive, one entry per data line of the UCD section, in file order.
DEFAULT_IGNORABLE: tuple[tuple[int, int], ...] = (
    (0x00AD, 0x00AD),  # Cf SOFT HYPHEN
    (0x034F, 0x034F),  # Mn COMBINING GRAPHEME JOINER
    (0x061C, 0x061C),  # Cf ARABIC LETTER MARK
    (0x115F, 0x1160),  # Lo HANGUL CHOSEONG FILLER..HANGUL JUNGSEONG FILLER
    (0x17B4, 0x17B5),  # Mn KHMER VOWEL INHERENT AQ..AA
    (0x180B, 0x180D),  # Mn MONGOLIAN FREE VARIATION SELECTOR ONE..THREE
    (0x180E, 0x180E),  # Cf MONGOLIAN VOWEL SEPARATOR
    (0x180F, 0x180F),  # Mn MONGOLIAN FREE VARIATION SELECTOR FOUR
    (0x200B, 0x200F),  # Cf ZERO WIDTH SPACE..RIGHT-TO-LEFT MARK
    (0x202A, 0x202E),  # Cf LEFT-TO-RIGHT EMBEDDING..RIGHT-TO-LEFT OVERRIDE
    (0x2060, 0x2064),  # Cf WORD JOINER..INVISIBLE PLUS
    (0x2065, 0x2065),  # Cn <reserved-2065>
    (0x2066, 0x206F),  # Cf LEFT-TO-RIGHT ISOLATE..NOMINAL DIGIT SHAPES
    (0x3164, 0x3164),  # Lo HANGUL FILLER
    (0xFE00, 0xFE0F),  # Mn VARIATION SELECTOR-1..16
    (0xFEFF, 0xFEFF),  # Cf ZERO WIDTH NO-BREAK SPACE
    (0xFFA0, 0xFFA0),  # Lo HALFWIDTH HANGUL FILLER
    (0xFFF0, 0xFFF8),  # Cn <reserved-FFF0>..<reserved-FFF8>
    (0x1BCA0, 0x1BCA3),  # Cf SHORTHAND FORMAT LETTER OVERLAP..UP STEP
    (0x1D173, 0x1D17A),  # Cf MUSICAL SYMBOL BEGIN BEAM..END PHRASE
    (0xE0000, 0xE0000),  # Cn <reserved-E0000>
    (0xE0001, 0xE0001),  # Cf LANGUAGE TAG
    (0xE0002, 0xE001F),  # Cn <reserved-E0002>..<reserved-E001F>
    (0xE0020, 0xE007F),  # Cf TAG SPACE..CANCEL TAG
    (0xE0080, 0xE00FF),  # Cn <reserved-E0080>..<reserved-E00FF>
    (0xE0100, 0xE01EF),  # Mn VARIATION SELECTOR-17..256
    (0xE01F0, 0xE0FFF),  # Cn <reserved-E01F0>..<reserved-E0FFF>
)
DEFAULT_IGNORABLE_TOTAL = 4174


def is_default_ignorable(char: str) -> bool:
    cp = ord(char)
    return any(first <= cp <= last for first, last in DEFAULT_IGNORABLE)


def name_key(name: str) -> str:
    """NFKC + casefold + removal of default-ignorable code points."""
    folded = unicodedata.normalize("NFKC", name).casefold()
    return "".join(ch for ch in folded if not is_default_ignorable(ch))


def colliding_names(names: Iterable[str]) -> frozenset[str]:
    """Every name that shares its key with at least one OTHER distinct name."""
    groups: dict[str, set[str]] = defaultdict(set)
    for name in names:
        groups[name_key(name)].add(name)
    return frozenset(n for members in groups.values() if len(members) > 1 for n in members)
