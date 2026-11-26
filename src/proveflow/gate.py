"""The scan gate (Phase 9): ``proveflow scan --fail-on CLASS`` for CI.

Exit codes, Haris's ruling (2026-11-26), "an error is never a finding":
* ``FINDINGS_EXIT_CODE`` (3) ONLY when the report holds at least one flow of the given class
  (``any``: of any class);
* 0 when it holds none, including ``--fail-on any`` with zero flows;
* 1 (``cli.USAGE_ERROR_EXIT_CODE``) for every error the command itself detects: a bad
  ``--fail-on`` value, and FAIL CLOSED, any config the scan could not read (parse error,
  unreadable file, or an invalid server entry). A gate that went green on a file it could not
  read would be worse than no gate (measured 2026-11-26: before this, a malformed ``--servers``
  file scanned as 0 flows and exit 0).
Arguments click itself rejects before the command runs (a missing ``--servers`` path, an
out-of-range ``--limit``) exit 2, click's usage-error code. That is still never 3.

A flow found with ``--no-launch`` is THEORETICAL (from config names and command lines only);
the message says which kind of scan produced it.
"""

from __future__ import annotations

from collections.abc import Sequence

from proveflow.core.client import ClientConfig, ConfigStatus
from proveflow.core.flows import Flow

FINDINGS_EXIT_CODE = 3
FAIL_ON = ("exfil", "action", "leak", "any")
UNREAD = frozenset({ConfigStatus.PARSE_ERROR, ConfigStatus.UNREADABLE})


def unread_configs(configs: Sequence[ClientConfig]) -> list[str]:
    """Every config the scan could not fully read, as one line each (fail closed)."""
    out: list[str] = []
    for c in configs:
        where = f"{c.kind.value} {c.scope.value} {c.path}"
        if c.status in UNREAD:
            out.append(f"{where}: {c.status.value} ({c.detail})")
        elif c.entry_errors:
            out.append(f"{where}: {len(c.entry_errors)} invalid server entr"
                       f"{'y' if len(c.entry_errors) == 1 else 'ies'}")  # fmt: skip
    return out


def matched(flows: Sequence[Flow], fail_on: str) -> list[Flow]:
    """The flows that trip the gate: every flow for ``any``, else those of that class."""
    if fail_on not in FAIL_ON:
        raise ValueError(f"--fail-on must be one of {', '.join(FAIL_ON)}")
    return [f for f in flows if fail_on == "any" or f.flow_class.value == fail_on]


def finding_message(hits: Sequence[Flow], fail_on: str, *, introspected: bool) -> str:
    kind = ("from introspected tool lists" if introspected
            else "THEORETICAL: from config names and command lines only (--no-launch)")  # fmt: skip
    return f"proveflow: {len(hits)} flow(s) matched --fail-on {fail_on} ({kind})"
