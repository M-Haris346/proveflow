# Classifier eval: servers (4a decisions applied; registry additions awaiting approval)

> Nothing has been collected or launched for the eval yet.
>
> Every column comes from the pinned package itself or its official page, fetched 2026-11-11:
> - versions and dates: the npm registry / PyPI JSON
> - licenses: the LICENSE file inside the pinned tarball/sdist, or the repo LICENSE when the
>   package ships none
> - tool counts: the pinned package's README or source
>
> Version rule: the newest stable release that is ≥ 14 days old (published ≤ 2026-10-28).
> Credentials rule (Haris): a dummy token only where official docs say startup does not
> validate it; otherwise the server is excluded. Real tokens are never used.

## Decisions (Haris, 2026-11-11)

| Topic | Decision |
|---|---|
| Reference servers (Note A) | **include**. License recorded as "MIT OR Apache-2.0 (repo LICENSE @6b36e3c)"; attribution in docs/DATASETS.md |
| everything | **exclude** |
| Desktop Commander | **exclude**. Its README says "Desktop Commander collects limited, pseudonymous telemetry … **Opt-out:** Ask Claude to "disable Desktop Commander telemetry" or set `"telemetryEnabled": false` in your config." PRIVACY.md: "Edit your configuration file at `~/.desktop-commander/config.json`". There is no launch flag or env var, and the docs do not say the opt-out works before the first run. Asking the model means a `tools/call`, which proveflow never sends. Rule: no applicable documented opt-out → exclude |
| Chrome DevTools MCP | **include, with its documented opt-out**. README 1.12.0: "Data collection is **enabled by default**. You can opt-out by passing the `--no-usage-statistics` flag" and "Collection is disabled if `CHROME_DEVTOOLS_MCP_NO_USAGE_STATISTICS` or `CI` env variables are set." The launch uses **both** the flag and `CHROME_DEVTOOLS_MCP_NO_USAGE_STATISTICS=1`, recorded in the dataset row |
| pg-mcp-guard | tools are **not** registered at import time: they are built inside `create_server(executor, principal, …)` (`app/server.py:275-380`), which needs an `Executor` (DB pools) and a verified principal. So the tools come **statically from source** at commit `b7a6dce`, provenance `"source"`. They go in the **dev split only** (Haris knows these tools; not blind) |
| GitHub MCP | **exclude**: needs `GITHUB_PERSONAL_ACCESS_TOKEN`, and the README does not say that startup skips validation |

## Servers in the set

| # | Server | Package @ version (published) | License (how verified) | Tools @ version (how counted) | Launch / provenance | Split constraint |
|---|---|---|---|---|---|---|
| 1 | fetch | PyPI `mcp-server-fetch==2026.10.24` (2026-10-25) | MIT OR Apache-2.0 (repo LICENSE @6b36e3c); sdist LICENSE + PKG-INFO say MIT | 1 (src) | `uvx mcp-server-fetch@2026.10.24`, tools/list | — |
| 2 | filesystem | npm `@modelcontextprotocol/server-filesystem@2.0.1` (2026-10-25) | MIT OR Apache-2.0 (repo LICENSE @6b36e3c; tarball ships none) | 14 (`registerTool` in dist) | `npx -y …@2.0.1 <empty tmpdir>`, tools/list | — |
| 3 | git | PyPI `mcp-server-git==2026.10.19` (2026-10-19) | MIT OR Apache-2.0 (repo LICENSE @6b36e3c); sdist LICENSE says MIT | 12 (`GitTools` enum) | `uvx mcp-server-git@2026.10.19 --repository <tmp git repo>`, tools/list | — |
| 4 | memory | npm `@modelcontextprotocol/server-memory@2.0.0` (2026-10-19) | MIT OR Apache-2.0 (repo LICENSE @6b36e3c) | 9 | `npx -y …@2.0.0` (memory file in tmp), tools/list | — |
| 5 | sequential-thinking | npm `@modelcontextprotocol/server-sequential-thinking@2.0.0` (2026-10-19) | MIT OR Apache-2.0 (repo LICENSE @6b36e3c) | 1 | `npx -y …@2.0.0`, tools/list | — |
| 6 | time | PyPI `mcp-server-time==2026.10.19` (2026-10-19) | MIT OR Apache-2.0 (repo LICENSE @6b36e3c); PKG-INFO says MIT | 2 | `uvx mcp-server-time@2026.10.19`, tools/list | — |
| 7 | Playwright MCP | npm `@playwright/mcp@0.0.83` (2026-09-28), gitHead `f183dad4` | Apache-2.0 (LICENSE in tarball) | 25 core (README "Core automation"); `--caps` extras not enabled | `npx -y @playwright/mcp@0.0.83 --headless`, tools/list | — |
| 8 | Chrome DevTools MCP | npm `chrome-devtools-mcp@1.12.0` (2026-10-22), gitHead `af283441` | Apache-2.0 (LICENSE in tarball) | **counted at collection** (21 tool modules; a static count is unreliable) | `npx -y chrome-devtools-mcp@1.12.0 --no-usage-statistics` + env `CHROME_DEVTOOLS_MCP_NO_USAGE_STATISTICS=1`, tools/list | — |
| 9 | pg-mcp-guard | Haris's repo, `0.1.0` @ `b7a6dce` | MIT (repo LICENSE) | 3 (`list_tables`, `describe_table`, `run_query`) | **source** (not tools/list); schemas are reconstructed from the `Field(...)` declarations, marked as such | **dev only** |

Confirmed so far: 1 + 14 + 12 + 9 + 1 + 2 + 25 + 3 = **67**, plus Chrome DevTools (unknown).

## Registry additions (by rule; awaiting your approval)

See §Registry rule below. The script is `scripts/eval_registry_select.py` (dev-only; it makes
network calls) and its rule is unit-tested in `tests/unit/test_registry_rule.py`.

REGISTRY_TABLE_PLACEHOLDER

## Split design (4b, implemented only after approval)

1. **Cap per server:** each server contributes at most `CAP` tools, a fixed number. When a
   server has more, the kept tools are a deterministic sample (seed `20261111`, sorted names,
   `random.Random(seed).sample`). The full list is still stored, and the cap only applies to
   eval rows. `CAP` gets proposed together with the feasibility numbers.
2. **Near-duplicate grouping:** servers with overlapping tool names stay in the same split, so
   the classifier is not tested on what it effectively saw in dev. Grouping rule: Jaccard
   similarity of tool-name sets ≥ 0.3, or the same upstream repo. (Desktop Commander, which
   overlaps filesystem, is excluded anyway.)
3. **Assignment:** enumerate group subsets; pick the test subset that minimizes
   |test_tools/total − 0.40|, subject to every group being ≤ 50% of the test tools and at least
   2 groups on each side; ties broken by sha256 of the sorted names. pg-mcp-guard is forced into
   dev.
4. **Feasibility first:** before splitting I show the per-group counts and whether the 40% /
   ≤ 50% rule is satisfiable at all. Reported also: the max single-group share in **both**
   splits.
5. **Reporting:** per-role precision/recall/F1 with Wilson 95% CIs **only where the relevant
   denominator is ≥ 10** (TP+FP for precision, TP+FN for recall). Otherwise the cell says
   "N < 10, not reported".
