# ADR-001: Scope and non-goals

- Status: accepted (2026-11-10)

## Decision

proveflow is a local-first CLI that finds cross-server toxic flows in a user's installed MCP
setup, proves exploitability in a schema twin, proposes fixes as patch files, and verifies them
with paired statistics.

Non-goals (will be declined even if requested):

- Certifying any setup as "safe" — `NOT_REPRODUCED` is a bounded negative result, never a safety claim.
- Runtime production firewall / gateway — use an actual gateway.
- SaaS dashboard, auth, multi-tenant anything.
- Jailbreak/toxicity testing — this is tool-flow security only.
- Attacking systems the user does not own.
- Enterprise claims of any kind.

## Rationale

Strict tiers (v0.1 find-only → v0.2 prove → v0.3 fix/verify) are the main defense against scope
explosion (ARCHITECTURE §12). Each cut feature has an existing better home (gateways, platforms).

## Consequences

Feature requests outside scope are rejected by reference to this ADR. The feature-tier table in
ARCHITECTURE §6 is the gate for what ships when.
