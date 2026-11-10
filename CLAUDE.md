# CLAUDE.md — proveflow contract

Read `docs/ARCHITECTURE.md` before any work. It is the source of truth for scope, components, and phases.

## Workflow (non-negotiable)
1. One phase at a time, in order from ARCHITECTURE.md §9. Never start the next phase uninvited.
2. Start every phase in **plan mode**: files to create/change, tests to add, dependencies (with justification), exit criteria. Wait for Haris's approval.
3. Implement code **and** tests together. Show real command output (pytest, ruff, mypy, CLI runs). Never summarize a run that did not happen.
4. Haris commits and pushes himself. Do not run `git commit` / `git push`. Suggest Conventional Commit messages.
5. After each phase: update README status block and ARCHITECTURE.md phase table with honest tags.

## Honesty rules
- Tags: [impl] [tested] [measured] [planned] [research]. Never upgrade a tag without evidence in the repo.
- No invented numbers. Every metric in README/site comes from a stored run ID reproducible by one command.
- Report N, model + provider version, temperature, corpus revision, proveflow version, hardware with every number.
- `NOT REPRODUCED` never means "safe". Twin limitation stated in every prove/verify report.
- Never claim enterprise usage or "production-ready".
- If a test is skipped or a live run was not executed, say so explicitly.
- Facts about external tools (client config paths, permission syntax, dataset licenses, provider limits) must come from official docs cited in `docs/`; never from memory.

## Engineering rules
- Python 3.12, `uv`, `ruff`, `mypy --strict`, `pytest`, `hypothesis`. Pydantic v2 models at every boundary.
- Windows is the dev machine: `pathlib` only, no shell-specific scripts in library code; CI runs ubuntu + windows.
- Primary verdicts are deterministic code. LLMs only for optional, separately reported, user-confirmed suggestions.
- Structured logging (stdlib `logging` + JSON formatter). No `print` in library code; CLI output via Rich.
- Every new reader, redaction rule, encoder, carrier, rule, or mitigation ships with unit tests and at least one mutation test.

## Safety rules (this tool reads secrets and attacks agents)
- Redact secrets at read time. Raw env values, headers, tokens never reach logs, cassettes, reports, or LLM prompts.
- Never edit a user's client config. Fixes are written as separate patch files for review.
- Never send `tools/call` to a real server in default mode. Introspection = `tools/list` only, with per-server consent and timeout.
- Sink sandbox always ON in twin mode. Sink calls are never forwarded.
- Payloads target only per-trial canaries and honey values. No real exfil endpoints, no format-valid card/ID numbers.
- Raw datasets never committed. Fetch at runtime, pin revision + checksum, record license per record.
- Real flaws found in third-party servers: report privately to maintainer first.

## Commands (fill in as they exist)
- `uv run pytest` · `uv run ruff check .` · `uv run ruff format --check .` · `uv run mypy src`
- `uv run proveflow --help`
