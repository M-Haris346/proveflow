"""F7: the ONE deliberate opt-out from the pinned render width (tests/widths.py).

The consent prompt is a security warning. A real user reads it in a narrow terminal, where
Rich hard-wraps its command line across many lines. The property that matters there is that
the pattern redaction survives the wrapping: no planted secret appears in the rendered
output, not even split across wrapped lines. That property exists only when wrapping
happens, so this check narrows the width on purpose. Exact text is width-dependent by design
here and is NOT asserted; the absence of the planted value is.

Called by tests/safety/test_consent_redaction_narrow.py and, with one redaction rule removed,
by tests/mutation/test_consent_redaction_narrow_mutation.py. Listed in the exact-set
allowlist of tests/unit/test_render_width.py with its reason.
"""

from __future__ import annotations

from widths import long_command_consent

NARROW_COLUMNS = "40"
# Caught only by the `--token X` flag rule (R-ARG-NEXT): no digits, so the entropy fallback
# does not redact it, and removing that one rule makes it leak (the mutation test).
PLANTED = "PLANTEDnarrowwrapvalue"


def assert_redaction_survives_narrow_wrap(tmp_path: object, monkeypatch: object) -> None:
    """Named check: at COLUMNS=40 the consent prompt is hard-wrapped across many lines, and
    the planted ``--token`` value appears nowhere in stderr or stdout, neither as printed nor
    with all whitespace removed (so a value split across wrapped lines is still caught)."""
    monkeypatch.setenv("COLUMNS", NARROW_COLUMNS)  # type: ignore[attr-defined]
    result, _ = long_command_consent(tmp_path, monkeypatch, ("--token", PLANTED))
    stderr: str = result.stderr  # type: ignore[attr-defined]
    stdout: str = result.stdout  # type: ignore[attr-defined]
    lines = stderr.splitlines()
    if len(lines) < 100 or max(len(line) for line in lines) > int(NARROW_COLUMNS):
        raise AssertionError("check is vacuous: the consent prompt was not hard-wrapped")
    squeezed = "".join(stderr.split())
    for text in (stderr, squeezed, stdout, "".join(stdout.split())):
        if PLANTED in text:
            raise AssertionError("planted secret leaked in the wrapped consent prompt")
    if "<redacted:sha256-" not in squeezed:
        raise AssertionError("no redaction marker in the wrapped consent prompt")
