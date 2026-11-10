# Phase 0 — Foundation plan (proveflow)

Goal: a repo where every later phase can start immediately — tooling, CI, CLI skeleton, typed domain models, and **verified external facts** (client config paths, permission syntax, dataset licenses, provider tool-calling support). No feature code.

Estimate: 2–3 days part-time.

## A. Done by Haris (manual, before Claude Code)
1. Create public GitHub repo `M-Haris346/proveflow` (empty, no template README).
2. Clone on Windows, open in VS Code, copy in `CLAUDE.md` + `docs/ARCHITECTURE.md` + this file.
3. Confirm git identity uses noreply email (`git config user.email`).
4. First commit yourself: `docs: add architecture, contract, phase 0 plan`.
5. Open Claude Code: *"Read CLAUDE.md and docs/ARCHITECTURE.md. Enter plan mode for Phase 0 using docs/PHASE0_PLAN.md."*

## B. Tooling (Claude Code)
| File | Content |
|---|---|
| `pyproject.toml` | uv + hatchling, `src/` layout, Python `>=3.12,<3.14`, entry point `proveflow = "proveflow.cli:app"`; runtime deps: `typer`, `rich`, `pydantic>=2`; dev deps: `pytest`, `pytest-cov`, `hypothesis`, `ruff`, `mypy` |
| `uv.lock` | committed |
| `ruff` config | lint + format, import sorting, `S` (bandit) rules on |
| `mypy` config | `strict = true`, pydantic plugin |
| `.github/workflows/ci.yml` | matrix ubuntu-latest + windows-latest, Python 3.12; steps: `uv sync --locked`, ruff check, ruff format --check, mypy, pytest with coverage |
| `.gitignore`, `.editorconfig`, `LICENSE` (MIT, same as other repos) | |
| `README.md` | one-paragraph pitch, **Status: Phase 0 — nothing usable yet [planned]**, link to ARCHITECTURE |

Dependency rule: nothing else added in Phase 0. MCP SDK, LiteLLM etc. come in their phases with justification.

## C. CLI skeleton
- `proveflow --version`, `proveflow --help`.
- Subcommands registered but returning exit code 2 with "not implemented yet (Phase N)": `discover`, `scan`, `prove`, `fix`, `verify`, `replay`. Honest stubs, no fake output.
- Logging setup module (JSON formatter, `--log-level`, logs to stderr).

## D. Core domain models `src/proveflow/core/`
Pydantic v2, frozen where possible, `extra="forbid"`:
- `ClientKind` enum, `ClientConfig`, `ServerSpec` (env as `dict[str, RedactedValue]` — type makes raw values impossible to store), `RedactedValue` (sha256 prefix + length only)
- `ToolRole` enum, `RoleEvidence` (source: heuristic|override|llm_confirmed, reason, weight), `ToolSpec`
- `Flow`, `FlowClass` enum (exfil|action|leak), `FlowVerdictKind` enum (CONFIRMED|NOT_REPRODUCED|THEORETICAL)
- `Payload`, `Carrier` enum, `Goal` (discriminated union: exfil|action|hijack), `Attack`
- `Trial`, `Verdict`, `RuleHit` enum, `RunMeta` (model, provider, temperature, seed policy, corpus revision, proveflow version, hardware, timestamps)
- `Mitigation`, `MitigationKind` enum (M1–M6)

Tests:
- Round-trip JSON for every model; JSON Schema export snapshot test (`tests/unit/test_schemas.py`) so accidental schema changes fail CI.
- `RedactedValue` property test (Hypothesis): for any string secret, `str()`, `repr()`, `model_dump_json()` of a `ServerSpec` never contain the secret.
- Validation tests: invalid enums/extra fields rejected.

## E. Verification research (written into docs, with links + access date)
Claude Code must fetch official docs, not rely on memory. Haris reviews each table.
1. **`docs/CLIENT_CONFIGS.md`** — for Claude Desktop, Claude Code (user + project), Cursor (user + project), VS Code, Windsurf: config file path per OS (Windows/macOS/Linux), JSON shape for stdio + HTTP servers, env/header fields, precedence rules. Source link per row.
2. **Permission syntax** (for mitigation M3) — how Claude Code (and Cursor/VS Code if available) express deny/ask rules for a specific MCP tool. Source link.
3. **`docs/DATASETS.md`** — LLMail-Inject, InjecAgent, BIPIA, AgentDojo: license, size, format, download location, revision to pin, redistribution allowed?, decision (use / drop / use-with-attribution).
4. **Provider table** (in `docs/METHODOLOGY.md` appendix) — Groq, Gemini, Cerebras, OpenRouter free models, Ollama: which models support tool calling, current free-tier limits (with date; marked "changes often"), LiteLLM provider string.

## F. Docs v0
- `docs/METHODOLOGY.md` v0 — oracle rules R1–R4, FlowVerdict definitions, paired design, statistics, threats to validity (twin realism, goal rewriting, static corpus vs adaptive attackers, model drift).
- `docs/THREAT_MODEL.md` v0 — threats **to proveflow and its user**: malicious MCP server during introspection, secret leakage from configs, payloads reaching real sinks, poisoned datasets, malicious cassette files on replay, supply chain (deps). Each → control → planned test.
- `docs/COMPETITORS.md` — table from research (Snyk agent-scan, mcp-red-team, mcp-tripwire, taintgate ×2, Agent3Sigma-Canary, agentprobe, mcpsafe, spikee, Promptfoo, Claude Code built-ins) with what each does, what proveflow does differently, and what they do better. Honest.
- `docs/adr/` — ADR-001 scope & non-goals · ADR-002 SQLite over Postgres · ADR-003 twin mode default, no real `tools/call` · ADR-004 deterministic oracle, no LLM judge for primary verdict · ADR-005 never edit user configs (patch files only).

## G. Exit criteria (all required)
- [ ] CI green on ubuntu + windows (link to run).
- [ ] `uv run proveflow --version` works; stubs exit 2 with honest message.
- [ ] `ruff`, `mypy --strict` clean; model + schema + redaction property tests pass (real output shown).
- [ ] CLIENT_CONFIGS, permission syntax, DATASETS, provider tables filled with source links + access date; Haris reviewed.
- [ ] Any dataset with unclear/incompatible license marked DROP.
- [ ] README status says Phase 0, nothing usable.
- [ ] Haris commits (suggested split): `chore: tooling and CI` · `feat(core): domain models` · `feat(cli): skeleton with honest stubs` · `docs: methodology, threat model, competitors, ADRs, verified external facts`.

## H. Mistakes to avoid
- Writing discovery code before CLIENT_CONFIGS is verified.
- Adding MCP SDK / LiteLLM now "to save time".
- Stubs that print fake results.
- Copying config paths or license claims from blogs instead of official sources.
- Squatting the PyPI name with an empty package — publish only when v0.1 (Phase 1) does something real.
