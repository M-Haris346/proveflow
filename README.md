# proveflow

**Find → Prove → Fix → Verify** for the MCP tool setup you actually run.

Your agent is connected to many MCP servers. Some combinations let an attacker who controls
*one* tool output steal data through *another* tool. Static scanners say "this might be risky" —
proveflow is being built to *prove* it: discover your installed MCP setup, map toxic flows inside
each agent profile (exfil, action, or informational leak; cross-server flows ranked first), attack
each flow in a safe schema twin with real-world injection payloads, let a
deterministic oracle decide whether the agent was hijacked, then propose a fix and measure the
attack-success-rate change after applying it.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full design, scope, and phase plan.

## Status

> **Phase 1 (Find) done. Phase 2 (Proxy) [impl][tested]. Not released.**
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
>   [docs/eval/RESULTS.md](docs/eval/RESULTS.md). Test N = 40, dev N = 60 tools, from 13
>   servers (12 of 14 planned collected).
>   - **Caveat:** the test split is mostly reference servers, dev recall is about 0.2-0.3, and
>     the labels are LLM pre-labels reviewed by the author. There is no independent human
>     second labeler, so no kappa.
>   - Test has only 1 `untrusted_source` positive.
>   - Read the caveats in RESULTS.md before quoting any number.
> - Role classifier v2 [measured, once, on a fresh held-out set]: rules tuned on dev only,
>   results in [docs/eval/RESULTS_V2.md](docs/eval/RESULTS_V2.md). held-out (55 tools, 7
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
>   - the upstream must be this Python interpreter running a `.py` twin; real servers (npx, uvx,
>     node, docker, URLs) are refused before anything starts
>   - default deny: only role-classified, non-sink, tool-level tools are forwarded; every other
>     `tools/call` gets a sandbox reply and is never forwarded; a second check on the write path
>     blocks independently. **The sandbox cannot be disabled** (no flag, env var or config)
>   - 5 injection carriers for source results; hash-chained JSONL cassette with a validating
>     loader; per-call / session / call-count limits; fails closed
>   - tested only with a fake twin written for the tests: no real server, no network, no LLM, no
>     agent loop. Windows locally; the POSIX kill tests run only in CI (not yet run for Phase 2).
>     Residual: a sink mislabeled by the classifier is forwarded to the twin (harmless in twin
>     mode; must be closed before any real-reads mode)
> - **Next:** Phase 3 (Oracle).
> - Everything from Phase 3 on is [planned]. No releases.

CI (`.github/workflows/ci.yml`, ubuntu + windows) runs on push. Last checked run:
`43493526715` on commit `13d1900`, green on both OSes (ubuntu: 572 passed, 14 skipped, all
Windows-only tests; windows: 586 passed). That run predates Phase 2: the proxy tests have not
run in CI yet. This README states CI results only for a run id checked with `gh run list`. Local commands:

```bash
uv sync
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest --cov -rs
```

## License

MIT
