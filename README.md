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

> **Phase 0 (Foundation) done — nothing usable yet.**
>
> What exists: tooling, CLI skeleton with honest stubs, typed core models with tests
> [impl][tested], and verified external-fact docs (CLIENT_CONFIGS, DATASETS, provider table).
> No command does anything beyond printing an honest "not implemented yet" message.
> No numbers, no results, no releases. Everything else in ARCHITECTURE.md is [planned].

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
