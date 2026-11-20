# ADR-008: A trial is auditable, not reproducible

- Status: accepted (2026-11-19, Phase 5)

## Decision

**A trial is auditable, not reproducible; two runs of the same trial may differ, and the
evidence is the recorded transcript plus the cassette, not a claim that the run repeats.**

An LLM is not deterministic, and temperature 0 does not make it so. Groq documents that
`temperature: 0` is converted to `1e-8`, and that `seed` is "best effort … Determinism is not
guaranteed" (docs/PROVIDERS.md). proveflow therefore never claims a trial repeats.

## What makes a trial auditable

- **The transcript** (`runner/transcript.py`): every request exactly as sent (no headers, so
  never the key), every response, every tool call with its server, every tool result as
  given to the agent, the final answer, any cap that fired, and `trial_end`. Canonical JSONL,
  `seq`, sha256 hash chain, the same discipline and the same `canonical`/`digest` functions
  as the proxy cassette. No wall-clock value is in the hashed content.
- **The cassettes stay the proxies' own record.** The runner never writes into one. The
  transcript is a separate file and references each cassette by its final chain hash;
  `verify_cassette_refs` refuses a transcript whose referenced cassette does not match or is
  incomplete. The final answer, which the proxy never sees, is in the transcript only.
- **The provider seed** is recorded with whether it was sent (`send_seed`, set per provider
  from its documentation).
- **Replay** (`ReplayChatClient`) re-runs a recorded trial without the network: fresh twins
  from the same seeds, fresh proxies, a new transcript. Every request must equal the recorded
  one (canonical JSON) or `ReplayMismatch` is raised; replay never generates text. This is
  what every test uses, and what lets the oracle be re-run on an old trial after a rule
  changes.
- **Timings are not evidence.** Latency is wall-clock, so it cannot be in a hashed chain. It
  goes to an unhashed sidecar (`<trial>.timings.json`) labelled non-evidence in its own
  header and bound to the transcript by its final hash. A replayed trial without that
  sidecar raises `MissingTimings`; `latency_ms` is never defaulted (a fabricated zero would
  be a published number nobody measured).

## Token counts are the provider's (F10)

`tokens_in` and `tokens_out` come from the provider's own `usage` object, so the per-trial
caps and the run budget are enforced on **provider-reported counts, not on anything proveflow
measures**. A response without integer usage counts ends the trial (`usage_missing`): an
unknown spend cannot be bounded. proveflow has no token counter.

## Consequences

- Reported numbers carry provider, model, temperature, seed policy and the transcript; a
  re-run is a new trial, not a verification of the old one.
- A test transcript is a recording of fixed, hand-written response bodies, authored once by
  a dev-only script (`tools/author_transcript.py`) that no test can reach. A changed request
  fails the test; refreshing a fixture is a reviewed, manual step.
