"""R8 property: no string the twin generates ever breaks t4_violations or contains a real
provider prefix, for any seed and any honey count (canary generation is covered in step 8)."""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from proveflow.core.honey import HoneyKind, new_honey, t4_violations
from proveflow.twin.archetypes import ARCHETYPES, render
from proveflow.twin.rng import Rng
from twinchecks import provider_prefix_in


@settings(max_examples=200, deadline=None)
@given(seed=st.text(max_size=20), name=st.sampled_from(sorted(ARCHETYPES)),
       n_honey=st.integers(min_value=0, max_value=4))  # fmt: skip
def test_no_generated_string_breaks_t4(seed: str, name: str, n_honey: int) -> None:
    kinds = list(HoneyKind)
    honey = tuple(
        new_honey(Rng(seed).derive("h", str(i)).draw_hex, kinds[i % 3], id=f"h{i:02d}")
        for i in range(n_honey)
    )
    for h in honey:
        assert t4_violations(h.value) == () and provider_prefix_in(h.value) is None
    content = render(name, Rng(seed).derive(name), "tool", honey)
    for item in content:
        assert t4_violations(item["text"]) == ()
        assert provider_prefix_in(item["text"]) is None
