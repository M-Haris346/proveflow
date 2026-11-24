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

### Real-session tests failed under load, three sightings; a twin's MCP handshake never completes (HIGH)
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
    `-p no:randomly`, a no-op: no random-order plugin was installed then; see "Order-independence:
    ONE seeded audit"): tests/integration/test_campaign.py,
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
- **THIRD SIGHTING (2026-11-23), the first with its evidence on disk.** Commit `e848da4`'s
  per-commit verification (a fresh detached worktree at a 140-character path) was RED on one
  test: `tests/mutation/test_campaign_mutation.py::test_rebuilding_the_budget_from_completed_
  trials_fails_the_resume_check`, in its BASELINE pass (before any mutant). In the D4 pin's
  first campaign run the REAL attempt `t1-a2` raised `ExceptionGroup[MCPError]` with 0 tokens,
  the campaign stopped there, and the check's premise assertion fired. The same code passed
  that test in the next commit's worktree (`8d06675`, green). The run took 1852 s against
  ~730 s for a normal full suite.
  - NEW EVIDENCE (the attempt's transcript and both cassettes, read from pytest's surviving
    temp directory): the transcript holds ONLY `trial_start` (the agent never sent its first
    LLM request: the trial never left proxy startup). The `filesystem` proxy recorded
    `session_start` then `session_end[session_timeout]`, with NO `tools_advertised` and no
    agent request: its twin never completed the MCP `initialize` handshake. The `fetch` proxy
    initialized fully (`tools_advertised`, initialize, `tools/list`) and then waited to the
    same `session_timeout`. NEITHER proxy recorded an error event. `SESSION_TIMEOUT_S = 600.0`
    (proxy/session.py), which fits 1852 s and the second sighting's ~20 minutes.
  - **HYPOTHESIS, NARROWED (still unverified):** under load, a twin's initialize handshake
    never completes, so the session runs to its 600 s timeout. The proxy records no error
    because nothing FAILED: it waited. When the session ends, the harness's MCP connection
    closes and the trial raises `MCPError` out of the harness's nested task groups. This
    replaces the earlier "unrecorded proxy-side early stop" with a findable thing.
  - **STILL UNKNOWN:** WHY the twin hangs (Windows subprocess scheduling, a pipe or buffering
    race in the twin's stdio start, the SDK's initialize path under load: none tested).
  - **Severity raised medium -> HIGH:** it has now cost a per-commit verification, and in
    Phase 7 every occurrence would cost a PAID campaign trial plus 600 s of wall clock.
  - **Diagnostics gap closed in the same change:** the D4 pin EXPECTS an `AttemptFailed`, so
    it caught the exception and the failure story attached to it was never printed; the cause
    was found only because pytest's temp directory survived. Every check that catches an
    expected exception and then asserts on state now fails with the caught exception's story
    (`campaignchecks.premise_failed`, `oraclechecks._RealEvents.story`; pinned by
    `tests/unit/test_campaign_loop.py::test_a_caught_expected_exception_still_tells_its_story`).
  - **PREREQUISITE for Phase 7's FIRST PAID CAMPAIGN (a sequencing constraint, not a note):
    a HANDSHAKE timeout, separate from the session timeout.** If a twin has not completed
    `initialize` within N seconds, the proxy records an error event naming the twin and the
    stage and fails fast. That turns a 600 s silent hang into a named, recorded error
    diagnosable in seconds, and it is a smaller change than chasing Windows subprocess
    scheduling. N is a design value to be chosen with evidence. Not built in Phase 6.
    **No paid campaign runs before it exists and is tested**: at HIGH and unfixed, a silent
    600 s hang mid-campaign burns wall clock and can strand a paid trial with nothing to show
    for it. "Run the campaign first and fix it later" does not satisfy this item.
  - **CORRECTION (2026-11-24) to the sentence this replaced**, which said the resume path
    "would then charge that attempt its FULL reservation". That was WRONG for this failure: a
    hung-handshake attempt leaves a READABLE transcript (`trial_start` only), so the campaign
    charges it the usage that transcript records, 0 tokens (`usage_source` `transcript`). The
    full-reservation charge (`unknown_spend_charge`) applies only to an attempt whose
    transcript is UNREADABLE. Measured, not argued:
    `handshakechecks.assert_the_campaign_files_a_handshake_timeout_as_a_failure` pins
    `("failed", None, "ExceptionGroup...", "transcript", 0)` and a budget ledger of 0. The real
    cost of the hang was wall clock (600 s per occurrence) and a stranded attempt, not tokens.
  - **BUILT (Phase 7.0, 2026-11-24) [impl][tested], OFFLINE; the item STAYS OPEN.** A
    per-stage handshake deadline, `HANDSHAKE_TIMEOUT_S = 30.0` (proxy/session.py), separate
    from the 600 s session timeout, over three stages: `spawn`, `initialize`, `tools_list`
    (`proxy.cassette.HANDSHAKE_STAGES`, one literal). There are two layers, and each is
    mutation-tested with the other off (`tests/mutation/test_handshake_mutation.py`):
    - **Proxy layer:** `serve()` moves its cancel-scope deadline to `now + 30 s` at each
      stage start. When that stage deadline (not the session's) fires, the session ends
      `handshake_timeout` with `session_end.handshake_outstanding` naming the stage. A
      `handshake_stage` event records each stage `started` and `completed` (cassette schema
      4; a v3 cassette is refused).
    - **Harness layer:** `running_proxies` bounds the agent-side startup by
      `startup_bound_s(30) = (3 + 1) × 30 × 1.5 = 180 s`, derived from the constant and not
      a literal. It raises `ProxyStartupTimeout` if the proxy never answers. Its bound
      exceeds the proxy's `3 × 30 = 90 s`, so the proxy names the stage first (the layering
      is mutation-tested too).
    Elapsed ms per stage are in the NON-EVIDENCE timings sidecar (`handshake_ms`), never the
    cassette (ADR-008). A handshake timeout is filed FAILED via `Attempt.exception`, never a
    result, and writes no `trial_end`. The AST scan of trial_end reasons stays at 12, exact.
    **What this is:** the hang is now VISIBLE, BOUNDED (30 s per stage instead of 600 s per
    session) and NAMED (which stage, in the cassette). **What it is NOT:** a fix. WHY a twin's
    handshake stalls under load is still UNKNOWN (the candidates above are untested). The
    deadline was triggered in tests by INJECTED hangs (a patched spawn, a `--hang-initialize`
    fake twin, a patched `tools/list`), never by the real load hang, which has not recurred
    since and has not been reproduced. 30 s is a design value: an unloaded twin starts in
    about 2 s here (measured while writing the tests, not a stored run), and it is not tuned
    on evidence from the real hang. Next occurrence: read `handshake_outstanding` and the
    sidecar's `handshake_ms`, and record them here.
  - **Still THREE sightings (2026-11-24).** Two sessions of the same cassette shape in a run
    made while the machine was in Modern Standby do NOT count: their cause is known. See "The
    session timeout does not hold across Modern Standby".
  - The push of `e848da4` rests on `8d06675`'s green run over a superset of the same code plus
    CI on both OSes, NOT on a re-run of `e848da4`: a re-run that happened to be green, recorded
    as its verification, would be "intermittent, on record", which is refused.

### Full-suite wall time is COMPLETELY SEPARATED by power source (OBSERVATION; cause NOT measured; medium)
- **Upgraded 2026-11-24, after the per-commit verification.** Nine valid full-suite runs on
  the dev machine, all in fixed order, split into two groups with NO OVERLAP. Each figure is
  given with its run, its test count, and which clock it is:

  | power | run | tests | seconds |
  |---|---|---|---|
  | AC | per-commit verification, b395736 (on AC until 20 s before the end) | 1715 | 534 (script; pytest's own 528.86) |
  | AC | per-commit verification, 1cfc7cc | 1758 | 592 (script; pytest's own 588.22) |
  | AC | per-commit verification, dde9c48 | 1758 | 607 (script; pytest's own 602.43) |
  | AC | gate 1, working tree | 1758 | 834 (gate wall) |
  | battery | per-commit verification, 70c025e | 1718 | 974 (script; pytest's own 968.64) |
  | battery | gate 2, working tree | 1758 | 1075 (gate wall) |
  | battery | gate 3, working tree | 1758 | 1107 (gate wall; pytest's own 1104.18) |
  | battery | order audit, seed 20261124 | 1758 | 1157 (wall; pytest's own 1154.68) |
  | battery | per-commit verification, 745388d | 1739 | 1322 (script; pytest's own 1315.08) |

  The slowest AC run (834 s) is faster than the fastest battery run (974 s). Restricted to the
  1758-test runs, it is still separated: AC 592-834, battery 1075-1157. Calling this a
  coincidence understates it. Excluded, as NOT valid: the standby run (36,271.99 s) and the
  low-memory 1cfc7cc run (1028 s on battery, ruled INVALID; it falls inside the battery range
  but is not counted).
- **The cause is still NOT measured.** CPU frequency and the active power plan were not
  recorded in any of these runs. The AC group also spreads by 834 vs 592-607 s on the same 1758
  tests, which is unexplained too. **What would measure it:** sample the CPU clock frequency and
  record the active power plan throughout each run, then run ONE commit back to back,
  alternating AC and battery several times with nothing else changed. The GitHub runners have
  no battery, so their times are the only external comparison.
- **Earlier record (kept as written at the time; the figures are in the table above).**
  Observed 2026-11-24, Windows, the dev machine, fixed order, Phase 7.0-7.2 working tree,
  three sequential full gates: 834 s, 1075 s and 1107 s (the gate's wall seconds; pytest's
  own figure was 1104.18 s for the third). Between them only two test files' TEXT differed:
  `tests/fixtures/fake_twin.py`, one docstring line, and
  `tests/safety/test_tools_never_imported.py`, the tool names it uses. All 1758 tests ran in
  every gate.
- **What the new tests account for:** the 7 new test files take 141 s run alone, so they
  explain 141 s of the growth from 1715 tests (about 674-790 s before) to 1758. They do NOT
  explain the extra ~250 s of the second and third gates over the first.
- **POWER CHECK (retroactive, 2026-11-24, read from the event log only; nothing re-run).**
  Each run's window was taken from the run's own log file (its NTFS creation and last-write
  times), and each one matches, to the second, the session transcript's timestamp for the
  launch and the completion notification. Gate 1 ran 01:38:04-01:52:00, gate 2
  01:57:22-02:15:19, gate 3 02:23:40-02:42:09, the seed-20261124 audit 02:42:09-03:01:28 (it
  started when gate 3 ended, in the same script; its log's creation time, 02:15:19, is kept
  from the stopped attempt the file overwrote), and the 141 s timing run inside
  03:08:27-03:12:31 (the transcript's launch and result).
  - **No standby or sleep in any of them.** There is NO Kernel-Power 506, 507, 42 or 107 in any
    window, or anywhere from 00:00 to 03:41:00. The log is complete over that stretch: its
    oldest event is 2026-09-01, it holds 8 other System events between 01:38 and 03:12, and
    the last such power event before it is 2026-11-23 23:29:14. So the variance is NOT
    standby.
  - **The POWER SOURCE changed in the gap where the timing jumped** (Kernel-Power 105,
    AcOnline): AC from 2026-11-23 23:30:22, BATTERY from 2026-11-24 01:53:18, AC again from
    13:33:14. Gate 1 (834 s) ran on AC. Gate 2 (1075 s), gate 3 (1107 s), the audit (1157 s)
    and the 141 s timing run ran on BATTERY.
  - **What that is and is not (SUPERSEDED by the upgrade at the top of this item):** a
    coincidence in timing between battery power and the slow runs, with ONE run on AC. It is NOT a measured cause: CPU frequency and the power plan were
    not recorded, and no run on AC was repeated. It also means the 141 s for the new files was
    measured on battery, so their cost on AC is unknown, probably lower. The observation stands
    as "three runs on battery were 29-39% slower than the one on AC" until runs on the same
    power source are compared.
- **Related:** "Real-session tests failed under load" above, also unexplained timing
  behaviour on this machine. The spread matters because the 600 s foreground limit has
  already been hit once, and every run on AC with 1758 tests is near or over it. A slow run is
  not evidence of the handshake hang (that hang now ends a session as `handshake_timeout`
  with the stage named), and a fast one is not evidence against it. See also "The matcher's
  15 s bound has a thin margin on battery" below.

### The matcher's 15 s bound has a thin margin on battery (OBSERVATION; medium; Haris rules)
- **The bound:** `tests/unit/test_oracle_matcher.py:203`, `PERF_BOUND_S = 15.0`, asserted at
  `:223` by `test_pathological_one_mib_input_completes_within_bound`. It is a DOCUMENTED safety
  claim: `docs/ORACLE.md:337-339` says a 1 MiB string with 300 distinct separators "must
  complete within 15 s", measured at 2.19 s locally.
- **Measured 2026-11-24, per-commit verification, valid runs only (each figure is the test's
  junit time):**
  - AC: 2.00 s (1cfc7cc), 2.00 s (dde9c48), 2.71 s (b395736, on AC until 20 s before the end),
    a margin of 7.5x at best and 5.5x at worst;
  - battery: 10.84 s (70c025e) and 10.92 s (745388d), a margin of only **1.37x** at worst
    (15.0 / 10.92; 1.38x for 10.84).
- **Not evidence, and excluded:** the 32.65 s breach in the first b395736 run happened under
  Modern Standby (ruled INVALID). The 9.93 s in the low-memory 1cfc7cc run was also ruled
  INVALID.
- **Why it matters:** a documented safety bound with a 1.37x margin is one slow machine away
  from a FALSE breach. A GitHub runner is not this laptop, and its time for this test has not
  been read.
- **CI, run 45386319527 (head 0ce2abe, 2026-11-24): the test PASSED on both runners, but its
  time is NOT RECORDED.** CI runs `uv run pytest --cov -rs` (`.github/workflows/ci.yml`), which
  prints neither per-test durations nor a junit file, and the run has 0 artifacts. Neither job
  log contains the test's name. So the only CI fact is the assertion itself: under `--cov`, the
  matcher took under 15.0 s on ubuntu-24.04 and on windows-2025. That gives a margin of more
  than 1.0x and says nothing beyond it. The non-laptop margin is still UNMEASURED. Measuring it
  needs a CI change (for example per-test durations or a junit artifact), which is Haris's
  ruling and is not made here. For scale only, not the matcher: pytest's own suite time was
  450.03 s on windows-2025 and 499.93 s on ubuntu-24.04, with coverage on, against 574-607 s
  locally on AC without coverage.
- **OPEN QUESTION, Haris's ruling, NOT in this pass:** should the bound be raised, the input
  shrunk, or the measurement made load-independent? Nothing is changed here, and the test and
  `docs/ORACLE.md` stay as they are.

### The session timeout does not hold across Modern Standby (HIGH; a 7.3 PRECONDITION)
- **OBSERVATION (2026-11-24, Windows laptop, the first per-commit verification of b395736,
  ruled INVALID by Haris):** the machine was in Modern Standby (S0 low-power idle) from 03:41:45
  to 13:33:14, apart from a few seconds at 09:30:49-09:30:54 (Kernel-Power events 506, 507, 42
  and 107 in the System log). Two in-process proxy sessions were opened inside that window, and
  both had the default `SESSION_TIMEOUT_S = 600.0`:
  - `test_max_calls_counts_sandboxed_and_forwarded`: cassette created 03:47:09, five seconds
    after standby began at 03:47:04. `session_end[session_timeout]` was written at 09:30:53,
    when the machine left standby at 09:30:49: 5 h 43 m 44 s of wall clock for a 600 s
    timeout.
  - `test_per_call_timeout_returns_error_and_proxy_keeps_serving`: cassette created 09:30:54.
    `session_end[session_timeout]` was written at 13:33:19, five seconds after the wake at
    13:33:14.
  - Both cassettes hold only `session_start` and `session_end`, with no `tools_advertised` and
    no error event. The fake twin's log shows that the `initialize` request WAS received.
  The 600 s did not hold on the wall clock: each session ended only once the machine woke.
  Whether the process was frozen or the clock did not advance is NOT known; no theory is
  offered. Also NOT measured: the 30 s handshake deadline (Phase 7.0) under standby. It is
  set on the same clock and is assumed to behave the same until measured.
- **This is NOT sighting 4.** "Real-session tests failed under load" stays at THREE sightings.
  A cassette shaped like sighting 3 (session_start, session_end[session_timeout], nothing
  between) under a KNOWN cause, the machine in standby, is a different thing from an
  unexplained one, and must not be counted with them or cited to explain them.
- **Why it matters for money:** a paid campaign on a laptop that enters standby would produce
  spurious `session_timeout` trials. Those attempts are PAID and measure NOTHING.
- **PRECONDITION for Phase 7.3 (a sequencing constraint, not a note):** before any paid
  campaign, EITHER standby is disabled for the run, OR the campaign detects a power event and
  marks the affected attempts INVALID instead of counting them. The mechanism is NOT designed
  here; this records the requirement only.
- **Verification has the same problem, and it is now guarded:** the per-commit verification
  script (kept in the scratchpad, not committed) reported this standby run as a RED commit.
  It now reads those four Kernel-Power events immediately before and after each pytest run. It
  prints a run that spans any of them as INVALID, not red, and does not advance. It also flags
  any run over three times the expected ~19 min as SUSPECT, even with no power event.
- **The guard was still too narrow, and has grown (2026-11-24):** the next verification reported
  1cfc7cc as RED on a run with no power event. The failure was a `MemoryError` in the same second
  Windows logged low virtual memory (see "Every config read allocates 32 MiB" below), and Haris
  ruled that run INVALID too. The script now also reads
  Microsoft-Windows-Resource-Exhaustion-Detector event 2004 over each pytest window, and treats
  the string `MemoryError` anywhere in the pytest output as an environmental signal. Either one
  makes the run INVALID, with the evidence printed. It also records the power source
  (Kernel-Power 105, plus the last one before the run) and free memory before each pytest run.
- **Which commits need their own per-commit verification (Haris's ruling, 2026-11-24; recorded
  so it is not re-argued):** a DOCS-ONLY commit whose tree is fully contained in a verified
  green commit needs no separate verification. A CODE commit ALWAYS gets its own, even when a
  later green commit contains it, because a bisected code state has its own behaviour and a docs
  state does not. First applied to 95be02a, a docs-only BACKLOG commit contained in 0ce2abe
  (verified green alone): accepted as covered.

### Every config read allocates 32 MiB, whatever the file's size (medium; a REAL code finding; NOT fixed)
- **Exposed by a machine condition, not by a test written for it:** the low-memory verification
  run of 1cfc7cc (2026-11-24, ruled INVALID) is what surfaced this. In that run,
  `tests/mutation/test_group_mutation.py::test_dropping_a_member_is_refused` failed at its sanity
  scan, before any mutation was applied, with `MemoryError` at `src/proveflow/discover/_io.py:32`,
  `fh.read(MAX_CONFIG_BYTES + 1)`. The file being read was a small test fixture. The test's
  `tmp_path` was created at 15:02:40.514. At 15:02:41 Windows logged
  Resource-Exhaustion-Detector 2004: system commit charge 39,191,642,112 of 39,287,246,848
  bytes (99.76%). 1cfc7cc touches neither that test nor `src/proveflow/discover/` (the diff
  against 745388d on those paths is empty), so the commit is not the cause. The cost is in the
  reader itself.
- **Measured (2026-11-24, CPython 3.12.10, the project venv, `tracemalloc`):** on an 18-byte
  file, `read(33554433)` returned 18 bytes with a traced peak of 33,563,338 bytes, while
  `read(19)` peaked at 8,924 bytes. `MAX_CONFIG_BYTES` is `32 * 1024 * 1024` (`_io.py:19`). So
  a 200-byte config costs a 32 MiB allocation, and discovery can fail under memory pressure for
  no benefit.
- **A second, related fact from the code:** `load_json_config` catches only `OSError`
  (`_io.py:42`). A `MemoryError` therefore propagates out of discovery, although the module
  docstring (`_io.py:1`) says loading "never crashes". The test above saw exactly that path.
- **Intended shape (NOT designed further here):** stat the file first and refuse anything over
  the cap. Then read only `st_size + 1`, and keep the read bounded. The cap is a SAFETY limit and
  must stay enforced, including when the file grows between the stat and the read: a read that
  returns more than `st_size` bytes must not be accepted silently.
- **Needs its own commit with its own named test** (plus a mutation test, per the rules). It is
  NOT fixed in the Phase 7.0-7.2 pass.

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

### Order-independence: ONE seeded audit, green (medium; more seeds owed)
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
  installed, cited, not from memory).
- **Installed (Phase 7.0, 2026-11-24):** `pytest-randomly==5.1.0`, dev group only (uv.lock:
  one package, depending on pytest). The flag syntax is from the plugin's own README
  (https://github.com/pytest-dev/pytest-randomly/blob/main/README.rst, and
  https://pypi.org/project/pytest-randomly/): `--randomly-seed=N` fixes the seed, `-p
  no:randomly` disables the plugin, and the header prints `Using --randomly-seed=N`. The
  DEFAULT gate stays FIXED order: `pyproject.toml` addopts is `-q -p no:randomly`. MEASURED,
  not documented: a later `-p randomly` re-enables it, and the header then prints `Using
  --randomly-seed=20261124` and `plugins: randomly-5.1.0`.
- **AUDIT RUN (2026-11-24), SEED 20261124: GREEN.** The command was `uv run pytest -rs -p
  randomly --randomly-seed=20261124`. The working tree was Phase 7.0–7.2, uncommitted, on top
  of 163547c, on Windows. Result: 1756 passed, 2 skipped (the two POSIX-signal tests,
  tests/safety/test_proxy_safety.py:390 and :395), 0 failed, 1758 collected; pytest 1154.68 s.
  The order really changed: collected with that seed, 0 of 1758 test ids are at their
  fixed-order position (the same set). The fixed-order gate on the same tree just before it:
  1756 passed, 2 skipped, 0 failed, 1104.18 s.
- **Power-checked retroactively (2026-11-24, event log only):** the audit ran 02:42:09-03:01:28
  and gate 3 ran 02:23:40-02:42:09. Neither window holds a Kernel-Power 506, 507, 42 or 107
  event, so neither run spanned standby or sleep, and both greens stand. Both ran on BATTERY
  (Kernel-Power 105, AcOnline=false from 01:53:18), which affects their wall times, not their
  results ("Full-suite wall time swings").
- **What it does NOT establish:** order independence in general. It is ONE permutation, and
  the plugin shuffles modules and the tests inside each module; it does not interleave tests
  across modules. It is Windows only; CI has not run an audit. It also says nothing about the
  twin-handshake hang, which did not recur in it. The item stays open (medium): further seeds,
  and an audit on CI, are owed before anyone claims the suite is order-independent.

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
- **PINNED (Phase 7.2, 2026-11-24):** `enginechecks.assert_aggregation_reads_only_the_results_
  ledger`: a state with one rate-limited and one failed attempt (the failed one's scripted
  verdict is compromised=true, so counting it would raise the numerator too), 8 transcripts
  on disk for 6 counted trials. `runner.report.aggregate` takes a state and no path. The
  mutant that counts one per attempt (one per transcript, the same thing) fails it
  (`tests/mutation/test_engine_report_mutation.py`). Kept open as the binding rule it is.

### Limit-ended trials are counted results; report them per reason (medium; Phase 7)
- `runner.campaign.COMPLETED_REASONS` includes every `limit:*` (argued in its docstring: the
  trial ran under declared, recorded caps and its evidence is complete). The cost: an agent
  that would have been compromised after the cap counts as not compromised, and
  `limit:wall_clock` depends on provider latency, so which trials it cuts does not reproduce.
  Phase 7 must report the number of limit-ended trials per reason beside every rate.
- **Built (Phase 7.2, 2026-11-24) [impl][tested]:** each source row carries `ended_by`, its
  counted trials per end reason, printed beside the rate; a mutant folding `limit:*` into
  `final_answer` fails the aggregation check. The cost above is unchanged: reporting the
  count does not recover what a cap cut off.

### One non-429 failure stops the whole campaign (medium; DEFERRED to Phase 7, not settled)
- Any attempt that fails for a reason other than a 429 (a FAILED reason, an exception, an
  unclassified reason) raises `AttemptFailed` and stops the campaign; resume retries it. Fail
  closed is right for a measurement tool. The consequence Phase 7 will meet: one bad response
  from one model halts a run of hundreds of trials. Whether a bounded skip-and-record is
  wanted is a Phase 7 decision; nothing here decides it.
- **Phase 7.1 (2026-11-24) kept fail closed:** the engine runs cells through `run_campaign`
  unchanged, so one non-429 failure still stops it with the state saved
  (`enginechecks.assert_the_engine_fails_closed`). The skip-and-record decision is still
  open, and must be made before 7.3.

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
