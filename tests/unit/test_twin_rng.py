"""twin/rng.py (R2): definition, golden values, determinism, HexSource compatibility, and a
scan that no stdlib ``random`` is used anywhere in twin/."""

from __future__ import annotations

import ast
import hashlib
import subprocess
import sys
from pathlib import Path

import pytest

import proveflow.twin
from proveflow.core.honey import HoneyKind, new_honey
from proveflow.twin.rng import Rng

GOLDEN_SEED = "golden-seed"
GOLDEN_BYTES64_SHA256 = "b6b113f519da0de53374de6521e981857faf4a58a604271338effccb164b6a85"
GOLDEN_HEX16 = "b5e1637b3b8ec2d6"
GOLDEN_INTS = [1, 5, 9, 3, 9, 2, 4, 4, 2, 5, 0, 0]
GOLDEN_SHUFFLE = ["c", "f", "e", "d", "a", "b"]
GOLDEN_DERIVED = "274351658b9e"


def test_stream_matches_its_definition() -> None:
    """Independent recomputation: block i = sha256(sha256(len||seed) || i as 8 bytes)."""
    raw = GOLDEN_SEED.encode()
    seed = hashlib.sha256(len(raw).to_bytes(4, "big") + raw).digest()
    expected = b"".join(hashlib.sha256(seed + i.to_bytes(8, "big")).digest() for i in range(3))
    assert Rng(GOLDEN_SEED).read(96) == expected


def test_golden_values() -> None:
    assert hashlib.sha256(Rng(GOLDEN_SEED).read(64)).hexdigest() == GOLDEN_BYTES64_SHA256
    assert Rng(GOLDEN_SEED).draw_hex(16) == GOLDEN_HEX16
    r = Rng(GOLDEN_SEED)
    assert [r.randrange(0, 10) for _ in range(12)] == GOLDEN_INTS
    assert Rng(GOLDEN_SEED).shuffled(list("abcdef")) == GOLDEN_SHUFFLE
    assert Rng(GOLDEN_SEED).derive("tool", "x").draw_hex(12) == GOLDEN_DERIVED


def test_same_output_in_a_fresh_interpreter_with_a_different_hash_seed() -> None:
    code = (
        "import hashlib; from proveflow.twin.rng import Rng; "
        f"print(hashlib.sha256(Rng({GOLDEN_SEED!r}).read(64)).hexdigest())"
    )
    for hashseed in ("0", "12345"):
        out = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            check=True,
            env={**__import__("os").environ, "PYTHONHASHSEED": hashseed},
        ).stdout.strip()
        assert out == GOLDEN_BYTES64_SHA256


def test_reads_are_contiguous() -> None:
    a = Rng("s")
    b = Rng("s")
    assert a.read(5) + a.read(40) + a.read(3) == b.read(48)


@pytest.mark.parametrize("n", [0, 1, 11, 12, 16, 33])
def test_draw_hex_length_and_alphabet(n: int) -> None:
    out = Rng("s").draw_hex(n)
    assert len(out) == n and set(out) <= set("0123456789abcdef")


def test_draw_hex_is_a_honey_hexsource() -> None:
    value = new_honey(Rng("s").draw_hex, HoneyKind.APIKEY, id="h01")
    assert value == new_honey(Rng("s").draw_hex, HoneyKind.APIKEY, id="h01")  # deterministic


def test_randbelow_range_and_all_values_reachable() -> None:
    r = Rng("s")
    seen = {r.randbelow(7) for _ in range(500)}
    assert seen == set(range(7))
    assert all(0 <= Rng(str(i)).randbelow(1000) < 1000 for i in range(50))
    with pytest.raises(ValueError):
        r.randbelow(0)
    with pytest.raises(ValueError):
        r.randrange(3, 3)
    with pytest.raises(ValueError):
        r.choice([])


def test_derive_is_independent_and_unambiguous() -> None:
    parent = Rng("s")
    before = Rng("s").read(32)
    parent.derive("x").read(100)
    assert parent.read(32) == before  # deriving consumes nothing from the parent
    assert Rng("s").derive("a", "bc").read(16) != Rng("s").derive("ab", "c").read(16)
    assert Rng("s").derive("x").read(16) != Rng("s").derive("y").read(16)
    assert Rng("s").derive("x").read(16) != Rng("t").derive("x").read(16)


def test_shuffled_is_a_permutation_and_does_not_mutate() -> None:
    items = list(range(20))
    out = Rng("s").shuffled(items)
    assert sorted(out) == items and items == list(range(20)) and out != items


def test_no_stdlib_random_anywhere_in_twin() -> None:
    """R2: the generator and archetypes use only twin.rng."""
    twin_dir = Path(proveflow.twin.__file__).parent
    for f in sorted(twin_dir.glob("*.py")):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            for name in names:
                assert name.split(".")[0] not in ("random", "secrets"), (f.name, name)
