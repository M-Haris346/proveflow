"""Property: no serialization of a ServerSpec ever contains a planted secret."""

from __future__ import annotations

from pathlib import Path

from hypothesis import given
from hypothesis import strategies as st

from proveflow.core import RedactedText, RedactedValue, ServerSpec, TransportKind

# Every secret starts with a marker that never occurs in model structure, so
# containment is a real leak signal. (A bare random 8-char string is not: Hypothesis
# found 'Transpor' matching the repr text "TransportKind" — a false positive, not a leak.)
MARKER = "PLANTED"
secrets = st.text(min_size=1, max_size=200).map(lambda s: MARKER + s)


@given(secret=secrets)
def test_redacted_value_never_leaks_secret(secret: str) -> None:
    redacted = RedactedValue.from_secret(secret)
    for rendering in (str(redacted), repr(redacted), redacted.model_dump_json()):
        assert secret not in rendering
        assert MARKER not in rendering


@given(secret=secrets)
def test_server_spec_never_leaks_secret(secret: str) -> None:
    spec = ServerSpec(
        name="srv",
        transport=TransportKind.STDIO,
        command=RedactedText.plain("cmd"),
        args=(RedactedText(parts=("--token=", RedactedValue.from_secret(secret))),),
        env={"API_KEY": RedactedValue.from_secret(secret)},
        headers={"Authorization": RedactedValue.from_secret(secret)},
        source_file=Path("C:/example/config.json"),
    )
    for rendering in (str(spec), repr(spec), spec.model_dump_json(), str(spec.model_dump())):
        assert secret not in rendering
        assert MARKER not in rendering


@given(secret=secrets)
def test_redaction_is_deterministic_and_length_preserving(secret: str) -> None:
    a = RedactedValue.from_secret(secret)
    b = RedactedValue.from_secret(secret)
    assert a == b
    assert a.length == len(secret)
    assert str(a) == f"<redacted:sha256-{a.sha256_prefix}>"
