# Backlog: known residuals not fixed yet

Each item has a source, a severity from the review that found it, and a proposed test. An item
moves out of this file only with a fix and that test in the repo.

## Proxy (Phase 2 review, 2026-11-14; ADR-006)

### L3: the gate allows any error response and any cancel params (low)
- **Where:** `src/proveflow/proxy/gate.py` (`UpstreamGate.check`). JSON-RPC error responses
  always pass, and `notifications/cancelled` passes with any params.
- **Today:** only the proxy's transport and the MCP SDK create these, with fixed text (for
  example "caller cancelled"). Probe: a forged agent cancel reason never reached the twin.
- **Risk:** a future code path that copied agent text into an error `data` or a cancel `reason`
  would pass the gate.
- **Proposed fix:** allow error responses only for request ids the transport answered itself,
  and cancels only for in-flight upstream request ids; drop `data` and `reason`.
- **Proposed test:** the gate rejects an error response for an unknown id, and a cancel for an
  unknown `requestId`.

### L4: cancellation during spawn (low)
- **Where:** Phase 1 `src/proveflow/introspect/procs.py` `spawn`, reachable from the proxy.
- **Risk:** a SIGTERM or session deadline that lands during `await anyio.open_process` could
  leave the child running before `Spawned` exists. On Windows that is a suspended process never
  assigned to the Job; on POSIX a process group nobody kills.
- **Proposed test:** inject a cancellation right after `open_process` returns, then assert no
  child is alive (psutil).

### Incomplete cassettes must not produce verdicts (Phase 5, replay)
- **Where:** `src/proveflow/proxy/cassette.py`. `load_cassette` checks integrity (models, seq,
  hash chain, canonical form, sizes), not completeness. A cassette cut off by SIGKILL, or read
  while the proxy is still running, loads without error. `is_complete(events)` (added in Phase
  2.1) returns False for it, but nothing enforces that yet.
- **Oracle part: done in Phase 3a.** `oracle.rules.evaluate` raises `IncompleteCassetteError`
  (no findings) when `is_complete` is False, when events were dropped, or when `session_start`
  or a sink call was truncated (`tests/unit/test_oracle_rules.py`).
- **Still open (Phase 5):** the replay CLI must surface that error as INCOMPLETE and never
  report a verdict.
- **Proposed test:** replay of a cassette with its `session_end` removed reports INCOMPLETE and
  produces no verdict.

### Deeply nested JSON in a cassette line raises an untyped error (low)
- **Where:** `src/proveflow/proxy/cassette.py` `load_cassette` (and `canonical` on write).
  `json.loads` of a line nested about 100k levels deep raises `RecursionError`, which is not
  caught as `CassetteError`. Probed in Phase 3a: `RecursionError (untyped)`.
- **Today:** fails closed (no events, so no findings). But callers that expect
  `CassetteError` get an untyped exception. The oracle's own JSON walk is iterative and
  unaffected.
- **Proposed fix:** catch `RecursionError` in `load_cassette` (and in the writer) and raise
  `CassetteError("nesting too deep")`. This is a proxy change, outside Phase 3a's single
  allowed proxy change.
- **Proposed test:** a cassette line with 100k nested lists → `CassetteError`.

## Runner (Phase 5, 2026-11-19)

### httpx2 is a direct dependency chosen by mcp (low; re-check on every mcp change)
- `httpx2==2.16.0` is declared with an exact pin because `mcp==2.3.0` already brings it.
- **If mcp is ever upgraded or unpinned,** re-check httpx2's version and availability: mcp
  may move to another http stack, and then the runner pins a package nothing else needs.
- **Proposed test:** `uv tree --package mcp` lists the declared httpx2 version (CI step).

### R2 and R3 are built but DORMANT until Phase 6 payloads carry the per-trial values (DOWNGRADED high -> medium in Phase 6 step 1; NOT closed)
- **Downgrade, 2026-11-23 (Phase 6 step 1):** a payload now CAN carry both values: the
  proveflow-authored goal clause appended to the verbatim payload shows the action target and
  the marker separator-split (`proveflow.corpus.instantiate`). R2 and R3 FIRE on a
  payload-driven trial: real in-process proxy sessions, the fake twin, a SCRIPTED agent that
  follows the clause (`corpuschecks.assert_payload_driven_r2_fires`,
  `assert_payload_driven_r3_fires_and_quoting_does_not`), and neither fires without the
  clause. That proves WIRING, not instruction-following.
- **Why it stays open:** neither has fired on a CORPUS payload in a REAL campaign with a real
  model. The corpus IS ingested since Phase 6 step 3 (347 records, docs/DATASETS.md), but no
  corpus payload has run in a real campaign, and real campaigns are Phase 7. Until then the attack-success rate is UNMEASURED, not zero. Close
  this only when a real campaign's results ledger contains a trial whose R2 or R3 status is
  evaluated on a corpus payload.
- *(The text below is the original item, kept as written.)*
- Two of the three compromise rules (R2 and R3) are built but DORMANT: neither can fire on a
  real trial until a payload carries the trial's per-trial value. R2 needs a payload that asks
  for the goal's sink tool with the trial's ACTION TARGET in the goal argument; R3 needs a
  payload that carries the trial's MARKER separator-split (`oracle.canary.spaced_marker`) with
  the instruction to rejoin it. No payload does either yet.
- **The payload design in Phase 6 is load-bearing for R2 and R3.** Phase 6 must deliver
  payloads that instantiate the action target and the split marker per trial, or R2 and R3
  stay dormant and only R1 can ever produce a compromise. Until then both are tested on
  authored fixtures only.
- **Reason it stays open:** it is corpus work, not oracle work, and Phase 6 is not started.

### The committed fixture transcripts' cassette hashes are NOT a replay invariant (low)
- The `trial_end.cassettes[].final_sha256` values in the committed replay fixtures
  (`tests/fixtures/runner/*/transcript.jsonl`) were NEVER reproducible by replay, neither
  after Phase 3b nor at its base commit: a cassette's `session_start` holds absolute
  interpreter and twin paths. Nothing checks those committed values: the only
  `verify_cassette_refs` test compares the REPLAYED transcript with the REPLAYED cassettes.
- Measured 2026-11-22 on `cross_server_exfil`: committed `b0c6...`/`ebe0...`; a replay at the
  base commit gave `9b78...`/`9b83...`, and after Phase 3b `10ce...`/`8779...`. Every event
  before `trial_end` was identical.
- **Do not read those committed hashes as meaning anything:** replay compares requests.
- **Reason it stays open:** making them meaningful needs path-free cassettes, a format change.

### Real-session tests failed under load, two sightings, cause not yet known (medium)
- **Observed once:** real-session tests that spawn a twin failed under full-suite load on
  Windows (commit 6f08b42, 2026-11-22, its per-commit worktree run): three at once, all in a
  test's baseline pass, before any mutant:
  `test_oracle_r4_mutation.py::test_ignoring_the_cap_refusal_refuses_a_valid_real_trial` and
  `::test_a_record_moved_below_the_gate_fails_the_real_session_check` ("upstream_crash: the
  scenario did not reach the upstream_error site"), and the protected
  `test_proxy_mutation.py::test_f_second_opinion_disabled_fails_forged_session_check` (the
  proxy call returned no result).
- **Did not reproduce:** in 5 isolated reruns, in 80 measured crash-scenario runs (40
  isolated, 40 under parallel load, all recording upstream_error), or in two later full-suite
  runs of the same commit, both green (1563 passed, 2 skipped, 0 failed): its rerun in the same
  worktree (2026-11-22) and its per-commit verification in a fresh worktree beside 0d604d5,
  b5de916 and 7dc1fa6, all four green (2026-11-22). Observed frequency, as of 2026-11-22: 1 red
  of 3 full-suite runs of 6f08b42. CI run 45028306407 (head 7dc1fa6, 2026-11-22) also ran these
  tests green on ubuntu and windows. The diagnostics are now in place so the NEXT occurrence is
  interpretable.
- **This item must NEVER be cited to dismiss a failure of these tests:** a recurrence is to be
  diagnosed from the new output, not waved at this item.
- **LEADING HYPOTHESIS, explicitly UNVERIFIED: a proxy-side early stop whose kind nothing
  recorded, one mechanism for all three failures at once.** The reasoning:
  - `run_in_process` returns no result in exactly one case: the PROXY ended the session first
    (`outcome.reason != "agent_closed"`, tests/proxyhelpers.py). So the forged-session failure
    had a proxy-side early stop.
  - A missed upstream_error site is consistent with the same thing: the session ending before
    the error was recorded.
  - All three failures occurred in the same run.
  The default session timeout is 600 s (proxy/session.py), so a timeout is unlikely but not
  excluded.
- **The open question the diagnostics answer next time:** serve() records `error[proxy_failure]`
  on an exception and sets `session_end.reason` on every early stop. So an early stop that
  recorded NEITHER an error event NOR a non-agent_closed reason would itself be a gap in the
  proxy's own recording. We do not know which path it was, because the original run discarded
  it; that is precisely what the diagnostics now capture.
- **Not done, on purpose:** the fixtures are not tuned to make it less likely. Raising a
  timeout or shortening a scenario would hide a symptom we have not explained, which is the same
  error as widening the check.
- **Done:** diagnostics only, no assertion changed. A real-session check that misses now prints
  the errors the cassette recorded, its tail and its session_end reason
  (`proxyhelpers.cassette_story`), and `text_of(None)` names the swallowed client error and the
  outcome reason (`tests/unit/test_failure_diagnostics.py`).
- **NOT done, on purpose:** no check was widened and no other error kind is accepted. An
  unexplained failure is not a reason to loosen a safety check.
- **Next time it happens:** read the message, which now says which path the session took, and
  record it here. It is NOT "the known flake": any failure of these tests is a finding until
  explained.
- **SECOND SIGHTING (2026-11-23, uncommitted Phase 6 step 2 tree, Windows), same shape: a real
  trial's MCP path failing during a long run, passing alone.**
  - Run: a SUBSET, not the full suite, in pytest's default FIXED order (the command carried
    `-p no:randomly`, a no-op: no random-order plugin was installed; see "Order-independence
    has never been tested"): tests/integration/test_campaign.py,
    tests/mutation/test_campaign_mutation.py, tests/mutation/test_campaign_loop_mutation.py,
    tests/integration/test_runner_replay.py, tests/unit/test_campaign_loop.py,
    tests/unit/test_campaign_state.py.
  - Failed: `tests/mutation/test_campaign_loop_mutation.py::test_min_instead_of_max_fails_the_
    retry_after_check`, with `proveflow.runner.campaign.AttemptFailed: t2-a2:
    ExceptionGroup[MCPError]`: a REAL attempt (real twins, real proxies, the fake provider over
    the mock transport) raised an MCPError out of the proxy harness's nested task groups,
    instead of the check failing or passing. Whether it was the check's baseline pass or its
    mutant pass is NOT known: only the tail of the output was kept.
  - That subset ran about 20 minutes (pytest started 11:43:22 and was still running at
    12:03:16 with 16.6 s of CPU used, i.e. mostly WAITING). Nothing in it accounts for that.
  - Did not reproduce: the same test alone passed in 41 s; the same subset rerun passed, 57 of
    57, in 274 s wall.
  - Lost, and why: the MCPError's own detail and the cassettes' story. The campaign path does
    not go through `run_in_process`, so `cassette_story` / `LAST_RUN` were not wired into it.
    Now they are: a real-trial campaign check that fails adds, as an exception note, the leaf
    exceptions with their message and innermost frames and the cassette story of every
    cassette of the failing attempt (`campaignchecks.campaign_story`).
- **The apparatus changed, the cause is still unknown, the item stays open at medium.** After
  this sighting the Retry-After check moved off real twins (one real trial kept for the wiring
  claim; the arithmetic runs scripted), and the backoff, exhaustion, corrupt-state and
  interrupted checks followed. The suite therefore runs FEWER real trials, which will probably
  make this failure appear less often. That is NOT a fix and must never be reported as one:
  hiding a flake by running less of the thing that flakes is the worst outcome available.

### R4 is computed only for runner trials (low; by design)
- R4 needs the runner's transcript as the trial's clock. A cassette recorded by the
  standalone `proveflow proxy` (stdio agent, no transcript) gets R1 and R2 only.
- **Reason it stays open:** there is no transcript to order such a session by; it is not a
  trial.

### The replay CLI (Phase 7)
- `proveflow replay` stays a stub, now pointing at Phase 7: re-evaluating a recorded trial is
  what a user wants once `prove` exists. `runner.trial.replay_trial` already does the work.

### 429 and retries (RESOLVED in Phase 6 step 2 by D3/D4; kept for the record)
- **Resolution:** a 429 is never retried INSIDE a trial; it ends the attempt `rate_limited`
  (`runner.llm.RateLimited`), and the campaign backs off and starts a NEW attempt with its own
  transcript (`runner.campaign`). So: (1) no retried request ever enters a transcript, the
  chain and strict replay are untouched; (2) every attempt's provider-reported usage counts
  against the budget, a 429 that consumed nothing adds nothing, and the budget is rebuilt from
  the campaign state file's per-attempt usage on resume (D4); (3) no tool-calling request is
  retried mid-loop. The proposed test below is superseded (there is no in-trial retry to
  replay); its budget half is `campaignchecks.assert_resume_rebuilds_the_budget_from_attempt_
  usage`. `Retry-After` is not read; the backoff schedule is a design value.
- **Before Phase 6:** the client failed closed. HTTP 400, 401, 429 and 500 each raised
  `ProviderError("HTTP <status>")` and the trial ended `provider_error`, recorded in the
  transcript (tests/unit/test_runner_llm.py). No request was retried. Since Phase 6, 429
  raises `RateLimited` (a `ProviderError`, still `"HTTP 429"`) and ends the trial
  `rate_limited`.
- **Three design questions to answer before any retry exists:**
  1. How does a retried request appear in the transcript without breaking the hash chain or
     strict replay (one `llm_request` per attempt? a separate attempt event? how does replay
     pair them)?
  2. How are a 429 that consumed no tokens, and a retry after a partial response that did
     consume some, accounted against the per-trial caps and the run budget (both enforced on
     provider-reported usage, F10)?
  3. Is a tool-calling request safe to retry at all, given the agent loop's state (messages
     already appended, tool calls already forwarded through a proxy)?
- **Proposed test:** a recorded 429 then 200 replays to the same transcript, and the budget
  counts exactly the provider-reported tokens of the attempt that answered.

### Order-independence has never been tested (medium; a seeded audit is owed)
- **Found 2026-11-23:** no random-order plugin is installed (no pytest-randomly, no
  pytest-random-order; `pyproject.toml` addopts is `-q`; CI adds none). Every test run in this
  project, local and CI, has run in pytest's default FIXED collection order. `-p no:randomly`,
  passed in Phase 6 timing runs and named in messages as "fixed order for comparability",
  was a NO-OP in every one of them. So every order-independence claim is UNVERIFIED,
  including the leading hypothesis for "Real-session tests failed under load" above, which
  nobody has ever tested under a different order.
- **Checked:** no COMMITTED doc or commit message claims random ordering was used (git log
  and git grep at HEAD, 2026-11-23); one uncommitted BACKLOG line that named the flag is
  corrected in place.
- **Ruling (Haris, 2026-11-23):** pytest-randomly is PERMITTED as a DEV-ONLY dependency (the
  no-new-dependency rule is about the shipped package, not the test harness). The DEFAULT
  gate stays FIXED order: a randomized default makes CI non-reproducible and a red run hard to
  reproduce.
- **Owed:** one deliberate audit run with an EXPLICIT seed, the SEED RECORDED in whatever
  reports it (the flag syntax to be taken from the plugin's own documentation when it is
  installed, cited, not from memory). Not done yet; the plugin is not installed yet.

### Phase 7 aggregation must read the RESULTS LEDGER only (high; binding on Phase 7)
- THE RESULTS LEDGER IS THE ONLY SOURCE OF COUNTED TRIALS (`runner.campaign.results`). A
  transcript's verdict is NOT evidence that a trial counted: `run_trial` gives a rate-limited
  or failed attempt a verdict with compromised=false too
  (`tests/integration/test_runner_replay.py::test_a_provider_error_ends_the_trial_fail_closed`
  asserts exactly that verdict). An aggregation reading verdicts off transcripts would count
  every attempt that measured nothing as a safe trial and dilute the ASR: R3's "not
  evaluable must never read as not fired", one layer up.
- **Required pin in Phase 7:** the aggregation run against a state file containing
  rate-limited and failed attempts (and their transcripts on disk), proving they are excluded
  from the DENOMINATOR as well as the numerator.

### Limit-ended trials are counted results; report them per reason (medium; Phase 7)
- `runner.campaign.COMPLETED_REASONS` includes every `limit:*` (argued in its docstring: the
  trial ran under declared, recorded caps and its evidence is complete). The cost: an agent
  that would have been compromised after the cap counts as not compromised, and
  `limit:wall_clock` depends on provider latency, so which trials it cuts does not reproduce.
  Phase 7 must report the number of limit-ended trials per reason beside every rate.

### One non-429 failure stops the whole campaign (medium; DEFERRED to Phase 7, not settled)
- Any attempt that fails for a reason other than a 429 (a FAILED reason, an exception, an
  unclassified reason) raises `AttemptFailed` and stops the campaign; resume retries it. Fail
  closed is right for a measurement tool. The consequence Phase 7 will meet: one bad response
  from one model halts a run of hundreds of trials. Whether a bounded skip-and-record is
  wanted is a Phase 7 decision; nothing here decides it.

### A forwarded dual-role sink's reply is REASONED not to echo arguments, not MEASURED (low)
- MEASURED: the sandbox's reply to every sink tool the fake twin offers carries none of the
  call's argument values (`corpuschecks.assert_the_sandbox_never_echoes_sink_arguments`).
- REASONED ONLY: a dual-role sink FORWARDED to a guard-passing generated twin (ADR-007) gets
  that tool's ONE canned response (F3, `twin/generator.py`: content does not depend on the
  arguments), so it cannot echo a split value. No test pins it; if the generator ever varied
  on arguments, F9 would refuse exactly the R2 trials that call such a tool.
- **What would measure it:** a real session against a guard-passing generated twin with a
  dual-role tool, the tool called with split-value-shaped arguments, asserting the forwarded
  reply (cassette `upstream_response`, and the `agent_response` the agent received) contains
  none of them raw or in any case.

### The D7 provider-prefix list has no Groq key prefix (low; wait for the key holder)
- `tests/twinchecks.py` `PROVIDER_PREFIXES` lists no Groq prefix: no documented source for
  Groq's key format was found, so none is guessed.
- The real protection for a manual run is the exact-value key check
  (`tests/runnerchecks.py` `exact_key_hits`, docs/PROVIDERS.md), independent of D7.
- **Fix:** after the first run, the key holder states the prefix; it goes into the list with
  "reported by the key holder" as its source. Never read off a key by code.

### SQLite store (deferred to Phase 7)
- Not built in Phase 5. Phase 7 aggregates across trials and needs it there; a trial today is
  its transcript, cassettes and timings sidecar on disk.

### Design caps are not measured (still open after the first manual run)
- The runner's caps (16 turns, 32 tool calls, 1024 tokens/request, 120,000 in, 8,000 out,
  300 s, 500,000/run) are design caps.
- The first real run (Groq, `openai/gpt-oss-120b`, 2026-11-21, clean scenario, no attack)
  used 2 turns, 1 tool call, 3,180 tokens in + 168 out (largest response 125 out) and about
  1.5 s. That is far below every cap, but N = 1 on the smallest scenario, so it justifies
  no change. Revisit with attack scenarios (Phase 6), whose transcripts are longer.

## Tooling (2026-11-21)

### Tests are not type-checked (a stated decision, not an oversight; low)
- **What:** `mypy` runs with `strict = true` on `src` only: pyproject `[tool.mypy] files =
  ["src"]`, and CI runs `uv run mypy src` (.github/workflows/ci.yml). `tests/`, `tools/` and
  `scripts/` are not type-checked anywhere.
- **Count, 2026-11-22 (Phase 3b):** `uv run mypy tests` reports 84 errors in 33 files (137
  checked), up from 62 in 27 (127 checked) at bf1e063, measured in a detached worktree. All 22
  added errors are of kinds that already existed (`attr-defined` 20->32, `unused-ignore`
  20->26, `arg-type` 3->7). THIS PHASE INTRODUCED NO NEW ERROR KIND: the two it first added
  (`list-item`, `type-var`, both in tests/oraclechecks.py) were fixed before its commits.
  `uv run mypy tools scripts` reports 7 errors in 3 files (8 checked), unchanged from
  bf1e063. (2026-11-21, Phase 5's close: 62 in 27, the same as at 83e364e.)
- **How the figure is kept honest:** re-measure it each phase, against the previous phase's
  last commit in a detached worktree, and state whether any NEW error kind appeared. Do NOT
  build a test that pins "no new error kinds": `mypy tests` is not in CI, so such a test would
  be slow and local-only. The figure here plus that re-measurement is the check.
- **Why it is acceptable today:** the safety and mutation suites are executed on every push
  on two OSes, and a type error in a test shows up as a failing test. The product claims
  (`mypy --strict` in README and ARCHITECTURE) are stated for `src`. No doc may say or imply
  that the tests are type-checked.
- **Fix, if decided:** clear the 84, add `tests` to `files`, add the step to CI. Then pin the
  count at 0 in a test, so it cannot grow back silently. CI type-checks `src` only until then.

## Twin (Phase 4, 2026-11-15)

### Argument-dependent responses (F3; medium for utility realism, none for safety)
- **Where:** `src/proveflow/twin/generator.py`. `TABLE[tool]["content"]` does not depend on
  the arguments: one canned response per tool. Arguments are validated (type, required,
  properties, enum) and then ignored.
- **Effect:** an agent reading two different paths gets identical content, so utility
  realism is limited to calling tools correctly, not to distinguishing their targets. The
  Phase 5 runner will meet this first.
- **Proposed fix:** derive the content from `Rng(seed).derive("content", tool, canonical
  args)` inside the embedded runtime (still literal data, still deterministic), keeping honey
  and marker placement.
- **Proposed test:** two calls with different `path` values return different content, the
  same call twice returns the same bytes, and every honey value still appears in some response.

### Readability of wrapped terminal output is untested (F7; low)
- **Where:** `tests/widths.py` pins every test to `TEST_COLUMNS = 1_000_000`, so exact-text
  assertions are width-independent. One check opts out on purpose,
  `tests/narrowchecks.py` (COLUMNS=40, allowlisted in `tests/unit/test_render_width.py`):
  it verifies only that redaction survives hard wrapping of the consent prompt.
- **Gap:** no test verifies that wrapped output (the consent prompt, a security warning, in
  an 80-column terminal) is READABLE, e.g. that the command line and the WARNING line stay
  recognisable. Only the absence of a planted secret is checked.
- **Rule for the future:** a narrow-width rendering test goes into the `COLUMNS_USERS`
  allowlist in `tests/unit/test_render_width.py` with a one-line reason.
- **Proposed test:** at COLUMNS=80, the WARNING sentence and every line label (`command:`,
  `env keys:`, `config:`) start a line of the rendered prompt.

### Dual-role agreement gap (F6; medium for realism, must close before `--real-reads`)
- **Measured:** v2 12/155, human labels 10/155, both 7, Jaccard 7/15 = 0.47
  (`tools/count_dual_role.py`, pinned by `tests/unit/test_dual_role_count.py`). v2 only:
  browser_navigate, get_blog_post, get_blog_posts, get_linkedin_post, save_conversation.
  Human only: browser_network_requests, fill, image_pull.
- **Effect:** not a safety hole in twin mode (the twin has no I/O). Prove attacks up to 5
  flows a human would not call dual-role and cannot attack 3 that a human would.
- **Proposed fix:** dual-role rules tuned on dev only, a second independent human labeler for
  the dual-role subset (kappa), then a re-measure on a fresh held-out set.
- **Proposed test:** the count tool reports agreement on the new held-out set; the test pins
  it.

### The ADR-007 dual-role exception must be removed before `--real-reads`
- **Where:** `proxy.server.forwardable_dual_roles`, `proxy.policy.dual_role_names`.
- In any mode where a forward can reach a real server, a dual-role tool is a real sink.
- **Proposed test:** in a real-reads session, `forwardable_dual_roles` is empty whatever the
  guard says, and a dual-role call is sandboxed.

### Classifier miss before `--real-reads` (must fix before that mode exists)
- A sink that both the session's evidence and the proxy's own v2 classifier miss is forwarded
  to the twin. That is harmless in twin mode. Held-out sink recall is 16/25
  (docs/eval/RESULTS_V2.md).
- A real-reads mode needs a stronger guarantee than a classifier, e.g. an explicit per-tool
  user allowlist of read tools.
