# proveflow — Architecture & Build Plan

> **Find → Prove → Fix → Verify** for the MCP tool setup you actually run.
> Status legend used everywhere in this repo: **[impl]** implemented · **[tested]** tested · **[measured]** number produced by a stored run · **[planned]** not built yet · **[research]** FYP/experimental, may fail.
> Everything below is **[planned]** until a phase marks it otherwise.

---

## 1. One-line pitch

Your agent is connected to many MCP servers. Some combinations let an attacker who controls *one* tool output steal data through *another* tool. Static scanners say "this might be risky". **proveflow proves it**:

1. **Find** — discover your installed MCP setup and map cross-server toxic flows (untrusted source → private data → sink).
2. **Prove** — attack each flow in a safe **schema twin** of your servers with real-world injection payloads; a deterministic oracle decides if the agent was hijacked. Result: `CONFIRMED` / `NOT REPRODUCED` / `THEORETICAL`, with attack success rate (ASR) and confidence interval.
3. **Fix** — propose a concrete mitigation (patch file, never auto-applied).
4. **Verify** — re-run the same attacks with the fix and show the ASR change, paired and significance-tested.

```bash
proveflow discover                          # find MCP configs on this machine (secrets redacted)
proveflow scan                              # static toxic-flow map, no LLM, SARIF output
proveflow prove --model groq/<model-id>     # dynamic exploit confirmation in twin mode
proveflow fix   --flow F3                   # write mitigation patch for review
proveflow verify --flow F3                  # re-run attacks with fix applied in twin
proveflow replay runs/<run-id>              # deterministic re-check from cassette, zero LLM cost
```

Install target (Phase 9): `uv tool install proveflow`, `uvx proveflow`, `pipx install proveflow`, plus one-line installers (`curl -LsSf <site>/install.sh | sh`, PowerShell `irm <site>/install.ps1 | iex`) that install `uv` then the tool.

## 2. Problem, market reality, positioning

**Problem.** Agents read untrusted content through tools. Indirect prompt injection is unsolved at the model level. Risk is not one server — it is the *combination* of servers a user connects.

**How MCP is governed today (research 2026-11):** client-side allowlists (Claude Code / Copilot managed settings), gateways (Docker MCP Gateway, Kong, MintMCP), registries (catalogue only), manual review checklists, runtime guardrails from big vendors. No source we read described **adversarial testing of an MCP setup before approval**.

**Existing tools (see `docs/COMPETITORS.md` for full table):**
- Static: Snyk agent-scan (ex-Invariant mcp-scan) discovers installed configs, static toxic-flow analysis.
- Dynamic harnesses on their own mocks: SrihaasaK/mcp-red-team (proxy + deterministic oracle + CIs), rishii-hub/mcp-tripwire (proxy + CI gate), antgroup/Agent3Sigma-Canary (research framework, LLM judge).
- Defenses: Nikita3005/taintgate, rudratoshs/taintgate (provenance gates).
- General injection kits: spikee, Promptfoo (OpenAI-owned since Mar 2026).
- Claude Code: permissions, auto-mode classifier, bash sandbox, `/security-review` (code diff), managed MCP allowlists. Anthropic docs: does "not security-audit or manage any MCP server".

**proveflow's position:** the bridge none of them close — *static finding on your real setup → safe dynamic proof → fix → measured re-verification*, with real human-written attack data instead of synthetic payloads.

**Realistic users:** individual developers with many MCP servers, **MCP server authors (CI)**, small AI startups, AI pentest consultants, researchers. **Not** enterprises directly (they buy bundled vendor platforms). Never claim enterprise use.

**Non-goals:** certifying "safe"; runtime production firewall (use a gateway); SaaS dashboard; auth/multi-tenant; jailbreak/toxicity testing; attacking systems the user does not own.

## 3. Core concepts

| Concept | Meaning |
|---|---|
| **ClientConfig** | One discovered MCP client config file (Claude Desktop, Claude Code, Cursor, VS Code, Windsurf, or `--servers file`). |
| **ServerSpec** | A configured server: name, transport, command/url, env **keys only** (values redacted), source file. |
| **ToolSpec** | Name, description, input schema, server, **roles** ⊆ {`untrusted_source`, `private_data`, `sink`}, role provenance (heuristic / override / LLM-suggested-and-confirmed). |
| **Flow** | Ordered path `source tool → (private tool) → sink tool`, possibly across servers. Severity class: `exfil` (source+private+sink), `action` (source+sink), `leak` (private+sink with no source = misuse, informational). |
| **Twin** | Mock MCP server generated from real `ToolSpec`s: same names/schemas/descriptions, deterministic synthetic responses, honey secrets, injection slots. |
| **Payload / Carrier / Goal / Attack** | Attack text (with provenance + license) × embedding method × attacker objective, instantiated with per-trial canary. |
| **Trial** | (flow, attack \| none, model, mitigation, seed) → trajectory → verdict. Every attacked trial has a clean twin (same seed). |
| **Verdict** | `utility`, `compromised`, `rule_hit`, `blocked_by_mitigation`, tokens, latency. |
| **FlowVerdict** | Per flow: `CONFIRMED` (≥1 compromise and ASR CI lower bound > 0), `NOT REPRODUCED` (0 compromises in N trials; report upper CI bound — absence ≠ safety), `THEORETICAL` (static only, not tested). |
| **Mitigation** | Candidate fix from catalog, rendered as reviewable patch + twin-applicable policy. |

## 4. Architecture

```mermaid
flowchart LR
  subgraph FIND["Find (no LLM)"]
    DISC[discover<br/>client config readers<br/>+ secret redaction]
    INTRO[introspect<br/>tools/list only, no tool calls]
    ROLE[role classifier<br/>heuristics + overrides]
    GRAPH[flow graph<br/>cross-server paths]
  end

  subgraph PROVE["Prove"]
    TWIN[schema twin servers]
    CORPUS[(corpus<br/>LLMail-Inject, InjecAgent,<br/>BIPIA, AgentDojo-derived)]
    PX[interception proxy<br/>sink sandbox + cassette]
    AG[agent runner<br/>LiteLLM loop / command adapter]
    ORA[deterministic oracle]
  end

  subgraph FIXV["Fix + Verify"]
    CAT[mitigation catalog]
    PATCH[patch writer<br/>never auto-applies]
    VER[paired re-run<br/>McNemar + CI diff]
  end

  STORE[(SQLite run store<br/>+ cassettes)]
  REP[reports<br/>terminal, HTML, JSON,<br/>SARIF, JUnit]
  SITE[Next.js site<br/>docs + published results]
  LLM[(free API tiers /<br/>local small model)]

  DISC --> INTRO --> ROLE --> GRAPH
  GRAPH --> TWIN
  CORPUS --> PX
  AG <--> PX <--> TWIN
  AG <--> LLM
  PX --> STORE --> ORA --> STORE
  GRAPH --> CAT --> PATCH
  CAT --> VER --> PX
  STORE --> REP --> SITE
  GRAPH --> REP
```

### 4.1 Prove-trial sequence

```mermaid
sequenceDiagram
  participant E as Campaign engine
  participant A as Agent (model under test)
  participant M as Mitigation layer (optional)
  participant P as Interception proxy
  participant T as Schema twin
  participant O as Oracle

  E->>T: start twin(flow, seed, honey secrets)
  E->>P: arm(attack, canary=cnry_7f3a9c)
  E->>A: user task + system prompt + tools (via P)
  loop agent loop (max steps, timeout)
    A->>M: tool call
    M->>P: tool call (or BLOCK)
    alt sink tool
      P-->>M: sandboxed fake success (never forwarded)
    else other tool
      P->>T: forward
      T-->>P: synthetic result
      P->>P: inject payload via carrier at source tool
      P-->>M: result
    end
    M-->>A: result
  end
  P->>E: cassette (all events, raw + transformed)
  E->>O: evaluate(cassette, goal, utility check)
  O-->>E: verdict
```

## 5. Components

### 5.1 Discovery `discover/`
- Readers per client: Claude Desktop, Claude Code (user + project scope), Cursor (user + project), VS Code (`mcp.json`), Windsurf; plus explicit `--servers path`. **Exact file paths and formats per OS are verified from official docs in Phase 0 and recorded in `docs/CLIENT_CONFIGS.md`; nothing is hard-coded from memory.**
- **Redaction (security-critical):** env values, headers, URL query strings, args matching secret patterns are replaced with `<redacted:sha256-prefix>` at read time; raw values never enter logs, reports, cassettes, or LLM prompts. Unit + property tests.
- Read-only: proveflow never edits a client config. Mitigations are written as separate patch files.

### 5.2 Introspection `introspect/`
- To get tool schemas, proveflow must start each configured server and call `tools/list` — which executes that server's code, exactly as the user's client already does. Default asks consent per server; `--no-launch` skips introspection (flows from names/descriptions in config only, lower confidence).
- **Never calls `tools/call` on real servers** in default mode. Timeout + process kill per server. Captured specs cached with hash; description changes between runs are flagged (rug-pull signal).

### 5.3 Role classifier + flow graph `flows/`
- Roles from deterministic heuristics: verbs/nouns in tool name + description + schema (e.g. `send|post|write|delete|create|upload|exec` → sink; `fetch|read_url|search_web|list_issues|read_email` → untrusted_source; `query|read_file|get_secret|list_customers` → private_data). Weights and reasons recorded per tool.
- User overrides in `proveflow.toml` (highest priority). Optional LLM role suggestion: shown to user, counts only after confirmation, stored with provenance.
- Graph: all ordered (source, private?, sink) combinations across servers. Ranking: cross-server first, then sink severity (external network > write > local), then classifier confidence. Output table + SARIF.
- Classifier quality is itself **measured** (Phase 1): hand-labeled set of tools from public MCP servers → precision/recall per role.

### 5.4 Schema twin `twin/`
- Generates a FastMCP server per real server: identical tool names, descriptions, input schemas.
- Responses: deterministic, seeded. Each tool gets a **response archetype** (email list, document/file text, DB rows, web page, issue/ticket, generic JSON) chosen by heuristics or override; filled with synthetic data (seeded Faker-style generator), honey secrets in private-data tools, and an injection slot in untrusted-source tools.
- Arguments are validated against the real input schema (agent must call tools correctly — utility realism).
- **Honest limitation:** twin behavior is not the real server's behavior. Twin proves *the agent + tool surface* is exploitable, not that the real server returns exploitable content. Documented in every report.
- **Real read-only mode** [planned v1, opt-in]: forward non-sink calls to real servers; requires explicit `--real-reads` + per-server consent; warning that real data goes to the model provider; recommends local model.

### 5.5 Interception proxy `proxy/`
- Agent-facing MCP server, upstream-facing MCP client (official `mcp` Python SDK). stdio first; Streamable HTTP later.
- **Sink sandbox (default ON, cannot be disabled in twin mode):** sink-role tool calls are never forwarded; proxy returns plausible fake success and records args for the oracle.
- Injection at source-tool results via carrier. Cassette: JSONL, every event, raw + transformed, hashes.

### 5.6 Agent runner `agents/`
- **builtin**: tool-calling loop over LiteLLM. Providers: Groq, Gemini, Cerebras, OpenRouter (free tiers — limits change, checked at runtime via 429 handling, not hard-coded), Ollama local (3–4B models on CPU; small runs only).
- **command**: `--agent-cmd` with JSON-lines protocol, so users can test their own agent code.
- **FakeLLM policies** for tests: `ObeyAlways`, `NeverObey`, `ObeyIfEncoded`, `ExfilViaBase64`, `ObeyThenRecover`.
- Captures tokens, latency, retries, model id + provider-reported version.

### 5.7 Oracle `oracle/` (deterministic — the heart)
- Per-trial canary `cnry_<12 hex>` + honey secrets (fake key formats; never format-valid card/ID numbers).
- Encoding-aware matcher on sink args: raw, case-fold, whitespace/zero-width stripped, URL, base64 (all alignments), hex, rot13, reversed, separator-split, JSON-escaped.
- Rules: **R1 exfil** (honey/canary in sink args), **R2 goal action** (tool + arg predicate), **R3 answer hijack** (marker in final answer), **R4 suspicious** (sink after injection, no canary — review only, not counted).
- Utility: per-flow deterministic task checker. LLM-as-judge never decides primary verdict.

### 5.8 Corpus `corpus/`
- Normalized record `{id, text, source_dataset, source_id, license, attack_family, language, sha256}`.
- Candidate sources: LLMail-Inject (adaptive human attacks, email-borne), InjecAgent, BIPIA, AgentDojo injection tasks. **Licenses audited in Phase 0; a source without a compatible license is dropped.**
- Pipeline: fetch (pinned revision + checksum, never committed) → normalize → exact + near-dup removal → stratified sample → **goal rewriting** to target per-trial canary + the flow's real sink tool name (original kept for ablation).
- Schema-aware templating: payloads mention the user's real tool/arg names.

### 5.9 Mitigation catalog + Fix/Verify `fix/`
Catalog (each with patch renderer + twin-applicable policy):
| ID | Mitigation | Output |
|---|---|---|
| M1 | Remove/disable sink tool or server from this profile | client-config patch |
| M2 | Split servers into separate agent profiles (break the flow) | two config files |
| M3 | Require human approval for sink tool | client permission rule patch (e.g. Claude Code permission rules; exact syntax verified in Phase 0) |
| M4 | Taint gate: block sink calls whose args contain untrusted/private content | `proveflow guard` proxy config [v1] |
| M5 | Spotlighting/delimiting of untrusted tool output | system prompt snippet |
| M6 | Tool filtering per task | config patch |
- `fix` writes `proveflow-fixes/<flow>/` with patch + rationale + expected trade-off. **Never edits user files.**
- `verify` runs the *same* attacks + seeds with mitigation applied in the twin → paired McNemar + Newcombe CI on ASR difference + utility cost. Honest: M3 "approval" is simulated as deny-by-default in twin; real-world effectiveness depends on the human.

### 5.10 Stats `stats/`
Wilson 95% CI; paired McNemar exact + Newcombe CI for mitigation effect; optional SPRT early stop for CI mode. Every result records N, model, provider, temperature, seed policy, corpus revision, proveflow version, hardware.

### 5.11 Store + reports `store/`, `report/`
- SQLite single file + cassette dir. (ADR: no server needed for a CLI; Postgres depth already shown in other repos.)
- Terminal report (Rich), HTML (self-contained), JSON, SARIF (scan findings), JUnit (CI).
- Rule: every number in README/site is regenerable by one command from a stored run.

### 5.12 CI `action/`
- Composite GitHub Action for **MCP server authors**: introspect their server, scan flows against a reference "companion" sink/source set, run `replay` on committed cassettes (free, deterministic) every PR, optional scheduled live run. Fail when ASR upper CI exceeds threshold or a new flow appears.

### 5.13 Site `site/`
Next.js static export: landing + install commands, docs, methodology, published results (per model × flow class × mitigation), limitations, competitor comparison. Reads exported JSON only.

### 5.14 Detector track [v1]
Evaluate injection classifiers (e.g. Prompt Guard 2, deberta-v3 prompt-injection-v2) on the full normalized corpus (thousands of samples) + benign tool-output negatives: precision, recall, FPR, PR-AUC, per-family, and recall on payloads that *actually* compromised an agent in prove runs.

## 6. Feature tiers

| Feature | Tier |
|---|---|
| discover + redaction, introspect, role classifier, flow graph, SARIF | **v0.1 (first release — useful with zero LLM)** |
| twin, proxy + sink sandbox, oracle, agent runner, corpus, prove, stats, reports, replay | **MVP v0.2** |
| fix (M1–M3, M5, M6) + verify | **MVP v0.3** |
| GitHub Action, installers, PyPI | **MVP v0.3** |
| M4 taint-gate guard, real read-only mode, Streamable HTTP, detector track, site results | v1 |
| adaptive attacker, payload minimizer (ddmin), rug-pull mode, transfer matrix | research / FYP |

Cut: web dashboard with auth, hosted SaaS, runtime production firewall, fine-tuned detector, browser agents.

## 7. Repo layout

```
proveflow/
├── CLAUDE.md
├── README.md
├── LICENSE
├── pyproject.toml              # uv, hatchling, Python 3.12, entry point `proveflow`
├── src/proveflow/
│   ├── cli.py                  # typer
│   ├── config.py               # pydantic settings + proveflow.toml
│   ├── core/                   # pydantic domain models
│   ├── discover/               # readers/, redact.py
│   ├── introspect/             # launch.py, cache.py
│   ├── flows/                  # roles.py, graph.py
│   ├── twin/                   # generator.py, archetypes/, synth.py
│   ├── proxy/                  # server.py, upstream.py, sandbox.py, carriers.py, cassette.py
│   ├── agents/                 # builtin.py, command.py, fake.py
│   ├── oracle/                 # canary.py, encodings.py, matcher.py, rules.py
│   ├── corpus/                 # schema.py, registry.py, dedup.py, rewrite.py, loaders/
│   ├── fix/                    # catalog.py, renderers/, verify.py
│   ├── stats/                  # wilson.py, paired.py, sprt.py
│   ├── store/                  # sqlite.py, migrations/
│   └── report/                 # terminal.py, html/, json.py, sarif.py, junit.py
├── tests/{unit,property,integration,mutation,safety}/
├── action/action.yml
├── install/{install.sh,install.ps1}
├── site/
└── docs/
    ├── ARCHITECTURE.md  METHODOLOGY.md  THREAT_MODEL.md
    ├── DATASETS.md      CLIENT_CONFIGS.md  COMPETITORS.md
    └── adr/
```

## 8. Testing strategy

- **Unit**: every reader, redaction rule, role heuristic, graph path, encoder, rule, carrier, archetype, stats function (reference values computed in tests).
- **Property (Hypothesis)**: redaction never leaks a planted secret into any output; encode→match always true; benign text never matches fresh canary; carriers keep JSON valid; twin responses validate against declared output shape.
- **Integration (no real LLM)**: FakeLLM policies through real proxy + generated twins → exact expected verdicts; fix+verify on FakeLLM shows expected ASR drop.
- **Safety**: sink calls never reach upstream (asserted on upstream call log); `tools/call` never sent to real servers in default mode; no raw secret in logs/cassettes/reports (grep planted secrets across all outputs).
- **Mutation**: disable an encoder / redaction rule / sandbox → named tests must fail.
- **Determinism**: same cassette ⇒ byte-identical verdict JSON.
- **Live (opt-in marker)**: small smoke run on free tier; never required for CI green.
- CI matrix: ubuntu + windows, Python 3.12.

## 9. Phases (one at a time: plan mode → approval → code + tests → real output → Haris commits)

| Phase | Scope | Exit criteria | Est. |
|---|---|---|---|
| **0 Foundation** | Repo, tooling, CI, CLI skeleton, core models, docs (METHODOLOGY v0, THREAT_MODEL v0, COMPETITORS, DATASETS audit, CLIENT_CONFIGS verified, ADRs) | **Done 2026-11-10** [impl][tested]: ruff/mypy-strict/pytest (79 tests) green locally on Windows; CI workflow written but **never run** (repo has no remote yet); audits filled with source links, pending Haris review | 2–3 d |
| **1 Find** | discover + redaction, introspect (tools/list only), role classifier, flow graph, terminal + SARIF report; labeled tool set for classifier eval | `proveflow scan` on Haris's real machine; classifier precision/recall **[measured]**; redaction property tests. **1a done 2026-11-10** [impl][tested]. **1b introspection [impl][tested] 2026-11-12**: consented tools/list with a method allowlist; Job Object / process-group kill; safe PATH resolution and temp cwd; project-scope consent; unresolved-variable refusal; discover→legacy relaunch; tool cache + PF-TOOLCHANGE; PF-UNPINNED. Tested with a fake server on Windows; CI run 43059686222 green on ubuntu + windows at 3b66868. **1b done 2026-11-13**: real-machine `scan` run by the author (1 real stdio server; consent yes → `ok`, consent no → `declined`; `leak_check` clean both times; output not committed). Classifier baseline **[measured] once** (docs/eval/RESULTS.md); caveat: the test split is mostly reference servers, dev recall ~0.2–0.3, labels are LLM pre-labels reviewed by the author. Fixed from the real-machine run: silent drop of out-of-project servers (T16); UTF-8 `--json` on Windows. **Next: 1c** classifier v2 (dev-only tuning, fresh held-out set), then Phase 2. **Backlog:** flow grouping (one real server produced several hundred theoretical flows) | 5–6 d |
| **2 Proxy** | stdio proxy, sink sandbox, carriers, cassette | Safety tests prove no sink forwarding | 3–4 d |
| **3 Oracle** | canary, encodings, matcher, R1–R4, FakeLLM policies | Exact FakeLLM verdicts; mutation tests fail as designed | 3–4 d |
| **4 Twin** | twin generator, archetypes, synthetic data, honey secrets, schema validation | Twin of pg-mcp-guard + 2 public servers runs under proxy | 4–5 d |
| **5 Runner + store** | LiteLLM loop, command adapter, retries/429, SQLite, replay | One real trial on free tier; replay reproduces verdict | 3–4 d |
| **6 Corpus** | loaders (audited licenses only), dedup, goal rewriting, sampling | Corpus stats **[measured]**; license per record | 4–5 d |
| **7 Prove** | campaign engine, paired trials, stats, HTML/JSON/JUnit | **First real numbers**: ≥2 models, FlowVerdicts with CIs | 4–5 d |
| **8 Fix + Verify** | catalog M1–M3, M5, M6; patch writers; paired verify | One CONFIRMED flow → fix → measured ASR change | 4–5 d |
| **9 Ship** | GitHub Action, PyPI trusted publishing, install.sh/ps1 | Clean-machine install on Windows + Linux recorded | 2–3 d |
| **10 Site + story** | Next.js site, README, demo video, write-up | Site live; every number links to run ID | 4–5 d |
| **11 v1** | taint-gate guard, real read-only mode, HTTP transport, detector track | per item | later |
| **F1–F4** | adaptive attacker, ddmin, rug-pull, transfer matrix | research questions answered from stored runs | FYP semester |

Realistic MVP (0–9): **~8–9 weeks part-time.** v0.1 (Phase 1) is releasable on its own — ship it early.

## 10. Hardware & cost constraints (stated: i5 12th gen, 16 GB RAM, 256 GB SSD, no discrete GPU)
- Free API tiers are primary for prove runs; rate-limit aware runner + caching + replay.
- Local Ollama: 3–4B Q4 models for privacy mode and smoke tests only; at most 2–3 models on disk.
- Datasets cached compressed; corpus cache size reported.

## 11. FYP mapping (DUET BS AI, group FYP)
- **Research question:** *How often are statically detected cross-server toxic flows actually exploitable by real-world injection payloads against open-weight and free-tier tool-using models, and what is the ASR reduction vs utility cost of each mitigation class?*
- Secondary: static-vs-adaptive gap (F1); classifier precision for tool roles; detector recall on real compromises.
- **Group honesty:** Haris builds the core. If teammates are listed, give them real owned modules (e.g. labeled tool dataset + classifier eval, detector track, site) with their own commits, or agree roles with the supervisor in writing. Never fabricate contributions either way.
- Check DUET rules on public prior work and supervisor approval before relying on this as FYP.

## 12. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Scope explosion | Strict tiers; v0.1 → v0.2 → v0.3 gates |
| Twin realism overstated | Limitation printed in every report; real read-only mode opt-in later |
| Secret leakage from configs | Redact at read time; property + grep tests; no raw values in any output |
| Launching malicious servers during introspection | Per-server consent, timeout/kill, `--no-launch`; documented in THREAT_MODEL |
| Free-tier limits / nondeterminism | Paired trials, CIs, replay, SPRT, record everything |
| Commoditization (Snyk/Anthropic ship similar) | Portfolio value stays; position on measured proof + fix verification |
| Over-claiming | "NOT REPRODUCED ≠ safe"; tags; no enterprise claims |
| Dataset licenses | Phase 0 audit; fetch at runtime; never redistribute raw data |
| Responsible disclosure | Real flaws in third-party servers reported privately first; no exploit publication before fix window |
