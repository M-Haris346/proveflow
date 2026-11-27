# proveflow: status in detail

The phase-by-phase status that was the README's "Status in detail" section until 2026-11-27, moved here verbatim EXCEPT that three relative links were repointed for this file's location (`docs/eval/RESULTS.md` -> `eval/RESULTS.md`, `docs/eval/RESULTS_V2.md` -> `eval/RESULTS_V2.md`, `docs/results/groq_forced_7db7eff3b652.md` -> `results/groq_forced_7db7eff3b652.md`); README.md links to it.

> **Phase 1 (Find) done. Phase 2 (Proxy), Phase 3a (Oracle) and Phase 4 (Twin) [impl][tested].
> Phase 5 (Runner) closed. Not released.**
>
> - `proveflow discover` [impl][tested]: reads Claude Desktop, Claude Code (user/local/project),
>   Cursor (user/project), VS Code (workspace), and Windsurf configs, plus `--servers FILE`.
>   Secrets are redacted at read time (docs/REDACTION.md). VS Code user-profile config is
>   reported *unsupported* (path not verified).
> - `proveflow scan --no-launch` [impl][tested]: static flow map from server names/commands only
>   (low confidence; nothing is started). `--json`, and `--sarif` (SARIF 2.1.0, validated
>   against the official OASIS schemas in tests). Every flow is THEORETICAL.
> - `proveflow scan` (introspection) [impl][tested with a fake MCP server on Windows and in CI;
>   verified once on the author's real Windows machine]:
>   - per-server consent; `--yes` does not cover project-scoped servers (`--yes-project`)
>   - `tools/list` only, with a method allowlist that blocks `tools/call`
>   - the process tree is killed (Windows Job Object; POSIX process group)
>   - minimal env and an empty temp cwd; no executables from the cwd or project
>   - servers with unresolved variables are not launched
>   - tool-change detection against a per-user cache; PF-UNPINNED notes
>   - **Real-machine check (1b exit):** run by the author with 1 real stdio server.
>     Consent yes gave `ok`; consent no gave `declined`. `scripts/leak_check.py` was clean
>     both times. Output is not committed.
> - Role-classifier baseline [measured, once]: results are in
>   [docs/eval/RESULTS.md](eval/RESULTS.md). Test N = 40, dev N = 60 tools, from 13
>   servers (12 of 14 planned collected).
>   - **Caveat:** the test split is mostly reference servers, dev recall is about 0.2-0.3, and
>     the labels are LLM pre-labels reviewed by the author. There is no independent human
>     second labeler, so no kappa.
>   - Test has only 1 `untrusted_source` positive.
>   - Read the caveats in RESULTS.md before quoting any number.
> - Role classifier v2 [measured, once, on a fresh held-out set]: rules tuned on dev only,
>   results in [docs/eval/RESULTS_V2.md](eval/RESULTS_V2.md). held-out (55 tools, 7
>   servers, single blind human labeler): sink recall 8/25 -> 16/25, mostly one rule (C1) on
>   one server; private_data recall 4/20 for both; 10 of 13 v2 rules untested; large
>   dev-to-held-out gap.
> - Fixed after the real-machine run:
>   - servers discovered but in no profile (e.g. another project's Claude Code local entry)
>     are now listed as `skipped` with a reason, no longer dropped silently (THREAT_MODEL T16)
>   - `--json` is written as UTF-8 on Windows whatever the console code page
> - Flow grouping [impl][tested] (scan report schema 2): the table shows one row per group of
>   flows with the same (class, source server, private server, sink server) across profiles;
>   `--limit` counts groups. **Grouping reduces table rows, not the number of tool paths**:
>   every flow is still in `--json` and `--sarif`, and per-path triage is Prove (Phase 7).
>   Rules and limitations: docs/ARCHITECTURE.md §5.3.
> - `proveflow proxy --session FILE` (Phase 2) [impl][tested, against a fake twin only]: a stdio
>   MCP proxy that serves ONE twin upstream to an agent (docs/ARCHITECTURE.md §5.5,
>   docs/adr/ADR-006-proxy-default-deny.md).
>   - the upstream must be this Python interpreter running a script inside proveflow's own twin
>     directory, whose sha256 matches the session (the hashed copy is what runs); npx, uvx,
>     node, docker, URLs and any other `.py` file are refused before anything starts. This does
>     not prove a script placed in that directory is harmless
>   - the session lists classified tools, never allow/deny decisions; the proxy computes the
>     policy itself (default deny: only role-classified, non-sink, tool-level tools) and also
>     runs its own classifier on what the twin advertises: a tool it calls a sink is never
>     forwarded; look-alike names (e.g. with a zero-width space) are denied together. Every
>     other `tools/call` gets a sandbox reply; a second check on the write path blocks
>     independently. No flag, env var or session field disables this
>   - 5 injection carriers for source results; hash-chained JSONL cassette with a validating
>     loader; per-call / session / call-count limits plus message and cassette-size caps;
>     fails closed
>   - tested only with a fake twin written for the tests: no real server, no network, no LLM, no
>     agent loop. Windows locally and in CI; the POSIX kill tests run only in CI (run
>     `43582905272`, ubuntu job: not skipped, 0 failed; that run also repeated both POSIX kill
>     tests 10x each, all green, after a test race was fixed).
>     Residuals: a sink that both the session's labels and the proxy's classifier miss (the
>     twin describes it innocently; held-out sink recall is 16/25) is forwarded to the twin,
>     harmless in twin mode but must be closed before any real-reads mode; fetch-a-URL sources
>     count as sinks (since Phase 4 they are forwarded only to a twin that passed the twin
>     guard, see below); two low-severity items (L3, L4) are listed in docs/BACKLOG.md
> - Oracle, Phase 3a [impl][tested] (docs/ORACLE.md): canary generator; a deterministic
>   matcher for 10 encodings (raw, case, zero-width, separator, URL, base64, hex, rot13,
>   reversed, JSON-escaped); rule R1 (canary in a call the proxy sandboxed as a sink) and R4
>   (review only) over a validated cassette; incomplete cassettes give no verdict. No LLM.
> - Oracle, Phase 3b [impl][tested on authored fixtures only] (docs/ORACLE.md): R2 (the
>   trial's minted action target in the goal argument of the goal tool's sink call), R3 (the
>   trial's minted marker, carried separator-split, rejoined in the final answer; raw + casefold
>   only; not evaluable without a final answer), R4 across a trial's cassettes in the runner
>   transcript's order. **Zero real positives:** every real trial so far has compromised=false,
>   so every rule is validated only against fixtures authored here, which shows the rule
>   matches our model of the attack, not that it catches real model behaviour. R3 is a
>   capability-dependent lower bound, not comparable across models. Nothing measured
> - Twin, Phase 4 [impl][tested, local only: Windows, both shells; CI not yet run on it]
>   (docs/ARCHITECTURE.md §5.4, docs/adr/ADR-007-dual-role-twin-exception.md):
>   - one self-contained, deterministic twin script per server (five imports, no proveflow
>     import; same tool names, descriptions and input schemas; 6 response archetypes; fake
>     data; honey values in private-data tools; a per-tool marker)
>   - honey and canaries are rejection-sampled against a structural T4 rule (no 12-digit
>     run, no NINO shape): canary space 47.9895 bits (|S| = 279,426,400,710,656), honey
>     63.9762 bits (|S| = 18,145,465,120,237,551,616), counted exactly by
>     `tools/count_t4_space.py`
>   - the oracle now searches for the canary and every honey value, and also checks dual-role
>     tools (e.g. fetch) that the proxy forwards only to a twin passing the AST no-I/O guard.
>     That guard is not a sandbox; this exception must not survive into any real-reads mode
>   - tested on twins generated from stored metadata (no server launched except the generated
>     twins, no network, no LLM): fetch (injection + canary R1), filesystem (honey R1 by a
>     scripted agent; no source tool, so not an injection chain), pg-mcp-guard (0 sink tools:
>     no exfiltration is possible, reported as a finding about the server)
>   - limitation: one canned response per tool (arguments are validated, never varied on)
>   - `proveflow twin --from SCAN.json --profile ID --out-dir DIR` [impl][tested on synthetic
>     scans]: one twin and one proxy session per introspected server; refuses a `--no-launch`
>     scan, an out-dir outside the twin directory and any existing file; prints to stderr only
> - Agent runner, Phase 5 [impl][tested on replay; one real trial] (docs/ARCHITECTURE.md
>   §5.6, docs/adr/ADR-008-auditable-not-reproducible.md, docs/PROVIDERS.md):
>   - one agent wired to N twin proxies, one OpenAI-compatible client, a hash-chained
>     transcript with strict replay, design caps on provider-reported usage, and a validity
>     guard (the attack arrives only through tool results)
>   - every test replays a recording; no test calls a provider (a network guard enforces it)
>   - **closed 2026-11-21** by its exit criterion. One real trial, run by the key holder on
>     Groq `openai/gpt-oss-120b`, scenario `clean_utility` (no attack): final answer,
>     utility true, compromised false, 3180 tokens in + 168 out. The transcript passed the
>     exact-key check and the evidence check and is committed under
>     `evidence/provider-runs/`. A strict offline replay (`tools/replay_evidence.py`, run
>     by hand, never a test) reproduces its verdict.
>     N = 1 and no attack, so no attack-success rate is measured
>   - the run found two things no hand-authored recording had shown. First, the model
>     Groq's docs name returned 404 on that account (availability is per account). Second,
>     real tool-call ids are `fc_<uuid>`, which the D7 scan flagged; they are now excluded
>     at five exact paths, and the four proveflow constructs must pass an echo check
>   - residuals: the caps are design values, not measured (docs/BACKLOG.md); 429 handling
>     added in Phase 6 step 2
> - **Phase 6 complete (2026-11-23; docs/ARCHITECTURE.md §9). Phase 7 is next.** Payload
>   instantiation and the goal clause, 429 / backoff / resumable campaign state (OFFLINE
>   only: fake provider, scripted agents; nothing paid, ASR unmeasured, not zero), and the
>   corpus: 347 records measured at pinned revisions (BIPIA attack files 250, InjecAgent 62,
>   AgentDojo 35 at upstream benchmark v1.2.2; MIT on every record; 72% BIPIA, so Phase 7
>   must stratify or report per source; docs/DATASETS.md). LLMail-Inject is not ingested
>   pending a ruling. FakeLLM policies are forbidden by D7 (Phase 5,
>   docs/ARCHITECTURE.md §5.6).
> - **Phase 7.0–7.2 [impl][tested] (2026-11-24), OFFLINE only: scripted model side, nothing
>   paid, no provider call; CI green on both OSes (run below).** A per-stage handshake
>   deadline (30 s; spawn, initialize, tools_list) that makes the twin-handshake hang VISIBLE,
>   BOUNDED and NAMED in the cassette. Its cause is unknown and it is NOT fixed. The campaign
>   engine: an equal-per-source seeded sampler and a six-cell scripted smoke campaign with a
>   429, a kill and a resume. The report: results ledger only, per-source Wilson 95%, no pooled
>   figure, the lower-bound note beside the numbers.
> - **Phase 7.3a [impl][tested] (2026-11-24), OFFLINE only: the paid-campaign PATH, built and
>   dry-run; nothing paid, no provider call; CI run 45446488249 on a6b8b27.**
>   - **Plans:** one plan file per campaign (`campaigns/`) feeds both the scripted dry run and
>     the paid run. Every refusal is tested with a mutation: missing cap, cap over the ceiling or
>     under one trial, missing limits, another template, another provider, a missing key, another
>     plan's state file, a root under docs/results/, no `--yes`.
>   - **Preflight:** it prints the measured request bytes, the estimate with its arithmetic, and
>     the published price with its URLs and read date.
>   - **Report:** EXPOSURE is read from the attacked server's cassette. Every report gives TWO
>     rates per source, END-TO-END and DELIVERED, and never one "ASR"; low exposure is a
>     reachability finding.
>   - **Runbook:** docs/RUNBOOK_7_3.md.
>   - **Not built, by ruling:** a suspend detector. The clock-based design is a no-op on
>     Windows. For the first, short, watched campaign, the run's event-log output must be
>     pasted with its report, or the report is not accepted. The trigger for building a
>     detector is in docs/BACKLOG.md.
> - **Phase 7.3b [measured, once] (2026-11-25): the first paid campaign, forced plan only.**
>   - `groq_forced_7db7eff3b652`, 30 counted trials: 0 compromised, exposure MEASURED 30 of 30,
>     per source 0/10 END-TO-END and DELIVERED, Wilson 95% [0.000, 0.278]
>     ([docs/results/groq_forced_7db7eff3b652.md](results/groq_forced_7db7eff3b652.md)).
>   - The 2a07305 fix: a provider response without usage is now charged the full reservation.
>   - Control A (`8003eb1`) [impl][tested]: the matched-pair positive control. It is
>     [tested] on the 30 real cells ONLY locally, because it needs the uncommitted corpus cache.
>     CI runs it on a 3-cell synthetic plan.
>   - What the 30 zeros are, and are not, is in the STATUS block above. ZERO REAL POSITIVES.
>   - NOT done: the incidental plan (`groq_incidental`), Finding 1's per-trial column, the
>     report's provenance fields (docs/BACKLOG.md).
> - **Phase 8 [impl][tested] (2026-11-26): Fix + Verify, measured against the CONTROL.**
>   - Exit criterion, as Haris ruled it, because there is no confirmed flow from a real model:
>     the control's rate falls to 0 on the new template's cells under FLOW BLOCKED, with
>     exposure and utility retained. MET locally for M1 and M3 (STATUS block above).
>   - `fix` [impl][tested on fixture configs]: M1 and M3 patch files for review, from the scan
>     report only. A user config is never opened, and a safety test pins its bytes and mtime.
>   - `verify` [impl][tested; measured on the control only]: paired halves, three figures and a
>     mechanism label per row. A label edited by hand, or a report missing its CONTROL note, is
>     refused by the report's own validator.
>   - The new template `fs_notes_exfil` gets its source role by an OVERRIDE. That is a recorded
>     Find-stage DEFECT with a BACKLOG item, not a template quirk: the classifier never calls a
>     filesystem read tool an untrusted source, so `scan` cannot discover file-borne injection
>     (measured: 0 such flows without the override, 11 with it). Its plan has never run against
>     a provider.
>   - NOT built: M2, M4, M5 (a scripted client never reads the prompt), M6; Newcombe CI; verify
>     against a real model. OPEN, HIGH: a full verbatim re-read of Claude Code's MCP rule
>     syntax, by hand, before M3 is relied on.
> - **Phase 9 [impl][tested] (2026-11-26): Ship. CLOSED 2026-11-27 by Install evidence run
>   `45880776283` (see the CI paragraph below).**
>   - `scan --fail-on` with the exit codes above. Each error status has its own named test, and
>     a mutant that turns an error into 0 or 3 is killed.
>   - The GitHub Action and its self-test workflow.
>   - The installers, tested against a stub uv, plus the `Install evidence` workflow
>     (wheelhouse route).
>   - The STATIC version `0.1.0a1`, with a tag check. It is a package version, never a commit
>     identifier. hatch-vcs was rejected as MEASURED (docs/BACKLOG.md).
>   - Measured blind spot: the Action sees 3 of the toxic fixture's 16 introspected flows, and
>     0 of the blind-spot fixture's 3.
>   - NOT done: a PyPI release (ruled: not in Phase 9); the default install route in CI; the
>     config-status field in the JSON (BACKLOG, HIGH).
> - Everything else is [planned]. No releases.
