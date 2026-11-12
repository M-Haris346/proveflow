# proveflow

**Find → Prove → Fix → Verify** for the MCP tool setup you actually run.

Your agent is connected to many MCP servers. Some combinations let an attacker who controls
*one* tool output steal data through *another* tool. Static scanners say "this might be risky" —
proveflow is being built to *prove* it: discover your installed MCP setup, map cross-server toxic
flows, attack each flow in a safe schema twin with real-world injection payloads, let a
deterministic oracle decide whether the agent was hijacked, then propose a fix and measure the
attack-success-rate change after applying it.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full design, scope, and phase plan.

## Status

> **Phase 1 (Find): checkpoint 1a done; checkpoint 1b introspection built, classifier eval not
> started. Not released.**
>
> - `proveflow discover` [impl][tested]: reads Claude Desktop, Claude Code (user/local/project),
>   Cursor (user/project), VS Code (workspace), and Windsurf configs, plus `--servers FILE`.
>   Secrets are redacted at read time (docs/REDACTION.md). VS Code user-profile config is
>   reported *unsupported* (path not verified).
> - `proveflow scan --no-launch` [impl][tested]: static flow map from server names/commands only
>   (low confidence; nothing is started). `--json`, and `--sarif` (SARIF 2.1.0, validated
>   against the official OASIS schemas in tests). Every flow is THEORETICAL.
> - `proveflow scan` (introspection) [impl][tested on Windows with a fake MCP server; POSIX
>   path tested in CI only]:
>   - per-server consent; `--yes` does not cover project-scoped servers (`--yes-project`)
>   - `tools/list` only, with a method allowlist that blocks `tools/call`
>   - the process tree is killed (Windows Job Object; POSIX process group)
>   - minimal env and an empty temp cwd; no executables from the cwd or project
>   - servers with unresolved variables are not launched
>   - tool-change detection against a per-user cache; PF-UNPINNED notes
>   - **It has not yet been run against your own real servers (step 1b exit).**
> - Role-classifier precision/recall: **not measured yet**. The eval server set is proposed in
>   docs/eval/SERVERS.md; nothing has been collected or labeled. No numbers exist.
> - Everything from Phase 2 on is [planned]. No releases.

CI (`.github/workflows/ci.yml`, ubuntu + windows) runs on push. Last checked run:
`43059686222` on commit `3b66868`, green on both OSes (ubuntu: 327 passed, 14 skipped, all
Windows-only tests; windows: 341 passed). This README states CI results only for a run id
checked with `gh run list`. Local commands:

```bash
uv sync
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest --cov -rs
```

## License

MIT
