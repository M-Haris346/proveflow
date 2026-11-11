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

> **Phase 1 (Find), checkpoint 1a done — config-only scan works; introspection not built yet.**
>
> - `proveflow discover` [impl][tested]: reads Claude Desktop, Claude Code (user/local/project),
>   Cursor (user/project), VS Code (workspace), and Windsurf configs, plus `--servers FILE`.
>   Secrets are redacted at read time (docs/REDACTION.md). VS Code user-profile config is
>   reported *unsupported* (path not verified).
> - `proveflow scan --no-launch` [impl][tested]: static flow map from server names/commands only
>   (low confidence, no server is started), with `--json` and `--sarif` (SARIF 2.1.0, validated
>   against the official OASIS schemas in tests). Every flow is THEORETICAL.
> - `proveflow scan` without `--no-launch` (tools/list introspection) is [planned], checkpoint 1b.
> - Role-classifier precision/recall: **not measured yet** (checkpoint 1b). No numbers exist.
> - Everything from Phase 2 on is [planned]. No releases.

This repo is currently local-only (no GitHub remote). The CI workflow in
`.github/workflows/ci.yml` is written but has **never run**; the identical checks are run
locally instead:

```bash
uv sync
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest --cov
```

## License

MIT
