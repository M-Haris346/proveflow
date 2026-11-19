# ADR-003: Twin mode is the default; no `tools/call` to real servers

- Status: accepted (2026-11-10)

## Decision

Dynamic testing runs against generated schema twins. proveflow never sends `tools/call` to a
real server in default mode. Introspection is `tools/list` only, with per-server consent and a
timeout. The sink sandbox is always on in twin mode and cannot be disabled.

## Rationale

- Attacking real servers could exfiltrate real data, send real emails, delete real resources —
  one incident would (rightly) end the project.
- `tools/list` already requires launching the server (same risk the user's client takes daily);
  that is the maximum default exposure we accept, and it is consent-gated.
- Twins preserve what the attack actually needs: tool names, descriptions, schemas — the agent's
  decision surface.

## Consequences

- Honest limitation in every report: the twin proves the agent + tool surface is exploitable,
  not that the real server returns exploitable content.
- A future opt-in `--real-reads` mode (v1) may forward **non-sink** calls with explicit per-server
  consent; sink calls stay sandboxed even then.
- Safety tests assert zero `tools/call` to real servers and zero forwarded pure-sink calls.
- **Amended by ADR-007 (Phase 4):** in twin mode only, a dual-role tool (untrusted_source +
  sink by the session's evidence AND the proxy's own classifier) is forwarded to a twin that
  passed the twin guard, so injection into fetch-style sources can be tested. Pure sinks stay
  sandboxed always. That exception must not survive into `--real-reads`.
