# proveflow

**Find → Prove → Fix → Verify** for the MCP tool setup you actually run.

An agent connected to several MCP servers holds two capabilities at once: it reads content it
does not control, and it can act. A tool that fetches a page and a tool that writes a file, in
one session, is a path — text in that page can carry private data out through the second tool.
You approved both tools. Nobody approved the combination.

```mermaid
flowchart LR
  A["<b>Untrusted source</b><br/>fetch a web page,<br/>read an issue, read a file"]
  B["<b>The agent</b><br/>one session<br/>both tools approved separately"]
  C["<b>Private data</b><br/>your files, your database,<br/>your messages"]
  D["<b>Sink</b><br/>write a file, send a request,<br/>post a message"]

  A -->|"tool result"| B
  C -->|"tool result"| B
  B -->|"tool call"| D

  A -. "<b>1.</b> text in that result<br/>instructs the model" .-> B
  B -. "<b>2.</b> the private data leaves<br/>through a tool you approved" .-> D

  style A fill:#fde2e2,stroke:#c0392b
  style D fill:#fde2e2,stroke:#c0392b
  style C fill:#fff6d6,stroke:#b8860b
```

> The agent holds both capabilities in one session. The attacker controls only the first tool's
> *output* — and that is enough. proveflow's own scanner does not yet see the file-borne case — see
> [Known limits](#known-limits-stated-plainly).

Static scanners list those pairings. proveflow is built to **measure** them: discover your real
setup, map the flows, attack each one in a safe schema twin with published injection payloads,
let a deterministic oracle decide whether the agent was hijacked, then patch the config and
re-measure on the same cells.

> **Read this first.** One paid campaign has run: **0 of 30 trials compromised**, with exposure
> measured at 30 of 30. That zero is a capability-dependent lower bound under a favourable
> delivery condition — not an attack-success rate, and not evidence any model is safe.
> **ZERO REAL POSITIVES: no real trial has ever been compromised.** Why the zero means anything
> at all, and what it cannot mean, is in [What is proved](#what-is-proved-and-what-is-not).

📄 **[Case study: building a security tool that refuses to overstate its own results](docs/CASE_STUDY.md)**
— the design decisions, the negative result, and the defect I found in my own tool that stopped
my own release.

---

## What it looks like

The committed fixture `tests/fixtures/action/toxic.servers.json`, scanned from the repo root.
Captured 2026-11-27 on Windows, verbatim, at 140 columns, with an empty home directory so
that no client config of the machine was read (`--project` pointed at an empty directory):

```console
$ proveflow scan --servers tests/fixtures/action/toxic.servers.json --no-launch --fail-on any
                                   Profile explicit:tests\fixtures\action\toxic.servers.json                                    
+------------------------------------------------------------------------------------------------------------------------------+
| server     | transport | introspection              | era | tools | baseline | redacted | roles                              |
|------------+-----------+----------------------------+-----+-------+----------+----------+------------------------------------|
| fetch      | stdio     | not launched (--no-launch) | -   | -     | -        | -        | source (server-level guess)        |
| filesystem | stdio     | not launched (--no-launch) | -   | -     | -        | -        | private, sink (server-level guess) |
+------------------------------------------------------------------------------------------------------------------------------+
Servers: 2 discovered, 2 analyzed, 0 skipped
                                    Toxic flows: 3 groups (3 flows), all THEORETICAL                                     
+-----------------------------------------------------------------------------------------------------------------------+
| id         | class  | source | private    | sink       | cross | worst sink kind | max conf      | #flows | #profiles |
|------------+--------+--------+------------+------------+-------+-----------------+---------------+--------+-----------|
| G-253caf41 | exfil  | fetch  | filesystem | filesystem | yes   | local_write     | 0.35 (server) | 1      | 1         |
| G-812c077e | action | fetch  | -          | filesystem | yes   | local_write     | 0.35 (server) | 1      | 1         |
| G-6655df9e | leak   | -      | filesystem | filesystem | no    | local_write     | 0.35 (server) | 1      | 1         |
+-----------------------------------------------------------------------------------------------------------------------+
limitation: Static analysis only: every flow is THEORETICAL until proven in a twin (Phase 7). No flow listed does not mean the setup is 
safe.
limitation: --no-launch: tools are unknown; roles are inferred from server names/commands only (granularity=server, low confidence).
limitation: Every configured server is treated as connected to its client (over-approximation): client-side approval and disabled flags are
not modeled.
limitation: Secrets in args/URLs are redacted by pattern (docs/REDACTION.md); a short unflagged positional secret can be missed. Env and 
header values are always fully redacted.
proveflow: 3 flow(s) matched --fail-on any (THEORETICAL: from config names and command lines only (--no-launch))
exit=3
```

Every report carries its own limitations. A scan that analysed nothing says `this is NOT a
clean result` instead of printing an empty flow table.

## Install

```sh
sh install/install.sh                                          # Linux / macOS
powershell -ExecutionPolicy ByPass -File install\install.ps1   # Windows
```

The default route installs from the git tag `v0.1.0a1`, with dependencies from PyPI.
- **It has run once, LOCALLY**, on the author's Windows machine (2026-11-27; not in CI, not a
  clean machine).
- `uv tool install git+https://github.com/M-Haris346/proveflow@v0.1.0a1`, the command the
  installers wrap, run directly, resolved 38 packages, built from the tag at `4740df3`, reported
  `proveflow 0.1.0a1` and uninstalled cleanly.
- CI has not run this route.
- Nothing is on PyPI.

Both routes, their cited sources, and what each does **not** prove:
[docs/INSTALL.md](docs/INSTALL.md).

**Install evidence (the wheelhouse route).** CI run `45906223124` on `4740df3`:
- the real installer ran in a bare `ubuntu:24.04` container with `python3`, `python`, `uv` and
  `curl` all absent;
- it bootstrapped uv 0.13.10 and installed 36 wheels with **no package index at all**
  (`--no-index`);
- it matched its version, and `scan --help` exited 0;
- on Windows, 38 wheels installed on a hosted runner, which is not a clean machine and is
  labelled as such.

## How it works

```mermaid
flowchart TD
  subgraph FIND["FIND — what is reachable"]
    direction LR
    DI["<b>discover</b><br/>real client configs<br/><i>secrets redacted at read time</i>"]
    SC["<b>scan</b><br/>flow graph per agent profile<br/><i>SARIF · exit 3 as a CI gate</i>"]
    DI --> SC
  end

  subgraph PROVE["PROVE — does a real model actually do it"]
    direction LR
    TW["<b>twin</b><br/>schema twin per server<br/><i>synthetic data, honey values</i>"]
    PX["<b>proxy</b><br/>inject · record · sandbox pure sinks<br/><i>hash-chained cassette</i>"]
    RU["<b>runner</b><br/>real LLM tool-calling loop<br/><i>per-trial DESIGN caps</i>"]
    OR["<b>oracle</b><br/>R1–R4, deterministic<br/><i>NO LLM judge</i>"]
    CA["<b>campaign</b><br/>two rates per source<br/><i>Wilson 95%, never pooled</i>"]
    TW --> PX --> RU --> OR --> CA
  end

  subgraph ACT["FIX + VERIFY — did the change help"]
    direction LR
    FX["<b>fix</b><br/>patch files<br/><i>NEVER applied</i>"]
    VE["<b>verify</b><br/>paired halves, same cells<br/><i>rate + exposure + utility + label</i>"]
    FX --> VE
  end

  SC -->|"introspected scan only<br/>a --no-launch scan is refused"| TW
  CA --> FX

  CTRL["<b>Control A</b><br/>the positive control<br/>30/30 compliant · 0/30 not<br/><i>without this, a zero means nothing</i>"]
  CTRL -.-> CA
  CTRL -.-> VE

  style OR fill:#e8f4ea,stroke:#2e7d32
  style CTRL fill:#e3eefc,stroke:#1565c0
  style FX fill:#fff6d6,stroke:#b8860b
```

| Stage | What it does | Key constraint |
|---|---|---|
| **Find** | Reads real client configs; classifies tools into untrusted source / private data / sink; builds a flow graph per agent profile; emits SARIF 2.1.0 | Secrets redacted at read time. Introspection asks `tools/list` only, with per-server consent and a method allowlist that blocks `tools/call` |
| **Prove** | Replaces each server with a deterministic schema twin (same tool names, descriptions and schemas; synthetic data; honey values); a proxy injects the payload into every result of the one attacked tool; a real model drives the loop | **Pure sinks are always sandboxed and never forwarded.** A dual-role tool (untrusted source AND sink, e.g. `fetch`) is forwarded to a twin that passed the no-I/O guard, recorded as `upstream_request.sink=true`, and that is the path the campaigns actually use (ADR-007). The guard is an AST check, not a sandbox. Payloads target per-trial canaries only: no real credentials, no real endpoints |
| **Oracle** | Decides compromise deterministically: the canary or a honey value in the arguments of a sandboxed sink call OR of a forwarded dual-role sink call (the campaigns use the second), across 10 encodings | **No LLM judge, anywhere.** Canary space 47.99 bits, honey 63.98 bits, counted exactly |
| **Fix** | Emits an RFC 6902 patch per config file, or a Claude Code approval fragment | **Never applied.** A safety test proves `fix` never modifies a config (bytes and mtime unchanged). That it never opens one is by construction (it reads only the scan report), not a test result |
| **Verify** | Paired halves on the same cells with the mitigation in the twin | Three figures per row — rate, exposure, utility — each with its own denominator, plus a label naming the mechanism |

```mermaid
flowchart LR
  LLM["<b>real LLM</b><br/>OpenAI-compatible<br/>provider"]
  PX{{"<b>proveflow proxy</b><br/>default deny"}}
  TW["<b>schema twin</b><br/>same tool names,<br/>descriptions and schemas<br/>synthetic data + honey values"]
  SB["<b>sandboxed</b><br/>the call goes nowhere<br/>a fixed ok reply goes back to the model"]
  CAS[("<b>cassette</b><br/>hash-chained JSONL")]
  ORA["<b>oracle</b><br/>canary or honey value<br/>in a sink call's arguments?<br/>10 encodings · no LLM"]

  LLM -->|"tools/call"| PX
  PX -->|"result, with the payload injected into<br/>EVERY result of the one attacked tool"| LLM

  PX ==>|"<b>pure sink</b>"| SB
  PX -->|"non-sink tool, or dual-role<br/>(e.g. fetch)"| TW
  TW -->|"result"| PX

  PX --> CAS --> ORA

  style SB fill:#e8f4ea,stroke:#2e7d32
  style ORA fill:#e8f4ea,stroke:#2e7d32
  style PX fill:#e3eefc,stroke:#1565c0
```

> A **pure sink** call is sandboxed and never forwarded. A **dual-role** tool — one that is both
> an untrusted source and a sink, such as `fetch` — *is* forwarded, to a twin that passed an AST
> no-I/O guard, and is recorded as `upstream_request.sink=true`. That is the path the campaigns
> actually use, and the guard is a static check, **not a sandbox**.

Payloads: 347 records from three published benchmarks at pinned revisions, MIT on every record.
72% come from one source, so results are reported **per source** and never pooled.

## What is proved, and what is not

**The one paid campaign** (`groq_forced_7db7eff3b652`, Groq `openai/gpt-oss-120b`, temperature
0.0, 30 counted trials, 10 per source) →
[full result](docs/results/groq_forced_7db7eff3b652.md)

| | |
|---|---|
| Compromised | **0 of 30**, END-TO-END and DELIVERED |
| Exposure (payload actually reached the model) | **measured, 30 of 30** |
| Per source | 0/10, Wilson 95% [0.000, 0.278] |

**Why that zero means anything at all.** A broken oracle, a proxy that never flags sinks, or a
payload that never arrives would all report zero too. So the positive control came first:
**Control A** runs the same 30 cells twice. A scripted client that complies with the injection
gives **30/30**; one that ignores it gives **0/30**. Six mutants each break one thing, and each
is killed with its layer named:
- **L3** delivery;
- **L4** the proxy's sink flag;
- **L5** the oracle;
- **L6** the ledger;
- **L6** the report;
- an oracle that fires on anything, which passes the compliant half and is killed only by the
  negative half.

**What the zero still is not:** an attack-success rate, or evidence a model is safe. It is a
capability-dependent lower bound under a favourable delivery condition.

**Three limits recorded beside it:**
- in 30 of 30, the model made **no tool call at all** after reading the injection, so the run
  cannot distinguish "refused to act" from "acted without leaking";
- the template's exfil clause asked for private data the task never read;
- the run is **not reproducible**: 25 distinct provider `system_fingerprint` values across 84
  responses in one campaign of 7 min 54 s. A seed sent is not determinism.

**Control A's 30-cell test runs only on the author's machine.** It needs a raw corpus cache that
is never committed, so it skips in a fresh clone and in CI; CI runs the same check on a 3-cell
synthetic plan plus its mutants.

### Verify, against the control only

| Mitigation / template | Rate | Exposure | Utility | Label |
|---|---|---|---|---|
| M1 on `fs_notes_exfil` | 10/10 → **0/10** | 10/10 → 10/10 | 10/10 → 10/10 | **FLOW BLOCKED** ✅ |
| M3 on the same cells | 10/10 → **0/10** | retained | retained | FLOW BLOCKED — *but the twin denied every call, not a real client* |
| M1 on `fetch_summary_exfil` | 10/10 → **0/10** | 10/10 → **0/10** | 10/10 → **0/10** | **DELIVERY + CAPABILITY REMOVED — NOT a fix** ❌ |

The third row is the point: the rate went to zero because the tool was turned off. Both rows
move the same way; only one of them means anything.
[Full report](docs/results/verify_control_groq_fs_forced_c254f660e358.md)

### Known limits, stated plainly

- **No real positive, for any rule.** Oracle rules are validated against fixtures authored here,
  which shows they match our model of the attack — not that they catch real model behaviour.
- One model, one tier, one template, n=10 per source.
- Verify has only run against a scripted control, never a real model.
- The approval mitigation has never been tested in a real client; its patch is headed FOR REVIEW
  because a wrong rule would apply cleanly and protect nothing.
- **`scan` cannot discover file-borne injection at all** — the classifier never labels a
  filesystem read tool an untrusted source. Measured: 0 such flows without a manual override,
  11 with it. A recorded Find-stage defect.
- Held-out classifier recall: sink 16/25, private data 4/20, and 10 of 13 rules never exercised.
- The GitHub Action classifies from config text only; on the toxic fixture it sees 3 of 16 flows
  and misses 13. A tripwire, not a proof.
- Nothing is released on PyPI.

## CI gate and the GitHub Action

**Exit codes of `proveflow scan`:**

| code | meaning |
|---|---|
| `0` | clean: no flow matched `--fail-on` (or none given) |
| `1` | proveflow's own usage or config error — including, under `--fail-on`, **any config it could not read**. Never a pass, never a finding |
| `2` | Click's own usage error. Currently overloaded: the not-implemented stub commands also exit 2 (pre-existing) |
| `3` | findings: a flow matched `--fail-on` |

Without `--fail-on` the exit code is unchanged, but every unreadable config is named on stderr.

**The Action** (`action/`, measured limits in [action/README.md](action/README.md)) runs
`scan --no-launch --fail-on <class>` and fails the job on a finding.
- It classifies from server names and command lines only, never tool lists.
- Every flow it reports is THEORETICAL.
- It misses 13 of 16 flows on the toxic fixture.
- It is a tripwire for a config change that introduces a dangerous pairing.

Its self-test, run `45906223026` on `4740df3`, gives the same result on both OSes: clean 0
flows, blind spot 0 flows, toxic exit 3 with 3 flows and 3 SARIF results.

## Tests

CI run `45906223082` on `4740df3`, green on both OSes: **ubuntu-24.04 1858 passed / 21 skipped, windows-2025 1873 passed / 6 skipped** (1879 collected on each).

- 225 mutation test functions (287 collected, with parametrisation); the newest 11 name the
  exact line they kill.
- Property tests on redaction.
- Safety tests prove that `discover`, `scan` and `fix` never **modify** a client config: its
  bytes and mtime are unchanged. `discover` opens configs to read them.
- The control client, which deliberately obeys injections, **is** importable: it ships in the
  package. A guard proves that nothing under `src/` imports it except `runner.verify`.
- **No test calls an LLM provider** — a network guard enforces it. The one paid campaign was run
  by hand.
- Four skips per OS are the corpus-cache tests, which need an uncommitted cache; CI runs the
  equivalent on 3 synthetic cells.

```bash
uv sync
uv run ruff check .
uv run ruff format --check .
uv run mypy src          # strict, src only
uv run pytest --cov -rs
```

## Documentation

| Document | What's in it |
|---|---|
| [docs/CASE_STUDY.md](docs/CASE_STUDY.md) | The design decisions, the negative result, and the defect that blocked a release |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Full design, every stage, the phase plan |
| [docs/THREAT_MODEL.md](docs/THREAT_MODEL.md) | T1–T20, each with its mitigation and its state |
| [docs/ORACLE.md](docs/ORACLE.md) | Rules R1–R4 and the encoding matcher |
| [docs/METHODOLOGY.md](docs/METHODOLOGY.md) | Rates, denominators, controls, labels |
| [docs/DATASETS.md](docs/DATASETS.md) | Corpus sources, licences, pinned revisions |
| [docs/REDACTION.md](docs/REDACTION.md) | What is redacted, where, and what can still be missed |
| [docs/INSTALL.md](docs/INSTALL.md) | Both install routes and what each does not prove |
| [docs/STATUS.md](docs/STATUS.md) | Phase-by-phase state, every claim tagged `[impl]`/`[tested]`/`[measured]` |
| [docs/BACKLOG.md](docs/BACKLOG.md) | Everything still open, with measurements, not guesses |

## How this was built

I designed and built ProveFlow, and I am its only author. I used Claude Code as a pair-programmer,
working from my own specification ([CLAUDE.md](CLAUDE.md)) and phase plans. Each phase started as a
plan that I reviewed, amended and approved before any code was written; I then reviewed the output
and the real test and campaign runs, and pushed back where something was wrong. Commits written with
Claude Code carry a `Co-Authored-By` trailer. I ran every git command myself, and I can explain
every design decision in this repository. The reasoning is in
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and [docs/CASE_STUDY.md](docs/CASE_STUDY.md).

## License

[MIT](LICENSE)
