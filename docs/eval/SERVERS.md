# Classifier eval: servers

> Nothing has been collected or launched for the eval yet.
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

## Servers in the set (collected on Haris's machine in step 4d, after approval)

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

## Registry additions: sample of ≤ 8 (awaiting your approval)

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
the README grep above.

| Registry name | Package @ version (published) | LICENSE file (archive sha256 prefix) | Telemetry grep | Proposal |
|---|---|---|---|---|
| io.github.mrfentmen/waqi-mcp | npm `waqi-mcp@1.0.0` (2026-09-21) | **none in package** (`9ab51998dd397d3c`) | 0 | **exclude** (no LICENSE file) |
| io.github.joepangallo/mcp-server-security-audit | npm `mcp-server-security-audit@1.0.3` (2026-03-01) | **none in package** (`c708bc69f274d2ea`) | 0 | **exclude** (no LICENSE file) |
| io.github.deliverd-dev/deliverd-screen | npm `@deliverd/screen@0.2.0` (2026-10-26) | MIT, `package/LICENSE` (`636a2e90385203f5`) | 0 | propose |
| io.github.PasiutusVovere/tickerrisk-mcp | PyPI `tickerrisk-mcp==0.1.3` (2026-09-27) | MIT, sdist `LICENSE` (`081ea6f90dc9d702`) | 0 | propose |
| io.github.howardpen9/grok-mcp | npm `grok-cli-mcp@0.2.0` (2026-06-10) | MIT, `package/LICENSE` (`d61f2b14599762e6`) | 0 | propose |
| io.github.FlagQuantum/flagquantum-mcp-server | PyPI `flagquantum-mcp-server==0.3.2` (2026-10-27) | Apache-2.0, sdist `LICENSE` (`3f52453418e11391`) | 0 | propose |
| io.github.nirholas/marketplace-mcp | npm `@three-ws/marketplace-mcp@0.1.3` (2026-10-10) | Apache-2.0, `package/LICENSE` (`41c3a2df65459bed`) | 1: `examples/README.md:90: - whale-wallet-tracking [analysis] 10 installs, free`, a listed skill, not product telemetry (my reading) | **ask** |
| io.github.ykshah1309/global-sentinel-mcp | PyPI `global-sentinel-mcp==0.1.1` (2026-04-20) | MIT, sdist `LICENSE` (`d227e244fcd2d3c4`) | 5: e.g. `README.md:6: … internet-infrastructure telemetry** into one alternative-data layer`, `README.md:191: Internet-infrastructure telemetry from Cloudflare's global network`. These are about the **data it serves**, not telemetry it sends (my reading) | **ask** |

Limits, stated:
- A README without a telemetry mention does not prove the server sends none.
- Tool counts are unknown until collection.
- The npm `license` field was **not** used.
- These 6 candidates come from unknown publishers.

**Collection only in an ephemeral runner:** proposed workflow
`docs/eval/proposed-workflows/eval-collect-registry.yml`, not active and not run.
- It uses `workflow_dispatch` on `ubuntu-24.04`, `contents: read`, and no secrets.
- `npm_config_ignore_scripts=true` (npm config docs; the docs do not say whether npx honours
  it, so the collector will also pass `--ignore-scripts`).
- `UV_NO_BUILD=1` (uv docs: "If set, uv will not build source distributions").
- `CI=true`.
- The collector it calls (`proveflow.eval.collect`) lands in step 4d.

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
