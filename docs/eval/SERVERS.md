# Classifier eval: servers

> Collected 2026-11-12 (GitHub Actions run `43285294552`): 12 of 14 planned servers; see
> [Collection attrition](#collection-attrition) and docs/eval/RESULTS.md.
>
> Every column comes from the pinned package itself or its official page:
> - versions and dates: the npm registry / PyPI JSON
> - licenses: the LICENSE file inside the pinned tarball/sdist, or the repo LICENSE when the
>   package ships none
> - tool counts: the pinned package's README or source
> - telemetry: a grep of the pinned README for
>   `telemetry|analytics|usage statistic|usage data|tracking|posthog|mixpanel|segment.io|google analytics|opt out`
>
> Version rule: the newest stable release that is ≥ 14 days old (published ≤ 2026-10-28).
> Credentials rule (Haris): a dummy token only where official docs say startup does not
> validate it; otherwise the server is excluded. Real tokens are never used. Accessed
> 2026-11-11/12.

## Decisions (Haris, 2026-11-11)

| Topic | Decision |
|---|---|
| Reference servers (Note A) | **include**. License recorded as "MIT OR Apache-2.0 (repo LICENSE @6b36e3c)"; attribution in docs/DATASETS.md |
| everything | **exclude** |
| Desktop Commander | **exclude**. Its README says "Desktop Commander collects limited, pseudonymous telemetry … **Opt-out:** Ask Claude to "disable Desktop Commander telemetry" or set `"telemetryEnabled": false` in your config." PRIVACY.md: "Edit your configuration file at `~/.desktop-commander/config.json`". There is no launch flag or env var, and the docs do not say the opt-out works before the first run. Asking the model means a `tools/call`, which proveflow never sends. Rule: no applicable documented opt-out → exclude |
| Chrome DevTools MCP | **include, with its documented opt-out**. README 1.12.0: "Data collection is **enabled by default**. You can opt-out by passing the `--no-usage-statistics` flag" and "Collection is disabled if `CHROME_DEVTOOLS_MCP_NO_USAGE_STATISTICS` or `CI` env variables are set." The launch uses the flag and `CHROME_DEVTOOLS_MCP_NO_USAGE_STATISTICS=1`, recorded in the dataset row |
| pg-mcp-guard | **in-process `list_tools`, stub executor** (below). Dev split only (Haris knows these tools; not blind) |
| GitHub MCP | **exclude**: needs `GITHUB_PERSONAL_ACCESS_TOKEN`, and the README does not say that startup skips validation |

## Servers in the set

**Where collected (Haris, 2026-11-12):** servers 1-8 below **and** the registry servers are all collected in **one ephemeral GitHub Actions job**: one reproducible artifact, and nothing third-party runs on the laptop. The workflow is `.github/workflows/eval-collect.yml` (manual `workflow_dispatch` only; moved there with Haris's approval on 2026-11-12; Haris triggers it). The launch specs are `data/eval/roles/servers.json`, run by `python -m proveflow.eval.collect`. pg-mcp-guard (row 9) stays the in-process script on Haris's machine (his own code).

| # | Server | Package @ version (published) | License (how verified) | Tools (how counted) | Telemetry (pinned README) | Launch / provenance | Split |
|---|---|---|---|---|---|---|---|
| 1 | fetch | PyPI `mcp-server-fetch==2026.10.24` (2026-10-25) | MIT OR Apache-2.0 (repo LICENSE @6b36e3c); sdist LICENSE + PKG-INFO say MIT | 1 (src) | 0 hits | `uvx mcp-server-fetch@2026.10.24`, tools/list | free |
| 2 | filesystem | npm `@modelcontextprotocol/server-filesystem@2.0.1` (2026-10-25) | MIT OR Apache-2.0 (repo LICENSE @6b36e3c; tarball ships none) | 14 (`registerTool` in dist) | 0 hits | `npx -y …@2.0.1 <empty tmpdir>`, tools/list | free |
| 3 | git | PyPI `mcp-server-git==2026.10.19` (2026-10-19) | MIT OR Apache-2.0 (repo LICENSE @6b36e3c); sdist LICENSE says MIT | 12 (`GitTools` enum) | 0 hits | `uvx mcp-server-git@2026.10.19 --repository <tmp git repo>`, tools/list | free |
| 4 | memory | npm `@modelcontextprotocol/server-memory@2.0.0` (2026-10-19) | MIT OR Apache-2.0 (repo LICENSE @6b36e3c) | 9 | 0 hits | `npx -y …@2.0.0` (memory file in tmp), tools/list | free |
| 5 | sequential-thinking | npm `@modelcontextprotocol/server-sequential-thinking@2.0.0` (2026-10-19) | MIT OR Apache-2.0 (repo LICENSE @6b36e3c) | 1 | 0 hits | `npx -y …@2.0.0`, tools/list | free |
| 6 | time | PyPI `mcp-server-time==2026.10.19` (2026-10-19) | MIT OR Apache-2.0 (repo LICENSE @6b36e3c); PKG-INFO says MIT | 2 | 0 hits | `uvx mcp-server-time@2026.10.19`, tools/list | free |
| 7 | Playwright MCP | npm `@playwright/mcp@0.0.83` (2026-09-28), gitHead `f183dad4` | Apache-2.0 (LICENSE in tarball) | 25 core (README "Core automation"); `--caps` extras not enabled | 0 hits | `npx -y @playwright/mcp@0.0.83 --headless`, tools/list | free |
| 8 | Chrome DevTools MCP | npm `chrome-devtools-mcp@1.12.0` (2026-10-22), gitHead `af283441` | Apache-2.0 (LICENSE in tarball) | **counted at collection** (21 tool modules; a static count is unreliable) | 5 hits, all in the "Usage statistics" section (README:41-55), opt-out applied as above | `npx -y chrome-devtools-mcp@1.12.0 --no-usage-statistics` + env `CHROME_DEVTOOLS_MCP_NO_USAGE_STATISTICS=1`, tools/list | free |
| 9 | pg-mcp-guard | Haris's repo, `0.1.0` @ `b7a6dce` | MIT (repo LICENSE) | **3**: `list_tables`, `describe_table`, `run_query`, from the in-process run below | n/a (own code) | **in-process `list_tools`, stub executor** | **dev only** |

Confirmed: 1 + 14 + 12 + 9 + 1 + 2 + 25 + 3 = **67** tools, plus Chrome DevTools (counted at
collection).

## Collection attrition

Run `43285294552` (workflow `eval-collect`, 2026-11-12, `--timeout 180 --ignore-scripts
--no-build`). Planned: 14 servers (`data/eval/roles/servers.json`). Collected: **12**
(136 tools). Neither failure was retried or replaced.

| Server | Status | Cause (from the run summary) |
|---|---|---|
| deliverd-screen | timeout | no `tools/list` answer within 180 s |
| global-sentinel-mcp | failed | unpinned `mcp` dependency resolved to `mcp` 2.x → `ModuleNotFoundError: No module named 'mcp.server.fastmcp'` (the SDK's error text: "pin 'mcp<2' to keep running v1 code") |

Collected tool counts: chrome-devtools 32, fetch 1, filesystem 14, flagquantum-mcp-server 27,
git 12, grok-mcp 4, marketplace-mcp 5, memory 9, playwright 25, sequential-thinking 1,
tickerrisk-mcp 4, time 2. Add pg-mcp-guard's 3 tools (in-process): 13 servers and 139 tools
before CAP, 100 after CAP 15 (dev 60 / test 40).

### pg-mcp-guard: in-process list_tools (run 2026-11-12, real output)

Script: `scripts/eval_pg_mcp_guard_list_tools.py`. It runs with pg-mcp-guard's **own** venv
interpreter (`.venv\Scripts\python.exe`) from the repo root and asserts `HEAD` is `b7a6dce`
with a clean working tree. It then calls
`create_server(StubExecutor(), stub_principal)` and `Client(server).list_tools()` in-process.
- `StubExecutor.__getattr__` raises on **any** attribute access, so a DB touch would fail the run.
- `stub_principal` returns `None` and counts its calls.

Why this is safe: tools are built inside `create_server` (`app/server.py:275-380`), and the
constructor `ToolCallGuard.__init__` (`app/server.py:223-235`) only stores references. The
principal source is called only for `tools/call` (`app/server.py:251`).

```
{
  "source": "pg-mcp-guard",
  "commit": "b7a6dce691e48cdf5feb777d221e25260c48d266",
  "provenance": "in-process list_tools, stub executor",
  "principal_source_calls": 0,
  "next_cursor": null
}
- list_tables: params=[]
- describe_table: params=['name']
- run_query: params=['sql']
```

`git status --porcelain` in pg-mcp-guard afterwards printed 0 lines.

## Registry additions (Haris, 2026-11-12: include all 6 licensed candidates)

Listing: `GET /v0/servers?limit=100&version=latest`. Registry OpenAPI
(<https://registry.modelcontextprotocol.io/openapi.yaml>, accessed 2026-11-12): "Use
version=latest to return only the latest version of each matching server."; `version`:
"Filter by version ('latest' for latest version, or an exact version like '1.2.3')". (The
first, unfiltered run of 2026-11-11 listed 242,565 server *versions* and was stopped when the
half-day budget ran out.)

Rule: `scripts/eval_registry_select.py` (R1–R5 unit-tested in
`tests/unit/test_registry_rule.py`). Run on 2026-11-12: 623 pages, **62,256** latest entries.

| Rule | Excluded |
|---|---|
| R1 not active / not latest | 974 |
| R2 published after 2026-10-28 | 18,799 |
| R3 no npm/PyPI stdio package | 29,135 |
| R4 required env var / required secret | 3,330 |
| R5 required package argument | 118 |
| **Survivors** | **9,900** |

Sample: `random.Random(20261111).sample(sorted_by_name, 8)`. License comes only from a LICENSE
file in the pinned tarball/sdist (read in memory, never extracted or executed). Telemetry is
the README grep above. **Attrition: 8 sampled, 2 dropped (no LICENSE file); not resampled.**

Wheels: collection runs with `--no-build` (`UV_NO_BUILD=1` in each server's env, so no sdist builds). PyPI JSON for each pinned
version, 2026-11-12: all three PyPI candidates publish a `py3-none-any` wheel, so the package
itself installs without a build. Their **dependencies** are only resolved at collection time;
a dependency that is sdist-only makes that server fail, and the failure will be reported.

| Registry name | Package @ version (published) | Wheel for pinned version | LICENSE file (archive sha256 prefix) | Telemetry grep | Decision |
|---|---|---|---|---|---|
| io.github.mrfentmen/waqi-mcp | npm `waqi-mcp@1.0.0` (2026-09-21) | n/a (npm) | **none in package** (`9ab51998dd397d3c`) | 0 | **dropped** (no LICENSE file) |
| io.github.joepangallo/mcp-server-security-audit | npm `mcp-server-security-audit@1.0.3` (2026-03-01) | n/a (npm) | **none in package** (`c708bc69f274d2ea`) | 0 | **dropped** (no LICENSE file) |
| io.github.deliverd-dev/deliverd-screen | npm `@deliverd/screen@0.2.0` (2026-10-26) | n/a (npm) | MIT, `package/LICENSE` (`636a2e90385203f5`) | 0 | **include** (ephemeral runner only) |
| io.github.howardpen9/grok-mcp | npm `grok-cli-mcp@0.2.0` (2026-06-10) | n/a (npm) | MIT, `package/LICENSE` (`d61f2b14599762e6`) | 0 | **include** (ephemeral runner only) |
| io.github.nirholas/marketplace-mcp | npm `@three-ws/marketplace-mcp@0.1.3` (2026-10-10) | n/a (npm) | Apache-2.0, `package/LICENSE` (`41c3a2df65459bed`) | 1 (`examples/README.md:90`): **telemetry grep hits manually reviewed: data/feature mentions, not product telemetry; collected only in the ephemeral runner** | **include** (ephemeral runner only) |
| io.github.PasiutusVovere/tickerrisk-mcp | PyPI `tickerrisk-mcp==0.1.3` (2026-09-27) | yes: `tickerrisk_mcp-0.1.3-py3-none-any.whl` | MIT, sdist `LICENSE` (`081ea6f90dc9d702`) | 0 | **include** (ephemeral runner only) |
| io.github.ykshah1309/global-sentinel-mcp | PyPI `global-sentinel-mcp==0.1.1` (2026-04-20) | yes: `global_sentinel_mcp-0.1.1-py3-none-any.whl` | MIT, sdist `LICENSE` (`d227e244fcd2d3c4`) | 5 (`README.md:6,22,29,182,191`): **telemetry grep hits manually reviewed: data/feature mentions, not product telemetry; collected only in the ephemeral runner** | **include** (ephemeral runner only) |
| io.github.FlagQuantum/flagquantum-mcp-server | PyPI `flagquantum-mcp-server==0.3.2` (2026-10-27) | yes: `flagquantum_mcp_server-0.3.2-py3-none-any.whl` | Apache-2.0, sdist `LICENSE` (`3f52453418e11391`) | 0 | **include** (ephemeral runner only) |

Limits, stated:
- A README without a telemetry mention does not prove the server sends none.
- Tool counts are unknown until collection.
- The npm `license` field was **not** used.
- These 6 candidates come from unknown publishers.

**Collection only in an ephemeral runner (same job as all other eval servers):**
`.github/workflows/eval-collect.yml` (manual dispatch only; not run by Claude).
- It uses `workflow_dispatch` on `ubuntu-24.04`, `contents: read`, and no secrets.
- Setup-uv caching is off (`enable-cache`, `save-cache` and `restore-cache` all `"false"`).
- `CI=true` at job level.
- The collector runs with `--ignore-scripts --no-build`, which puts
  `npm_config_ignore_scripts=true` (npm config docs; the docs do not say whether npx honours
  it) and `UV_NO_BUILD=1` (uv docs: "If set, uv will not build source distributions") into
  **every server's own env**.
- **Fixed bug (2026-11-12):** these were first set as job-level env. That never reached the
  servers, because a launched server gets only proveflow's minimal env allow-list plus its
  configured env (`src/proveflow/introspect/env.py`). A job-level `UV_NO_BUILD` would also
  have stopped `uv sync` from building proveflow itself. Tests:
  `tests/safety/test_eval_collect.py::test_no_build_reaches_child_env` and
  `test_job_level_env_does_not_reach_child`.

## Split design (4b, implemented only after approval)

1. **Cap per server:** each server contributes at most `CAP` tools, a fixed number. When a
   server has more, the kept tools are a deterministic sample (seed `20261111`, sorted names,
   `random.Random(seed).sample`). The full list is still stored, and the cap only applies to
   eval rows. `CAP` gets proposed together with the feasibility numbers.
2. **Near-duplicate grouping:** servers with overlapping tool names stay in the same split.
   Grouping rule: Jaccard similarity of tool-name sets ≥ 0.3, or the same upstream repo.
3. **Assignment:** enumerate group subsets; pick the test subset that minimizes
   |test_tools/total − 0.40|, subject to every group being ≤ 50% of the test tools and at least
   2 groups on each side; ties broken by sha256 of the sorted names. pg-mcp-guard is forced into
   dev.
4. **Feasibility first:** before splitting I show the per-group counts, whether the rule is
   satisfiable at all, and the max single-group share in **both** splits.
5. **Reporting:** per-role precision/recall/F1 with Wilson 95% CIs **only where the relevant
   denominator is ≥ 10** (TP+FP for precision, TP+FN for recall). Otherwise the cell says
   "N < 10, not reported".

### 4b decisions (Haris, 2026-11-12)

**CAP = 15** and **variant A (Jaccard-only grouping)** are approved. The "same upstream repo" clause is dropped.

**Threat to validity (stated in the eval report):** the six reference servers come from one repository (modelcontextprotocol/servers) and share a writing style and vocabulary for names and descriptions. Under variant A they can land on both sides of the split, so heuristics tuned on dev reference servers may do better on test reference servers than on unseen styles. That would inflate test precision/recall. The report gives per-source results (reference / popular / registry) next to the pooled numbers, so the effect is visible.

### 4b feasibility (computed 2026-11-12 from KNOWN counts only; no split file exists)

Script: scratch calculation that implements rule 3 above exactly. Chrome DevTools and the 6
registry servers have **no counts until collection**, so this is conditional.

**Proposed CAP = 15 tools per server.** Playwright (25) is capped to 15. With a total of about
70 known tools, 15 keeps any one server at about 20% or less of all rows.

Per-group counts after CAP (variant A: one group per server, grouping only by tool-name Jaccard
≥ 0.3; the overlaps can only be computed after collection):

| Group | Tools (capped) |
|---|---|
| fetch | 1 |
| filesystem | 14 |
| git | 12 |
| memory | 9 |
| sequential-thinking | 1 |
| time | 2 |
| Playwright | 15 (25 → CAP) |
| Chrome DevTools | unknown (scenarios below) |
| pg-mcp-guard | 3 (forced dev) |
| 6 registry servers | unknown |

| Chrome DevTools count | Variant A (Jaccard-only grouping) | Variant B (also "same upstream repo": 6 reference servers = one group of 39) |
|---|---|---|
| 10 | **feasible**: test = chrome-devtools, fetch, git, sequential-thinking, time = 26/67 (0.388); max group share test 0.462, dev 0.366 | **infeasible** (no subset satisfies ≤ 50% per group + ≥ 2 groups per side) |
| ≥ 15 (capped) | **feasible**: test = filesystem, git, sequential-thinking, time = 29/72 (0.403); max group share test 0.483, dev 0.349 | feasible only as test = Playwright + Chrome DevTools = 30/72 (0.417); max share test 0.500, **dev 0.929** (one group is almost all of dev) |

**Recommendation:** variant A (drop the "same upstream repo" clause I proposed earlier). Variant
B turns the 6 reference servers into one 39-tool block, so the split is either impossible or
puts only two browser-automation servers in test. The cost of variant A: test and dev both
contain reference servers that share a writing style, which is mild leakage and will be
stated in the report. The final split is computed only **after** collection, when the
registry servers' counts and the Jaccard overlaps are known. That split is then shown to you
before any label exists.

