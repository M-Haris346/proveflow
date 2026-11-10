"""Property: no serialization of a ServerSpec ever contains a planted secret."""

from __future__ import annotations

from pathlib import Path

from hypothesis import given
from hypothesis import strategies as st

from proveflow.core import RedactedValue, ServerSpec, TransportKind

# min_size=8 so substring containment is a meaningful leak signal and
# coincidental matches against fixed JSON structure are effectively impossible.
secrets = st.text(min_size=8, max_size=200)


@given(secret=secrets)
def test_redacted_value_never_leaks_secret(secret: str) -> None:
    redacted = RedactedValue.from_secret(secret)
    for rendering in (str(redacted), repr(redacted), redacted.model_dump_json()):
        assert secret not in rendering


@given(secret=secrets)
def test_server_spec_never_leaks_secret(secret: str) -> None:
    spec = ServerSpec(
        name="srv",
        transport=TransportKind.STDIO,
        command="cmd",
        env={"API_KEY": RedactedValue.from_secret(secret)},
        headers={"Authorization": RedactedValue.from_secret(secret)},
        source_file=Path("C:/example/config.json"),
    )
    for rendering in (str(spec), repr(spec), spec.model_dump_json(), str(spec.model_dump())):
        assert secret not in rendering


@given(secret=secrets)
def test_redaction_is_deterministic_and_length_preserving(secret: str) -> None:
    a = RedactedValue.from_secret(secret)
    b = RedactedValue.from_secret(secret)
    assert a == b
    assert a.length == len(secret)
    assert str(a) == f"<redacted:sha256-{a.sha256_prefix}>"
