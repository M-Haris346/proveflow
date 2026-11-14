# ADR-004: Deterministic oracle; no LLM judge for primary verdicts

- Status: accepted (2026-11-10)

## Decision

Compromise verdicts come only from deterministic rules (R1–R4 in METHODOLOGY.md) evaluated over
the cassette: canary/honey matching with an encoding-aware matcher, goal predicates, and answer
markers. An LLM may *suggest* (e.g. tool roles), but a suggestion only counts after explicit
user confirmation and is stored with provenance. No LLM-as-judge decides whether a trial was a
compromise.

## Rationale

- The whole pitch is *proof*. A probabilistic judge judging a probabilistic attack produces
  numbers nobody can reproduce or trust.
- Deterministic verdicts make `replay` possible: same cassette ⇒ byte-identical verdict JSON,
  at zero LLM cost — which is also what makes the CI story (Phase 9) free to run.
- Canary-based detection has a precisely characterizable false-positive story (a fresh random
  canary cannot occur benignly), unlike judge prompts.

## Consequences

- Attacks whose success is not expressible as a deterministic predicate are out of scope for
  primary metrics (R4 flags suspicious cases for human review, uncounted).
- The encoding matcher must be aggressively tested (property + mutation tests) since it bounds
  what R1 can see.
- Phase 3a implementation (docs/ORACLE.md):
  - R1 and R4 only.
  - Sink-ness is recorded by the proxy (`sink` on `sandboxed_call`, cassette schema 2) and
    only read by the oracle, so there is one definition and no drift.
  - Incomplete, byte-capped or truncated cassettes raise `IncompleteCassetteError` and never
    produce a verdict.
  - False-positive union bound: n · 91 · 2^-48 per string of n characters.
  - `OracleFindings` → `Verdict` needs runner-provided utility and costs (no defaults).
