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
  canary cannot occur benignly), unlike judge prompts. Phase 4 states it with the exact
  accepted space (47.9895 bits for the canary, |S_canary| = 279,426,400,710,656), see below.

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
  - False-positive union bound (Phase 3a, superseded below): n · 91 · 2^-48 per string of n
    characters.
  - `OracleFindings` → `Verdict` needs runner-provided utility and costs (no defaults).

## Phase 4 amendment: honey needles, structural T4 predicate, honest entropy

**Pre-existing T4 gap found in Phase 4.** THREAT_MODEL T4 says payloads never carry
format-valid card or ID numbers. The Phase 3a canary was `cnry_` + 12 hex digits drawn
uniformly, and nothing rejected a draw that breaks T4. By the exact count below, 7.2780e-3 of
all draws (about 1 in 137) do: twelve decimal digits in a row (alone (10/16)^12 ≈ 3.55e-3, a
card-number-like run) or a NINO-shaped substring.

**Structural rule, not a blocklist.** `core.honey.t4_violations` has exactly two rules:
`digit_run_12` (twelve or more consecutive decimal digits) and `nino_shape` (two NINO prefix
letters, six digits, one suffix letter A-D). There is no Luhn check and no list of provider
key prefixes in the library: a blocklist must be kept in step with every provider on earth, a
restricted alphabet does not. Generated values use only lowercase hex after a fixed prefix,
so a provider prefix (`sk-`, `AKIA`, `ghp_`, ...) cannot appear; that is asserted in tests
(`tests/twinchecks.py`), not enforced by a list.

**Rejection sampling, shared.** Both the canary (`oracle.canary.new_canary`, N1) and every
honey value (`core.honey.new_honey`) redraw on any violation and fail closed after 64 draws.
`CANARY_PATTERN` is unchanged.

**Honest entropy (R11).** The accepted spaces are counted exactly by
`uv run python tools/count_t4_space.py` (pinned by `tests/unit/test_t4_space.py`, with
brute-force cross-checks on reduced alphabets):

| Needle | Format | Accepted values |S| | log2 |S| | Rejection per draw |
|---|---|---|---|---|
| canary | `cnry_` + 12 hex | 279,426,400,710,656 | 47.9895 bits | 7.2780e-3 |
| honey | `pfhoney_<kind>_` + 16 hex | 18,145,465,120,237,551,616 | 63.9762 bits | 1.6332e-2 |

(Never "48 bits" or "64 bits": the rejected values are not in the space.)

**Bound.** For a fixed string of n characters that does not depend on the needles, with at
most V ≤ 91 variant checks per string and at most H ≤ 32 honey values per session:

  P(false R1 match) ≤ n · V / |S_canary| + H · n · V / |S_honey|

| n | H | new bound | old bound n · 91 · 2^-48 | ratio |
|---|---|---|---|---|
| 1 KiB | 0 | 3.3348e-10 | 3.3106e-10 | 1.0073 |
| 1 KiB | 32 | 3.3365e-10 | 3.3106e-10 | 1.0078 |
| 1 MiB | 0 | 3.4149e-07 | 3.3900e-07 | 1.0073 |
| 1 MiB | 32 | 3.4166e-07 | 3.3900e-07 | 1.0078 |

**Phase 5: H is the TRIAL's total needles.** A trial with N proxies is evaluated with the
union of every session's honey (`oracle.evaluate_trial`), so H counts all honey values of
all twins in the trial, not one session's. There is no trial-level cap; the bound is
computed instead (same counter, n = 1 MiB, V = 91):

| H | bound | vs n · 91 · 2^-48 = 3.3900e-07 |
|---|---|---|
| 32 | 3.4166e-07 | ×1.0078 |
| 64 | 3.4182e-07 | ×1.0083 |
| 128 | 3.4216e-07 | ×1.0093 |
| 256 (eight servers at the per-session cap) | 3.4283e-07 | ×1.0113 |

Each honey value adds n·V/|S_honey| = 5.2586e-12; the canary term (3.4149e-07) dominates.

This is a union bound, not a measurement. The honey cap H ≤ 32 (`twin.generator.MAX_HONEY`,
`proxy.session.MAX_HONEY`, equal by test) is a **statement-bounding device**: it keeps the
bound above true as written. It is not a safety-critical number; raising it changes the
stated bound, nothing else.
