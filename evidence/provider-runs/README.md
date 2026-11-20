# Evidence: records of real provider runs (Phase 5, R2)

Each directory here is a record of ONE real run against a real LLM provider, named
`<provider>-<model>-<date>/`, holding `transcript.jsonl`, the `scenario.json` it ran, and a
`README.md` stating the provider, model, date and outcome.

**These are not replay fixtures.** A real run's cassettes hold absolute interpreter and twin
paths in `session_start` and are not committed, so a transcript here cannot have its cassette
references resolved. Its check (`tests/safety/test_transcript_layers.py`) is the hash chain
plus the D7 shape scan over the file, and it never resolves cassette references. Replay
fixtures live in `tests/fixtures/runner/`, and the replay helpers cannot reach this directory.

Before a run is committed here it must also pass the exact-key check: the real API key, in
any of the matcher's 10 encodings, appears in no file of the run's output directory.
