# Classifier eval v2: fresh held-out servers (checkpoint 1c, Stage C)

> Prepared, **not collected**. 14 servers (run 3). The author triggers `eval-collect` with
> `servers=data/eval/roles/servers_v2.json`, `out_dir=out/v2`. No server below has been
> launched, asked for `tools/list`, or had its tools classified. Claude did read README
> excerpts while checking credentials and launch commands, and some excerpts name tools or
> parameters (see "Blindness during selection").

## Why a new set

The v1 test split was evaluated once (docs/eval/RESULTS.md) and is now burned. Classifier v2
was tuned on the v1 dev split (docs/eval/V2_CHANGELOG.md), so the only honest v2 number comes
from servers that were part of neither split.

## Selection rules

- **Exclusion:** every package in `data/eval/roles/servers.json` (v1 dev and test, including
  the two that failed to collect) is excluded.
- **Cutoff:** a release counts only if it was published on or before **2026-10-30**, i.e. at
  least 14 days before selection on 2026-11-13. Within a package, the newest stable release
  (digits and dots only, no pre-release) on or before the cutoff is pinned.
- **License (L):** read from the LICENSE file inside the pinned npm tarball or PyPI sdist/wheel,
  in memory, never executed. Package metadata alone is not enough.
- **Telemetry (T):** the pinned README is grepped as in v1. Any hit needs a documented opt-out
  before collection.
- **No real credentials (R4):** the registry entry declares no required env var and no required
  secret. No credential (real or dummy) is given to any server. Four picks' READMEs configure
  credentials, but none says whether listing tools needs them. They are kept, not dropped, and
  are expected to fail at collection (recorded attrition); see "Credentials".
- **Composition:** registry-sample passes + one hand-pick per category (14 expected; the
  15–20 target from the Stage C brief was soft, see "Rule changes" below). Two sources:
  1. **Registry sample:** `scripts/eval_registry_select.py` rules R1–R5, seed **20261201**, at
     most 8 drawn.
  2. **Hand-picked popular servers by category:** among R1–R5 survivors in the same registry
     snapshot, matched by category keywords on the server part of the registry name (after the
     last `/`), the description and the package id. Ranked by npm last-month downloads (npm
     downloads API, `https://api.npmjs.org/downloads/point/{period}[/{package}]`, with scoped
     names written with a literal slash, e.g. `/downloads/point/last-month/@slack/client`:
     github.com/npm/registry `docs/download-counts.md`, accessed 2026-11-13).
- **Category constraints (author, 2026-11-13):**
  - at most 2 browser-automation servers (dev is browser-heavy)
  - at least 1 LLM-proxy / model-API server (tests C9)
  - at least 1 VCS-hosting server that reads public repos (tests whether C2 over-labels public
    data as private)
  - at least 1 database, 1 messaging/email and 1 web fetch/search server
- **Blindness during selection (partial):**
  - Read: registry metadata (names, descriptions, package entries), npm download counts, and
    the LICENSE files and README telemetry greps of walked candidates.
  - For the 14 selected servers, Claude also grepped their READMEs for credential and launch
    lines. Those excerpts include some tool and parameter names: podman's container
    operations, pdf-suite's `filePath`/`outputPath`/`password`, and wander-agent's
    `find_mistake_fares` and `check_visa_requirement`. This is a small leak of held-out
    content to the classifier's author, and it is reported as a threat in RESULTS_V2.md.
  - No `tools/list` was run, and no classifier was run on any candidate.

## Rule changes during Stage C (recorded in order)

1. **Picker run 1 was discarded (implementation bugs, not judgment).**
   - The category regex was applied to the full registry name. `io.github.<owner>/…`
     matched `\bgithub\b`, so almost every survivor became "vcs-hosting". All 6 sample servers
     were labelled vcs-hosting, and the vcs-hosting "pick" was a charting library.
   - npm download lookups failed for many packages, so some rankings fell back to name order.
     Probable causes: rate limiting, and run 1 percent-encoding the `/` in scoped names, which
     the npm download-counts doc does not do for point queries.
   - Fix: match only the server part of the name (after the last `/`), retry 429/5xx with
     backoff, and record unknown counts as −1 (ranked last).
   - Run 1's picks were not used.
2. **Picker run 2 was stopped before completion** (its output was not read) because of two
   definition fixes from the author (2026-11-13). The author's two definition fixes were
   written before the author or reviewer saw run-1 picks. Run-1 picks were printed in Claude
   Code's session before the fixes arrived; run 1 was discarded for its own bugs, run 2 was
   stopped unread, run 3 is the only run used. The fixes:
   - **No round 2.** Total = registry-sample passes + one pick per category. Reason: round 2
     starts at "browser", and a second browser server would favour v2, whose rules were
     mostly fit on dev browser tools.
   - **Narrower llm-proxy regex.** "claude", "gpt", "llm" alone match servers that merely
     mention an MCP client. The new regex matches providers and API phrasing only:
     `\b(openai|anthropic|gemini|ollama|openrouter|deepseek|mistral|groq|together ?ai|litellm)\b|\b(llm|model|chat) ?(api|completion|completions|gateway|proxy)\b`
   The RULE text embedded in the output says 'before picks'; that means before the author or
   reviewer saw run-1 picks, as recorded in 'Rule changes during Stage C'.
3. **Picker run 3 (final)** uses both fixes. Its npm download counts are stored as a snapshot,
   so a re-run reproduces the same ranking. Output sha256
   `f9f1f70d7b451c1465a5ea7954d966dd76c50ee7d9aa001b3ddb2528dbbfd4db`.
4. **Label fix after run 3; picks unchanged.**
   - Bug: registry-sample rows were categorised on their package string
     `npm:<id>@<ver>`, and the `npm:` prefix matched `\bnpm\b` (dev-tools).
   - Fix: sample rows now use the same text as hand-picks: `<server part> <description>
     <package identifier>`, where the identifier has no `npm:`/`pypi:` prefix and no `@version`
     (`package_identifier()` in `scripts/eval_handpick.py`, unit-tested).
   - Re-run on the same cache and snapshot (no `--fetch-missing`; snapshot sha256 unchanged).
     Output sha256 `a8106f48651c907154b173fc92501ace4f3f3131cfbaa2bc8ab18a9c16e14d69`.
   - Diff vs run 3: `rule`, `cutoff`, `picked`, `ranked`, `walk_log` and `total` are identical.
     Only `registry_sample` `category`/`all_categories` changed, in 5 rows:
     - glyphic and bankregpulse: dev-tools → other (both in the set)
     - pdf-suite: still "file"; dev-tools dropped from `all_categories`
     - aena-mcp and scopeguard: dev-tools → other (both failed L/T, not in the set)
   - `servers_v2.json` now uses the fixed labels.

## Limitations of the selection

- **"Popular" means popular among credential-free registry survivors, not popular MCP servers
  overall.** R4 (no required env var or secret) removes most well-known servers in
  vcs-hosting, messaging and database, because they need a token or a connection string.
  The picks there are often in the low hundreds of monthly npm downloads. Each pick's
  download count is reported in the table below.
- Download counts are a snapshot at selection time (stored with the picker output) and
  change daily.
- Category is a keyword match on registry metadata. A pick can match a category only
  incidentally; such picks are flagged below, not swapped.
- The registry sample is random among all survivors, so its servers can fall in any category
  (or none).

## Expected rule exposure by category

Which v2 rules (V2_CHANGELOG.md) a category is likely to exercise. This is an expectation
from the rule definitions, not from the servers' tools.

| Category | v2 rules most exposed | What the held-out run can show |
|---|---|---|
| browser | C1 save-to-file, C4 entered text, C5 UI-only actions, C7 navigate, C8 URL, C11a capture nouns, C11d arbitrary code, C12 headers | whether the browser rules (most dev wins) carry over to another browser server |
| llm-proxy | **C9** model + prompt, C8 (base URL params) | whether C9 (single-server evidence) holds |
| vcs-hosting | **C2** repository param → private, C3 VCS verbs, C6 write-tool descriptions, C8 | whether C2 **over-labels public repository data as private** (FP risk) |
| database | C6 (write tools mention table/record), C11c untrusted phrasing, v1 SQL param | private recall on rows; C6 FP/FN trade-off |
| messaging | C6, v1 egress verbs and recipient params, C11c | source + private on messages; sink on send |
| web | C8 URL sink, C11a (html), C1 (save output) | the known fetch(url) gap, now weight 0.5 |
| file | C1 output path, C6 write-tool descriptions | the C10 revert (plural `paths`) shows up here as private FN |
| dev-tools | C11d (exec), C12 headers, C1, C3 | generalization outside browser/git |

## Run 3 result: constraint check and flags (reported, NOT swapped)

Total: **14** = 6 registry-sample passes + 8 hand-picks (one per category).

| Constraint (author) | Met nominally | Flag |
|---|---|---|
| ≤ 2 browser | yes (1: `a11y-scanner`) | none |
| ≥ 1 LLM-proxy / model API | `purmemo` | **matched only "gemini"**: "AI memory across Claude, ChatGPT, Gemini, and Cursor". It is a memory service, not a model API, so **C9 is effectively untested**. The ranking's #1, `@mrfentmen/openrouter-mcp` (4,194 dl), failed L (no LICENSE file) |
| ≥ 1 VCS hosting reading public repos | `bitbucket` | The category fits (Bitbucket Cloud/Server API). The README configures `BITBUCKET_USERNAME`/`BITBUCKET_PASSWORD` in every example, and whether it lists tools or reads public repos without an account is not documented |
| ≥ 1 database | `mssql-reader` (+ sample `meok-koikeeper`) | `mssql-reader` needs a SQL Server connection (README: `SQL_USERNAME`/`SQL_PASSWORD` required for sql/windows modes). `meok-koikeeper` matched "database" for a built-in koi-varieties reference table, not a user database |
| ≥ 1 messaging / email | `emailmd` | **matched incidentally**: "Render markdown into email-safe HTML, lint drafts…, preview emails". An email formatter, not a mail or chat service, so the requirement is **effectively not met** |
| ≥ 1 web fetch / search | `perplexity` | The category fits (web search via Perplexity's API). The README configures `PERPLEXITY_API_KEY` in every example |

Other category notes:
- `glyphic` (diagram generation) and `bankregpulse` (banking-regulation brief) were
  "dev-tools" in run 3 only because of the `npm:` label artifact. After the label fix
  ("Rule changes" item 4) they are "other". Picks unchanged.
- `tabellio` ("file") and `compound-memory` ("file", sample) are agent-memory stores. Both matched "markdown".

## Credentials (no real credential anywhere)

- No server gets a credential, real or dummy.
- **Expected to fail without credentials:** `purmemo`, `bitbucket`, `mssql-reader` and `perplexity`. Their READMEs set an API key, username/password or SQL login in every example.
  - None of the four declares a required env var in the registry (so they passed R4).
  - Whether they start and answer `tools/list` without credentials is not documented.
  - No dummy value is set. If they fail, that is recorded attrition, like v1's two failures.
- **Non-credential env:**
  - `compound-memory`: `COMPOUND_MEMORY_ROOT` and `TABELLIO_STORE` (for `tabellio`) point into the collector's temp work dir, so third-party writes stay in the ephemeral runner (as v1 did for the memory server).
  - `COMPOUND_MEMORY_AGENT_ID=proveflow-eval` is a non-secret identifier that the registry entry describes as required for a multi-agent store.
- **Launch commands follow each README's documented MCP command**, pinned exactly (forms documented in docs/PINNING.md):
  - `tabellio`: `-p tabellio@0.1.12 tabellio-mcp`. The README names `tabellio-mcp` as the MCP stdio bin.
  - `emailmd`: `… mcp`, per the README's `npx emailmd mcp`.
  - `compound-memory` and `meok-koikeeper`: `uvx --from pkg==ver <console script>`. The script names come from the README and the wheel's `entry_points.txt`.
- **Not provided on the runner:** a Playwright browser (`a11y-scanner`) and a Podman/Docker runtime (`podman`). Whether they are needed just to list tools is not documented.

## Reproduce

- **Registry cache (NOT committed):** `scripts/eval_registry_select.py <dir> --seed 20261201 --cutoff 2026-10-30 --sample-max 8 --exclude data/eval/roles/servers.json`.
  - Fetched 2026-11-13. Page files were written 11:11:34–11:27:49 UTC.
  - 63,345 latest entries, 10,204 R1–R5 survivors (after excluding the v1 packages).
  - sha256 over the sorted file listing and contents (for each of `pages-latest/page-*.json` and `selection.json`, sorted by relative POSIX path: `path + "\n" + bytes`): `51188c54308009c7196ebf0d2de724a69dd3b59badbcb53b38e3b98adbe77db7` (635 files). A re-fetch on another day will differ.
- **Downloads snapshot (committed, unchanged copy of run 3's file):** `data/eval/roles/handpick_downloads_snapshot.json`.
  - sha256 `4c17a3b8b6c94c467181ff9dfe66f31978c593471995763a9e64076542dc527f`.
  - npm last-month counts for the 1,261 npm candidates, from `https://api.npmjs.org/downloads/point/last-month/<package>`. Fetched during run 3, 2026-11-13 11:36–12:05 UTC; the file was written 12:05:11 UTC. 3 counts are unknown (−1).
- **Picker:** `uv run python scripts/eval_handpick.py <registry cache dir> data/eval/roles/handpick_downloads_snapshot.json <out.json>`.
  - It stops if any npm candidate is missing from the snapshot, unless `--fetch-missing` is given (which would make a new run).
- **Identity check (2026-11-13):** the repo script, run against the same cache and snapshot without `--fetch-missing`, produced output byte-identical to run 3's `picks.json`. `cmp` reported no difference, both are 270,051 bytes, and both have sha256 `f9f1f70d7b451c1465a5ea7954d966dd76c50ee7d9aa001b3ddb2528dbbfd4db`. The snapshot's sha256 was the same before and after.
  - Run 3's output was confirmed first: its file was modified after run 3 started (16:36:50 local), and its `rule` contains "no second round".
  - The output is written with the platform's default newlines, so the identity holds on the same OS.
- **Current script output (after the label fix):** sha256
  `a8106f48651c907154b173fc92501ace4f3f3131cfbaa2bc8ab18a9c16e14d69`. Running today's
  `scripts/eval_handpick.py` on the same cache and snapshot reproduces this file, not run 3's
  (see "Rule changes" item 4 for the exact diff).
- **What the picker reads:** besides registry metadata and the snapshot, it reads each walked candidate's LICENSE and README from the pinned npm tarball or PyPI archive (in memory only).

## Collection attempts

- **eval-collect run #2** (GitHub Actions 43432066358, 2026-11-13, commit 016e39d) is **not a
  v2 collection**.
  - Its log records the input defaults: `SERVERS: data/eval/roles/servers.json` and
    `OUT_DIR: out`. So it collected the v1 set into the artifact `eval-tools`.
  - Cause: the workflow's defaults silently select the v1 set. Nothing printed the chosen
    file, and nothing checked the result. Claude's Stage C report named the v2 artifact
    without checking what the default inputs produce.
  - Fix (next commit):
    - the first job step validates, prints and step-summarizes the resolved inputs;
    - the artifact name is derived from `out_dir` (`out/v2` → `eval-tools-v2`);
    - a step after collection fails the job unless the summary's server ids equal the
      chosen file's ids (`python -m proveflow.eval.verify_collection`).
    - Tests: `tests/safety/test_eval_collect_workflow.py`.
  - Run #2's output is not used for anything in checkpoint 1c.

## Decision before collection

No supplement round. Servers that fail without credentials are
recorded attrition. RESULTS_V2 reports per-rule exposure on the
held-out set (how many held-out tools each v1/v2 rule fired on);
a rule with zero exposure is reported as untested, not as passing.

## Failure classification (written before reading stderr)

Each failed v2 server is classified from its stderr_tail and, if
needed, by launching it locally with the same command (tools/list
only, no tools/call):
- Collector-caused: our launch command or client is wrong (wrong bin
  or module name, wrong --from/-p form, a protocol-negotiation bug in
  our collector, a setup step we declared but did not perform). These
  are fixed and the WHOLE v2 set is re-collected once (run recorded).
- Server-caused: the package itself fails (import error, missing
  credential, crash, requires install scripts or a source build that
  our safety flags --ignore-scripts/--no-build forbid, needs a runtime
  the v1 collection also did not provide). These stay attrition, as in v1.
No server is added, swapped or dropped. The safety flags are not relaxed.
The classification of each server and its evidence line are recorded here.

## Final set (14 servers; collected by the author, not yet)

| id | source | category (after label fix) | package @ pinned version | license (file) | npm downloads (snapshot) | launch | env |
|---|---|---|---|---|---|---|---|
| `glyphic` | registry | other | npm `@glyphicjs/mcp-server@1.0.2` | MIT | n/a (sample) | `npx -y @glyphicjs/mcp-server@1.0.2` | none |
| `compound-memory` | registry | file | pypi `compound-memory@0.5.12` | MIT | n/a (sample) | `uvx --from compound-memory==0.5.12 compound-memory-server` | `COMPOUND_MEMORY_ROOT`, `COMPOUND_MEMORY_AGENT_ID` |
| `pdf-suite` | registry | file | npm `pdf-suite-mcp@2.1.2` | MIT | n/a (sample) | `npx -y pdf-suite-mcp@2.1.2` | none |
| `wander-agent` | registry | other | pypi `wander-agent@0.1.1` | MIT | n/a (sample) | `uvx wander-agent@0.1.1` | none |
| `bankregpulse` | registry | other | npm `bankregpulse-mcp-server@1.3.0` | MIT | n/a (sample) | `npx -y bankregpulse-mcp-server@1.3.0` | none |
| `meok-koikeeper` | registry | database | pypi `meok-koikeeper-ai-mcp@1.0.3` | MIT | n/a (sample) | `uvx --from meok-koikeeper-ai-mcp==1.0.3 meok_koikeeper_ai_mcp` | none |
| `a11y-scanner` | popular | browser | npm `mcp-accessibility-scanner@1.1.1` | MIT | 10466 | `npx -y mcp-accessibility-scanner@1.1.1` | none |
| `purmemo` | popular | llm-proxy | npm `purmemo-mcp@12.9.5` | MIT | 3424 | `npx -y purmemo-mcp@12.9.5` | none |
| `bitbucket` | popular | vcs-hosting | npm `bitbucket-mcp@5.0.5` | MIT | 24432 | `npx -y bitbucket-mcp@5.0.5` | none |
| `mssql-reader` | popular | database | npm `@connorbritain/mssql-mcp-reader@0.3.1` | MIT | 11480 | `npx -y @connorbritain/mssql-mcp-reader@0.3.1` | none |
| `emailmd` | popular | messaging | npm `emailmd@0.13.2` | MIT | 19455 | `npx -y emailmd@0.13.2 mcp` | none |
| `perplexity` | popular | web | npm `@perplexity-ai/mcp-server@1.2.1` | MIT | 132575 | `npx -y @perplexity-ai/mcp-server@1.2.1` | none |
| `tabellio` | popular | file | npm `tabellio@0.1.12` | MIT | 2932 | `npx -y -p tabellio@0.1.12 tabellio-mcp` | `TABELLIO_STORE` |
| `podman` | popular | dev-tools | npm `podman-mcp-server@0.0.15` | Apache-2.0 | 9383 | `npx -y podman-mcp-server@0.0.15` | none |

Registry-sample servers that failed (not in the set):

- `io.github.MrGo2/aena-mcp` (npm:mcp-aena@0.1.3): ask: README mentions telemetry/analytics: needs a documented opt-out
- `io.github.Alex-Dev-Web-C-DE/scopeguard` (npm:@alex-dev-web-c-de/scopeguard-mcp@1.0.1): exclude: no LICENSE file in the package

## Hand-pick walk per category (run 3)

Every candidate walked before the pick, in ranking order. Candidates after the pick were not inspected.

**browser** (224 candidates)

- `browser-devtools-mcp` (downloads 19984): skipped: exclude: LICENSE text not recognized as one permissive license
- `mcp-accessibility-scanner` (downloads 10466): PICKED (round 1)

**llm-proxy** (113 candidates)

- `@mrfentmen/openrouter-mcp` (downloads 4194): skipped: exclude: no LICENSE file in the package
- `purmemo-mcp` (downloads 3424): PICKED (round 1)

**vcs-hosting** (107 candidates)

- `@gitkraken/gk` (downloads 289690): skipped: exclude: no LICENSE file in the package
- `bitbucket-mcp` (downloads 24432): PICKED (round 1)

**database** (268 candidates)

- `run402-mcp` (downloads 25423): skipped: ask: README mentions telemetry/analytics: needs a documented opt-out
- `@connorbritain/mssql-mcp-reader` (downloads 11480): PICKED (round 1)

**messaging** (154 candidates)

- `emailmd` (downloads 19455): PICKED (round 1)

**web** (188 candidates)

- `@perplexity-ai/mcp-server` (downloads 132575): PICKED (round 1)

**file** (589 candidates)

- `emailmd` (downloads 19455): skipped: already picked for an earlier category
- `@adeu/mcp-server` (downloads 4969): skipped: exclude: no LICENSE file in the package
- `@mcp-z/mcp-pdf` (downloads 4222): skipped: exclude: no LICENSE file in the package
- `@mcp-z/mcp-pdf` (downloads 4222): skipped: exclude: no LICENSE file in the package
- `@guardbee/mcp-secret-scanner` (downloads 3693): skipped: exclude: no LICENSE file in the package
- `tabellio` (downloads 2932): PICKED (round 1)

**dev-tools** (276 candidates)

- `kubernetes-mcp-server` (downloads 199511): skipped: ask: README mentions telemetry/analytics: needs a documented opt-out
- `emailmd` (downloads 19455): skipped: already picked for an earlier category
- `podman-mcp-server` (downloads 9383): PICKED (round 1)

## Appendix: full ranked candidate list per category (run 3)

npm candidates by last-month downloads (descending, ties by package name; -1 = unknown), then PyPI candidates by name. From `scripts/eval_handpick.py` output.

<details><summary>browser: 224 candidates</summary>

| # | package | downloads | registry name |
|---|---|---|---|
| 1 | `npm:browser-devtools-mcp@0.9.1` | 19984 | io.github.serkan-ozal/browser-devtools-mcp |
| 2 | `npm:mcp-accessibility-scanner@1.1.1` | 10466 | io.github.JustasMonkev/mcp-accessibility-scanner |
| 3 | `npm:next-finance-mcp@0.9.163` | 7803 | io.github.paivapiovesan/next-finance |
| 4 | `npm:smart-web-mcp@1.10.19` | 5178 | io.github.jojo-labs/smart-web |
| 5 | `npm:@agent360/browser-mcp@1.31.0` | 5007 | io.github.Agent360dk/browser-mcp |
| 6 | `npm:safari-mcp@2.23.0` | 4392 | io.github.achiya-automation/safari-mcp |
| 7 | `npm:poltertab@1.12.0` | 3939 | io.github.abhinav162/poltertab |
| 8 | `npm:kogiqa-mcp@1.3.103` | 3743 | com.atagon/kogiqa-mcp |
| 9 | `npm:@kaptionai/mcp-extension@0.5.11` | 3462 | io.github.Kaption-AI/mcp-extension |
| 10 | `npm:@agent-infra/mcp-server-browser@latest` | 3355 | io.github.bytedance/mcp-server-browser |
| 11 | `npm:chrome-bridge-mcp@1.32.1` | 3162 | io.github.frsorrentino/chrome-bridge |
| 12 | `npm:@shiplightai/mcp@0.2.3` | 3022 | ai.shiplight/shiplight |
| 13 | `npm:mcpbrowser@0.2.1` | 2375 | io.github.cherchyk/browser |
| 14 | `npm:tabhand@0.10.1` | 2171 | dev.tabhand/tabhand |
| 15 | `npm:cloakbrowser-mcp@1.15.1` | 2168 | io.github.swimmwatch/cloakbrowser-mcp |
| 16 | `npm:dsh-verify@0.9.6` | 2168 | io.github.263311487-ux/dsh-verify |
| 17 | `npm:reflex-browser@0.4.12` | 2128 | com.reflexmcp/reflex |
| 18 | `npm:unbrowse@12.5.0` | 1901 | io.github.unbrowse-ai/unbrowse |
| 19 | `npm:@ainative/browser-mcp@1.1.2` | 1813 | io.github.AINative-Studio/ainative-browser-mcp |
| 20 | `npm:@walkeros/mcp-source-browser@4.5.0` | 1750 | io.walkeros/source-browser |
| 21 | `npm:tada-mcp@0.1.44` | 1736 | dev.taada/tada |
| 22 | `npm:fablecut@1.18.0` | 1720 | io.github.ronak-create/fablecut |
| 23 | `npm:playwright-report-mcp@3.4.0` | 1663 | io.github.hubertgajewski/playwright-report-mcp |
| 24 | `npm:@roveapi/mcp@1.18.0` | 1652 | io.github.noncelogic/rove |
| 25 | `npm:perplexity-browser-mcp@1.4.0` | 1584 | io.github.xs1128/perplexity-browser-mcp |
| 26 | `npm:word-to-markdown@0.9.0` | 1439 | io.github.benbalter/word-to-markdown |
| 27 | `npm:@ticktockbent/charlotte@0.1.3` | 1415 | io.github.TickTockBent/charlotte |
| 28 | `npm:agentic-browser-mcp@1.4.0` | 1365 | io.github.davarion-tech/agentic-browser |
| 29 | `npm:playproof@0.3.2` | 1284 | io.github.EmirhanOzl/playproof |
| 30 | `npm:@eurafaeldecarvalho/browser-scraper@0.8.3` | 1271 | io.github.eurafaeldecarvalho/browser-scraper |
| 31 | `npm:yab-mcp@0.2.1` | 1266 | com.yetanotherbrowser/yab |
| 32 | `npm:cssprobe-cli@0.3.0` | 1244 | io.github.mack-peng/cssprobe-cli |
| 33 | `npm:toolaby@1.15.1` | 1232 | app.toolaby/toolaby |
| 34 | `npm:@agentutility/mcp-browser-workflow@0.1.1` | 1207 | ai.agentutility/mcp-browser-workflow |
| 35 | `npm:layoza@0.1.4` | 1200 | io.github.layoza/layoza |
| 36 | `npm:rea-captcha@0.3.1` | 1191 | io.github.masakaai/rea-captcha |
| 37 | `npm:devloop-mcp@0.13.0` | 1164 | io.github.vincentvella/devloop |
| 38 | `npm:@mcpware/pagecast@0.1.0` | 1124 | io.github.mcpware/pagecast |
| 39 | `npm:ghostlight@2.0.2` | 1124 | org.sylin/ghostlight |
| 40 | `npm:uisandbox-mcp@0.5.3` | 1095 | io.github.Ideelab/uisandbox |
| 41 | `npm:sitelooper@0.7.0` | 1072 | io.github.restspace/sitelooper |
| 42 | `npm:webpeel@0.3.0` | 1068 | io.github.JakeLiuMe/webpeel |
| 43 | `npm:one-search-mcp@1.2.4` | 1062 | io.github.yokingma/one-search-mcp |
| 44 | `npm:openscreenshot@2.5.2` | 996 | io.github.PGHQdev/openscreenshot |
| 45 | `npm:real-browser-mcp@1.2.1` | 972 | io.github.ofershap/real-browser |
| 46 | `npm:hotedit@0.5.0` | 916 | io.github.Thewhey-Brian/hotedit |
| 47 | `npm:playwright-stealth-mcp-server@0.2.3` | 885 | com.pulsemcp/playwright-stealth |
| 48 | `npm:@allchemylabs/aether-wcag-scanner@1.0.8` | 831 | io.github.allchemylabs/aether-wcag-scanner |
| 49 | `npm:keyframe-mcp@0.6.0` | 819 | io.github.kendall8388/keyframe |
| 50 | `npm:uivision-mcp-bridge@1.7.18` | 817 | io.github.A9T9/uivision-mcp |
| 51 | `npm:chmi-mcp@1.0.0` | 781 | io.github.mrfentmen/chmi-mcp |
| 52 | `npm:adam-mcp@0.2.0` | 736 | io.github.Arudchayan/adam-mcp |
| 53 | `npm:caishi-mcp@1.0.1` | 736 | io.github.ZhongQuinnKing/caishi |
| 54 | `npm:@apireno/domshell@2.0.10` | 735 | io.github.apireno/domshell |
| 55 | `npm:@mrfentmen/ucsc-genome-mcp@1.0.1` | 726 | io.github.mrfentmen/ucsc-genome-mcp |
| 56 | `npm:mcp-wallet-signer@0.1.3` | 698 | io.github.nikicat/mcp-wallet-signer |
| 57 | `npm:@devinwangd/cloak-browser-mcp@0.2.0` | 691 | io.github.devinwang/cloak-browser-mcp |
| 58 | `npm:@page-scanner/mcp@0.4.5` | 687 | io.github.sbd530/page-scanner |
| 59 | `npm:@paramability/mcp@1.0.0` | 666 | app.paramability/mcp |
| 60 | `npm:bryg-mcp@1.0.0` | 661 | io.github.flexiblepackage/bryg |
| 61 | `npm:google-news-scraper-mcp@0.1.2` | 657 | io.github.lewisdonovan/google-news |
| 62 | `npm:@voidly/pay-mcp@0.7.4` | 643 | io.github.voidly-ai/pay-mcp |
| 63 | `npm:@putervision/behavior-mcp@0.4.1` | 622 | io.github.putervision/behavior-mcp |
| 64 | `npm:@dynamicu/chromedebug-mcp@2.9.6` | 614 | io.github.dynamicupgrade/chromedebug |
| 65 | `npm:native-devtools-mcp@0.10.1` | 614 | io.github.sh3ll3x3c/native-devtools |
| 66 | `npm:vibe-testing@0.4.6` | 586 | io.github.AishwaryShrivastav/vibe-testing |
| 67 | `npm:agent-webbridge@1.3.3` | 555 | io.github.jeet-dhandha/agent-webbridge |
| 68 | `npm:@vibebrowser/mcp@0.3.6` | 551 | io.github.VibeTechnologies/vibe-mcp |
| 69 | `npm:connections-mcp@2.253.0` | 531 | io.github.Lunarwerx/connections |
| 70 | `npm:view-sim-mcp@1.0.0` | 516 | io.github.itelo/view-sim |
| 71 | `npm:firefox-addons-mcp@1.0.0` | 512 | io.github.mrfentmen/firefox-addons-mcp |
| 72 | `npm:seo-notary@0.1.0` | 496 | io.github.raxocode/seo-notary |
| 73 | `npm:@yuanhuakk/js-reverse-mcp@3.0.0` | 495 | io.github.YuanHuakk/JSReverser-MCP |
| 74 | `npm:@yuanhuakk/js-reverse-mcp@2.5.0` | 495 | io.github.YuanHuakk/js-reverse-mcp |
| 75 | `npm:public-browser@3.0.0` | 493 | io.github.Silbercue/public-browser |
| 76 | `npm:deepbom@2.5.0` | 492 | io.github.JunHwan-Kwon/deepbom |
| 77 | `npm:figranium-mcp@1.4.0` | 484 | io.github.figranium/figranium-mcp |
| 78 | `npm:@dockndevai/mcp-cdp@0.2.3` | 482 | io.github.dockndevai/mcp-cdp |
| 79 | `npm:crawlio-browser@1.11.0` | 464 | app.crawlio/crawlio-browser |
| 80 | `npm:@briefgate/mcp@0.10.7` | 462 | io.github.sekera-radim/briefgate |
| 81 | `npm:knownfix@0.3.17` | 460 | io.github.b-hash88/knownfix |
| 82 | `npm:mac-control-mcp@0.10.3` | 450 | io.github.AdelElo13/mac-control-mcp |
| 83 | `npm:parallel-browser-mcp@0.1.14` | 450 | io.github.etairl/parallel-browser-mcp |
| 84 | `npm:web-task-api@0.10.1` | 444 | io.github.jojo-labs/web-task-api |
| 85 | `npm:web-task-api@0.2.4` | 444 | io.github.rich-jojo/web-task-api |
| 86 | `npm:@weavatrix/wvq@0.1.0-alpha.5` | 437 | io.github.Weavatrix/weavatrix-quality |
| 87 | `npm:@mrfentmen/pod-upload-mcp@1.0.0` | 420 | io.github.mrfentmen/pod-upload-mcp |
| 88 | `npm:crumbtrail-node@0.3.0` | 413 | io.github.CrumbtrailDev/crumbtrail |
| 89 | `npm:@feedthrough/mcp@0.4.0` | 403 | io.github.feedthrough/feedthrough |
| 90 | `npm:selenium-webdriver-mcp@0.4.6` | 402 | io.github.pshivapr/selenium-mcp |
| 91 | `npm:b4n1-web@0.12.1` | 399 | io.github.B4N1-com/b4n1web |
| 92 | `npm:@spark-apps/quickpeek@1.2.10` | 386 | co.quickpeek/quickpeek |
| 93 | `npm:browserbash-cli@1.5.1` | 383 | io.github.PramodDutta/browserbash |
| 94 | `npm:capmonster-mcp-patchright@1.1.3` | 381 | io.github.CapMonsterCloud/capmonster-mcp-patchright-captcha-solver |
| 95 | `npm:@pilotgentic/mcp-server@1.0.0` | 377 | com.pilotgentic/mcp-server |
| 96 | `npm:camoufox-mcp@1.0.0` | 375 | io.github.baixianger/camoufox-mcp |
| 97 | `npm:@dir-ai/voyager-browser@0.7.0` | 373 | io.github.dir-ai/voyager-browser |
| 98 | `npm:@uindow/cli@0.1.12` | 371 | io.github.uindow/uindow |
| 99 | `npm:a11yscope-mcp@0.3.0` | 358 | io.github.perceivable/a11yscope |
| 100 | `npm:@peekdev/mcp@0.1.0-alpha.24` | 355 | io.github.Cubenest/peek-mcp |
| 101 | `npm:bun-uia@1.9.1` | 355 | io.github.ObscuritySRL/bun-uia |
| 102 | `npm:@kitewright/mcp@0.1.1` | 337 | io.github.kitewright/mcp |
| 103 | `npm:runbook-ai-mcp@1.1.0` | 331 | io.github.runbook-ai/browser-agent |
| 104 | `npm:leapfrog-mcp@0.7.4` | 322 | io.github.anthonybono21-cloud/leapfrog |
| 105 | `npm:@readystack/autorenew-signup-lint@1.0.5` | 320 | io.github.jmshinhwa/autorenew-signup-lint |
| 106 | `npm:@readystack/optout-signal-lint@0.1.1` | 314 | io.github.jmshinhwa/optout-signal-lint |
| 107 | `npm:@readystack/livewire-client-surface-audit@1.0.4` | 313 | io.github.jmshinhwa/livewire-client-surface-audit |
| 108 | `npm:aether-browser@0.2.2` | 309 | io.github.AetherAI3/agent-browser |
| 109 | `npm:@sidebutton/server@1.5.2` | 304 | io.github.sidebutton/sidebutton |
| 110 | `npm:qualien-mcp@0.6.2` | 304 | io.github.qualienai/qualien-mcp |
| 111 | `npm:@gaforov/selenium-mcp@0.3.0` | 295 | io.github.gaforov/selenium-mcp |
| 112 | `npm:appcontext-mcp@0.1.0` | 293 | dev.appcontext/appcontext |
| 113 | `npm:@kaael1/mcp-power-automate@0.4.1` | 285 | io.github.kaael1/mcp-power-automate |
| 114 | `npm:@uplink-code/mcp@0.1.4` | 284 | build.uplink/uplink |
| 115 | `npm:smolanalytics@0.21.0` | 282 | io.github.Arjun0606/smolanalytics |
| 116 | `npm:@yawlabs/vew-mcp@0.4.3` | 281 | io.github.YawLabs/vew-mcp |
| 117 | `npm:neo-vision@0.2.2` | 276 | io.github.matthewalexong/neo-vision |
| 118 | `npm:@domscout/mcp@1.0.8` | 275 | io.github.jkresearch8/domscout |
| 119 | `npm:doppel-mcp@0.7.2` | 275 | io.github.Samrj12/doppel |
| 120 | `npm:@mtop-devtools/mcp-server@1.37.0` | 274 | io.github.F-loat/mtop-devtools |
| 121 | `npm:playwright-trace-decoder-mcp@0.2.3` | 274 | io.github.vola-trebla/playwright-trace-decoder-mcp |
| 122 | `npm:stealth-agent-browser-mcp@0.2.0` | 274 | io.github.ykshah1309/stealth-agent-browser-mcp |
| 123 | `npm:safari-devtools-mcp@1.8.1` | 269 | io.github.HayoDev/safari-devtools-mcp |
| 124 | `npm:@blueprint-chart/mcp@0.2.1` | 266 | io.github.blueprint-chart/mcp |
| 125 | `npm:@mcpware/ui-annotator@0.1.1` | 266 | io.github.mcpware/ui-annotator-mcp |
| 126 | `npm:@secforge/chrome-devtools-mcp@1.10.1004` | 266 | io.github.secforge/chrome-devtools-mcp |
| 127 | `npm:mcp-server-terminal@1.0.3` | 266 | io.github.aybelatchane/mcp-server-terminal |
| 128 | `npm:@keyid/agent-kit@0.4.1` | 265 | io.github.KeyID-AI/keyid |
| 129 | `npm:ritoko@0.2.0` | 264 | io.github.Swih/ritoko |
| 130 | `npm:lionscraper@1.0.6` | 251 | io.github.dowant/lionscraper-node |
| 131 | `npm:pagerunner@0.8.0` | 251 | io.github.Enreign/pagerunner |
| 132 | `npm:linkedin-toolkit-mcp@2.1.0` | 248 | io.github.FormatixAI/linkedin-toolkit |
| 133 | `npm:zen-mcp@1.2.1` | 247 | io.github.sh6drack/zen-mcp |
| 134 | `npm:chromium-bridge@0.5.3` | 243 | io.github.dashi96/chromium-bridge |
| 135 | `npm:@async23/chrome-devtools-mcp@1.7.0` | 242 | io.github.Async23/chrome-devtools-mcp |
| 136 | `npm:openevidence-mcp@0.2.1` | 242 | io.github.bakhtiersizhaev/openevidence-mcp |
| 137 | `npm:@zamery/browser-mcp@0.1.2` | 234 | io.github.maemreyo/zamery-browser |
| 138 | `npm:bookmarks-mcp@0.1.0` | 225 | io.github.Fisher521/bookmarks-mcp |
| 139 | `npm:storymapper@1.0.1` | 225 | io.github.TomAtAP/storymapper |
| 140 | `npm:wick-mcp@0.1.0` | 225 | io.github.myleshorton/wick |
| 141 | `npm:wick-mcp@0.5.0` | 225 | io.github.wickproject/wick |
| 142 | `npm:@perfonext/profiler-mcp@0.7.3` | 221 | io.github.souvikdu/perfonext-profiler-mcp |
| 143 | `npm:cowork-qa-mcp@0.1.1` | 221 | io.github.inSideos-designs/cowork-qa |
| 144 | `npm:aethyn-browser-mcp@0.1.1` | 218 | io.github.aethynio/aethyn-browser-mcp |
| 145 | `npm:lan-direct@1.0.2` | 216 | io.github.farshadmomo/lan-direct |
| 146 | `npm:@matware/e2e-runner@1.3.0` | 215 | io.github.fastslack/e2e-runner |
| 147 | `npm:flakiness-knowledge-graph-mcp@0.2.2` | 210 | io.github.vola-trebla/flakiness-knowledge-graph-mcp |
| 148 | `npm:obscura-mcp@0.1.1` | 204 | io.github.Metadrama/obscura-mcp |
| 149 | `npm:opengame-browser-game-mcp@0.1.3` | 202 | io.github.opengameapp/browser-game |
| 150 | `npm:playwright-wizard-mcp@0.1.6` | 202 | io.github.oguzc/playwright-wizard-mcp |
| 151 | `npm:snapstack-server@1.2.3` | 202 | io.github.bgaze/snapstack-server |
| 152 | `npm:@dinesh-nalla-se/chrome-devtools-mcp@0.10.2` | 201 | io.github.dinesh-nalla-se/chrome-devtools-mcp |
| 153 | `npm:zahori@0.1.1` | 201 | io.github.josesepulvedapino/zahori |
| 154 | `npm:glamour-mcp@0.2.0` | 200 | io.github.gratise/glamour |
| 155 | `npm:webrecipe@0.1.5` | 199 | io.github.Pillsoon/webrecipe |
| 156 | `npm:@chromium-style-qrcode/mcp@1.0.2` | 197 | io.github.chromium-style-qrcode/mcp |
| 157 | `npm:browsermesh@0.2.1` | 196 | io.github.scrollDynasty/browsermesh |
| 158 | `npm:looking-glass-mcp@3.1.1` | 196 | io.github.Sahib-Sawhney-WH/looking-glass-mcp |
| 159 | `npm:playwright-network-chaos-mcp@0.2.1` | 195 | io.github.vola-trebla/playwright-network-chaos-mcp |
| 160 | `npm:chrome-debugger-mcp@1.0.4` | 190 | io.github.BitePro/chrome-debugger-mcp |
| 161 | `npm:devcdp@5.0.1` | 185 | io.github.Dayananda-D/devcdp |
| 162 | `npm:@infoinlet/mcp-browser-research@0.1.1` | 180 | io.github.infoinlet-marketplace/mcp-browser-research |
| 163 | `npm:@dikshanty94/webnav@0.2.0` | 177 | io.github.lucyfuur94/webnav |
| 164 | `npm:plasmate-mcp@0.4.1` | 175 | io.github.plasmate-labs/plasmate |
| 165 | `npm:usable-browser-agent@0.7.1` | 174 | io.github.Savvy-Tech-Sphere/usable-browser-agent |
| 166 | `npm:newton-browser@0.4.1` | 172 | io.github.Koala-Studios/newton-browser |
| 167 | `npm:@selenix/mcp-server@1.0.7` | 170 | io.github.markmircea/Selenix-MCP-Server |
| 168 | `npm:@io.github.hj1003862396/draw-flow-mcp-server@1.0.2` | 169 | io.github.hj1003862396/draw-flow-mcp-server |
| 169 | `npm:yad-agent-mcp@0.1.1` | 169 | io.github.holistis/yad-agent-mcp |
| 170 | `npm:weboperator-mcp@1.5.1` | 168 | io.github.KazKozDev/weboperator |
| 171 | `npm:playwright-spatial-layout-mcp@0.2.0` | 167 | io.github.vola-trebla/playwright-spatial-layout-mcp |
| 172 | `npm:browser-mcp-cdp@0.1.2` | 166 | io.github.zhiqi-li/browser-mcp-cdp |
| 173 | `npm:sealedmail-mcp@0.1.1` | 165 | io.github.thesuitabs/sealedmail |
| 174 | `npm:ashfields-mcp-server@1.0.0` | 164 | io.github.smoke711711/ashfields-mcp-server |
| 175 | `npm:@edititall/mcp@0.2.1` | 162 | io.github.Subcue/edititall-mcp |
| 176 | `npm:elster-mcp-server@0.1.0` | 160 | io.github.lukasschwarz/elster-mcp-server |
| 177 | `npm:substrate-browser@2.0.2` | 159 | io.github.manuelinuxkr/substrate-browser |
| 178 | `npm:ridealong-mcp@0.1.0` | 158 | io.github.williamblaismedia-create/ridealong |
| 179 | `npm:arc-control-mcp@0.4.0` | 151 | io.github.DB-25/arc-control-mcp |
| 180 | `npm:upnext-mcp@0.3.1` | 151 | io.github.tothienbao6a0/upnext |
| 181 | `npm:infytool-mcp@1.0.0` | 146 | io.github.krupalghori44-dev/infytool |
| 182 | `npm:pdfspark-mcp@1.2.0` | 145 | io.github.dpozimski/pdfspark-mcp |
| 183 | `npm:oculo-mcp@0.4.2` | 144 | io.github.xidik12/oculo |
| 184 | `npm:@leek-emperor/personae-mcp@0.2.1` | 140 | io.github.leek-emperor/personae |
| 185 | `npm:@dominion525/familiar-mcp@0.1.2` | 112 | io.github.dominion525/familiar-mcp |
| 186 | `pypi:aihawk@0.69.2` | pypi | io.github.feder-cr/aihawk |
| 187 | `pypi:android-puppeteer-mcp@1.0.1` | pypi | io.github.pedro-rivas/android-puppeteer-mcp |
| 188 | `pypi:browsegrab@0.1.1` | pypi | io.github.ArkNill/browsegrab |
| 189 | `pypi:browser-buddy-mcp@0.1.1` | pypi | io.github.hahahahahahahahah6/browser-buddy |
| 190 | `pypi:browser-use@0.13.11` | pypi | com.browser-use/browser-use |
| 191 | `pypi:browsertap-mcp@0.4.12` | pypi | io.github.LinVireo/browsertap-mcp |
| 192 | `pypi:clickcast@0.4.4` | pypi | io.github.AlexKay28/clickcast |
| 193 | `pypi:clipacanvas-mcp@1.0.2` | pypi | io.github.mechreaper007x/clipacanvas |
| 194 | `pypi:cloakbrowsermcp@2.0.1` | pypi | io.github.overtimepog/CloakMCP |
| 195 | `pypi:conduit-browser@0.2.1` | pypi | io.github.bkauto3/conduit |
| 196 | `pypi:dash-mcp-server@1.1.1` | pypi | io.github.Kapeli/dash-mcp-server |
| 197 | `pypi:delhaize-mcp@0.1.0` | pypi | io.github.SHIMABEIGI/delhaize-mcp |
| 198 | `pypi:drissionpage-mcp@0.8.5` | pypi | io.github.jumodada/drissionpage-mcp |
| 199 | `pypi:eyebrowse@0.3.10` | pypi | io.github.Evil-Bane/eyebrowse |
| 200 | `pypi:flyto-core@2.12.6` | pypi | io.github.flytohub/flyto-core |
| 201 | `pypi:footnote-mcp@0.2.6` | pypi | io.github.KazKozDev/footnote-mcp |
| 202 | `pypi:ghostfox@0.9.2` | pypi | io.github.autokeren/ghostfox |
| 203 | `pypi:inkvault@0.3.4` | pypi | io.github.sandoreclegane/inkvault |
| 204 | `pypi:invisible-playwright-mcp@0.73.0` | pypi | io.github.feder-cr/invisible-playwright-mcp |
| 205 | `pypi:jev-ultrafast-mcp@0.1.5` | pypi | io.github.jiawei686/jev-ultrafast-mcp |
| 206 | `pypi:jevnav@0.2.2` | pypi | io.github.dtduc-git/jevnav |
| 207 | `pypi:kitchensink4web@1.0.4` | pypi | io.github.KitchenSink4AI/kitchensink4web |
| 208 | `pypi:kloakt@0.1.2` | pypi | io.github.KultMember6Banger/kloakt |
| 209 | `pypi:linkedin-api-mcp@1.0.1` | pypi | io.github.JohannsenLum/linkedin-api-mcp |
| 210 | `pypi:linkedin-sales-nav-mcp@1.2.0` | pypi | io.github.nick-choudhary/linkedin-sales-nav-mcp |
| 211 | `pypi:lionscraper@1.0.6` | pypi | io.github.dowant/lionscraper-python |
| 212 | `pypi:mcparmory-browserbase@1.0.4` | pypi | com.mcparmory/browserbase |
| 213 | `pypi:morfiade-mcp@0.2.3` | pypi | io.github.morfiade-app/morfiade-mcp |
| 214 | `pypi:nexus-browser-mcp@0.3.0` | pypi | io.github.paipaipai666/nexus-browser-mcp |
| 215 | `pypi:nodriver-mcp@2.6.1` | pypi | io.github.andresolbach/nodriver-mcp-server |
| 216 | `pypi:openbrowser-ai@0.1.54` | pypi | me.openbrowser/openbrowser-ai |
| 217 | `pypi:pyunbrowser@0.0.21` | pypi | io.github.protostatis/unbrowser |
| 218 | `pypi:retio-pagemap@0.7.3` | pypi | io.github.Retio-ai/pagemap |
| 219 | `pypi:skdev-websearch-mcp@1.10.0` | pypi | io.github.SK-DEV-AI/websearch |
| 220 | `pypi:tilion@0.1.3` | pypi | io.github.tiliondev/fortress |
| 221 | `pypi:wavexis-mcp@1.6.24` | pypi | io.github.MathiasPaulenko/wavexis-mcp |
| 222 | `pypi:web-to-markdown-mcp@0.6.0` | pypi | io.github.sidney/web-to-markdown-mcp |
| 223 | `pypi:zendriver-mcp@0.3.4` | pypi | io.github.bituq/zendriver-mcp |
| 224 | `pypi:zenlink-mcp@2.1.2` | pypi | io.github.JayQuan-McCleary/zenlink-mcp |

</details>

<details><summary>llm-proxy: 113 candidates</summary>

| # | package | downloads | registry name |
|---|---|---|---|
| 1 | `npm:@mrfentmen/openrouter-mcp@1.1.0` | 4194 | io.github.mrfentmen/openrouter-mcp |
| 2 | `npm:purmemo-mcp@12.9.5` | 3424 | io.github.purmemo-ai/purmemo |
| 3 | `npm:cool-workflow@0.1.97` | 3041 | io.github.coo1white/cool-workflow |
| 4 | `npm:@antonbabenko/deliberation-mcp@3.14.5` | 2843 | io.github.antonbabenko/deliberation |
| 5 | `npm:mcp-imagenate@0.1.5` | 2279 | io.github.mimo-3/mcp-imagenate |
| 6 | `npm:@ask-llm/gemini-mcp@2.0.0` | 2157 | io.github.Lykhoyda/ask-gemini |
| 7 | `npm:claude-token-saver-mcp@0.3.2` | 1820 | io.github.BlackFoil/claude-token-saver-mcp |
| 8 | `npm:google-ai-search-mcp@1.1.1` | 1428 | io.github.shariqriazz/google-ai-search-mcp |
| 9 | `npm:@automatelab/citation-intelligence@0.12.1` | 1423 | io.github.AutomateLab-tech/citation-intelligence |
| 10 | `npm:@houtini/lm@3.3.4` | 1370 | io.github.houtini-ai/lm |
| 11 | `npm:mediagen@0.3.0` | 1307 | io.github.Cripacx/mediagen |
| 12 | `npm:usage-planner@0.2.7` | 1236 | io.github.ItsOdeLeo/usage-planner |
| 13 | `npm:@mrfentmen/gemini-mcp@1.0.0` | 1215 | io.github.mrfentmen/gemini-mcp |
| 14 | `npm:@qmediat.io/gemini-code-context-mcp@1.20.0` | 1210 | io.github.qmediat/gemini-code-context-mcp |
| 15 | `npm:@spideriq/mcp-gate@1.3.0` | 1099 | ai.spideriq/gate |
| 16 | `npm:ai-cli-mcp@2.24.0` | 1064 | io.github.mkXultra/ai-cli-mcp |
| 17 | `npm:@mrfentmen/groq-mcp@1.0.1` | 1019 | io.github.mrfentmen/groq-mcp |
| 18 | `npm:codex-openai-image-mcp@0.1.2` | 1008 | io.github.meet30997/codex-openai-image-mcp |
| 19 | `npm:agy-bridge@0.3.1` | 985 | io.github.sshahzaiib/agy-bridge |
| 20 | `npm:@ask-llm/claude-mcp@0.2.0` | 937 | io.github.Lykhoyda/ask-claude |
| 21 | `npm:@runapi.ai/gemini-omni-mcp@0.3.1` | 915 | io.github.runapi-builder/gemini-omni-mcp |
| 22 | `npm:codex4ever@0.1.3` | 812 | io.github.ItsOdeLeo/codex4ever |
| 23 | `npm:@runapi.ai/gemini-tts-mcp@0.2.1` | 795 | io.github.runapi-builder/gemini-tts-mcp |
| 24 | `npm:gemini-researcher@1.0.2` | 763 | io.github.capyBearista/gemini-researcher |
| 25 | `npm:@clusteragent/cluster-mcp@1.0.12` | 709 | dev.clusteragent/cluster-mcp |
| 26 | `npm:codex-subagent-mcp@0.6.0` | 629 | io.github.parisbs/codex-subagent-mcp |
| 27 | `npm:@ask-llm/ollama-mcp@0.7.0` | 615 | io.github.Lykhoyda/ask-ollama |
| 28 | `npm:@quantulabs/hivemind@0.1.3` | 596 | io.github.QuantuLabs/hivemind |
| 29 | `npm:@google-cloud/gemini-cloud-assist-mcp@0.1.1` | 590 | io.github.GoogleCloudPlatform/gemini-cloud-assist-mcp |
| 30 | `npm:llm-cli-gateway@1.17.1` | 480 | io.github.verivus-oss/llm-cli-gateway |
| 31 | `npm:@iamjrmh/mcpbridge@1.0.0` | 479 | io.github.iamjrmh/mcpbridge |
| 32 | `npm:@ask-llm/codex-mcp@0.9.0` | 476 | io.github.Lykhoyda/ask-codex |
| 33 | `npm:@j0hanz/code-lens-mcp@0.12.0` | 467 | io.github.j0hanz/code-lens |
| 34 | `npm:@bridgenode/mcp@1.1.1` | 437 | io.github.bridgenode-ai/bridgenode-mcp |
| 35 | `npm:@inite/visibility@1.3.0` | 427 | ai.inite/inite-visibility |
| 36 | `npm:viberank-mcp@1.2.0` | 427 | io.github.sculptdotfun/viberank |
| 37 | `npm:proxyllm-mcp@1.0.2` | 424 | ai.proxyllm/proxyllm-mcp |
| 38 | `npm:mcp-nano-banana@1.2.2` | 412 | io.github.codeFi/mcp-nano-banana |
| 39 | `npm:tokencost-dev@0.1.3` | 411 | io.github.jeff-atriumn/tokencost-dev |
| 40 | `npm:@trishchuk/codex-mcp-tool@2.2.0` | 408 | io.github.x51xxx/codex-mcp-tool |
| 41 | `npm:@strato-space/media-gen-mcp@1.0.4` | 401 | io.github.strato-space/media-gen-mcp |
| 42 | `npm:cited-mcp@0.1.0` | 394 | io.github.impowerdlifestyle-code/cited-mcp |
| 43 | `npm:mcp-server-google-antigravity@1.0.2` | 394 | io.github.TurkerYakup/mcp-server-google-antigravity |
| 44 | `npm:crazyseo@0.1.2` | 387 | io.github.bolidee/crazyseo |
| 45 | `npm:crazyseo@0.1.3` | 387 | io.github.d08m/crazyseo |
| 46 | `npm:pathmark@0.1.17` | 385 | io.github.hacksurvivor/pathmark |
| 47 | `npm:short-video-agent-kit@0.1.7` | 361 | io.github.davidmosiah/short-video-agent-kit |
| 48 | `npm:@pymodel/claude-agy-mcp@1.0.3` | 360 | io.github.PyModel/claude-agy-mcp |
| 49 | `npm:@three-ws/brain-mcp@0.1.4` | 359 | io.github.nirholas/brain-mcp |
| 50 | `npm:@weiseer/api-changelog-mcp@0.1.1` | 358 | io.github.weiseer/api-changelog |
| 51 | `npm:whisper-mcp@0.1.1` | 349 | io.github.jwulff/whisper-mcp |
| 52 | `npm:@nuver-labs/image-gen-mcp@0.2.1` | 345 | com.nuverlabs/image-gen |
| 53 | `npm:@hol-org/hashnet-mcp@1.0.24` | 315 | io.github.hashgraph-online/hashnet |
| 54 | `npm:ipforai-mcp@0.1.0` | 310 | cc.ipforai/ipforai |
| 55 | `npm:awesome-agent-skills-mcp@1.0.2` | 295 | io.github.shadowrootdev/awesome-agent-skills |
| 56 | `npm:imgx-mcp@1.6.1` | 288 | io.github.somacoffeekyoto/imgx |
| 57 | `npm:@j0hanz/code-assistant@2.0.0` | 286 | io.github.j0hanz/code-assistant |
| 58 | `npm:pixel-surgeon-mcp@1.1.1` | 268 | io.github.j-east/pixel-surgeon |
| 59 | `npm:@truealter/mcp-ollama@0.2.1` | 254 | io.github.true-alter/mcp-ollama |
| 60 | `npm:@skillfm/llm-cost-optimizer-mcp@0.1.0` | 251 | io.github.ericm1018/skillfm-llm-cost-optimizer-openai-anthropic-usage |
| 61 | `npm:@weiseer/status-aggregator-mcp@0.1.2` | 238 | io.github.weiseer/status-aggregator |
| 62 | `npm:@samoradc/tetrad@0.1.12` | 236 | io.github.SamoraDC/tetrad |
| 63 | `npm:tickerr-mcp@1.0.1` | 225 | io.github.imviky-ctrl/tickerr |
| 64 | `npm:llm-cost-estimator-mcp@0.3.1` | 210 | io.github.waqarulwahab/llm-cost-estimator |
| 65 | `npm:@infoinlet/mcp-translate@0.1.1` | 208 | io.github.infoinlet-marketplace/mcp-translate |
| 66 | `npm:ai-visibility-mcp@1.0.0` | 199 | io.github.sharozdawa/ai-visibility |
| 67 | `npm:@modelpricewatch/mcp@1.0.0` | 193 | com.modelpricewatch/mcp |
| 68 | `npm:@comparedge/llm-cost-mcp@1.0.0` | 191 | io.github.imkemit-ops/comparedge-llm-cost |
| 69 | `npm:ai-price-index-mcp@0.1.2` | 183 | io.github.RoninForge/ai-price-index-mcp |
| 70 | `npm:@tokeneyez/mcp@0.3.2` | 161 | io.github.Reemedri/tokeneyez |
| 71 | `npm:ai-cost-analyzer@1.1.4` | 156 | io.github.vpatser1/ai-cost-analyzer |
| 72 | `npm:claude-code-usage-mcp@0.1.0` | 154 | io.github.wheelbarrel00/claude-code-usage |
| 73 | `npm:@j0hanz/code-review-analyst-mcp@1.7.6` | -1 | io.github.j0hanz/code-review-analyst |
| 74 | `pypi:agentic-research-engine@0.1.3` | pypi | io.github.TheAiSingularity/agentic-research |
| 75 | `pypi:algernon-mcp@0.1.1` | pypi | io.github.sammyboi81/algernon |
| 76 | `pypi:apipriceindex-mcp@0.3.0` | pypi | io.github.apipriceindex/mcp |
| 77 | `pypi:ask-fable@0.13.0` | pypi | io.github.baggybin/ask-fable |
| 78 | `pypi:cli-bridge-mcp@0.3.0` | pypi | io.github.JoaoBerne/cli-bridge-mcp |
| 79 | `pypi:contextkeeper@0.2.7` | pypi | io.github.TheRealDataBoss/contextkeeper |
| 80 | `pypi:ddg-agent-services-mcp@0.10.1` | pypi | com.daedalusdevelopmentgroup/ddg-agent-services-mcp |
| 81 | `pypi:ddg-agent-services-mcp@0.5.0` | pypi | io.github.daedalusdevelopmentgroup/ddg-agent-services-mcp |
| 82 | `pypi:deputy-cc@0.3.1` | pypi | io.github.alimohammadiamirhossein/deputy |
| 83 | `pypi:dsh-cua@0.4.1` | pypi | io.github.Hutusion/dsh-cua |
| 84 | `pypi:evalforge-lite@1.0.1` | pypi | io.github.thejaredchapman/evalforge-lite |
| 85 | `pypi:evalview@0.6.0` | pypi | io.github.hidai25/evalview-mcp |
| 86 | `pypi:fish-bridge-mcp@0.1.3` | pypi | io.github.MakeaMouse/fish-bridge-mcp |
| 87 | `pypi:freellmpool@0.13.0` | pypi | io.github.0xzr/freellmpool |
| 88 | `pypi:fusion-mcp@0.1.0` | pypi | io.github.Jolymmiles/fusion-mcp |
| 89 | `pypi:gopher-mcp@0.10.2` | pypi | io.github.cameronrye/gopher-mcp |
| 90 | `pypi:image-generation-mcp@1.12.1` | pypi | io.github.pvliesdonk/image-generation-mcp |
| 91 | `pypi:imagine-mcp@1.11.6` | pypi | io.github.n24q02m/imagine-mcp |
| 92 | `pypi:litellm-mcp@1.0.2` | pypi | io.github.BerriAI/litellm-mcp |
| 93 | `pypi:litellm-mcp@1.0.1` | pypi | io.github.shin-bot-litellm/litellm-mcp |
| 94 | `pypi:llm-usage-mcp@0.1.3` | pypi | io.github.zhaoyue722/llm-usage-mcp |
| 95 | `pypi:llmledger-mcp@0.2.0` | pypi | io.github.pouriaetab/llmledger |
| 96 | `pypi:massive-context-mcp@3.0.1` | pypi | io.github.egoughnour/massive-context-mcp |
| 97 | `pypi:mcp-gemini-crunchtools@0.3.0` | pypi | io.github.crunchtools/gemini |
| 98 | `pypi:mcp-llm-gateway@0.1.0` | pypi | io.github.daedalus/mcp-llm-gateway |
| 99 | `pypi:mcp-ollama-vllm@1.0.6` | pypi | io.github.setheerwagen/mcp-ollama-vllm |
| 100 | `pypi:meta-prompt-mcp@1.0.11` | pypi | io.github.kapillamba4/meta-prompt-mcp |
| 101 | `pypi:model-council-mcp-server@0.1.2` | pypi | io.github.ivanantigravity-lgtm/model-council-mcp-server |
| 102 | `pypi:model-price-radar-mcp@0.1.0` | pypi | io.github.alialtunar/model-price-radar-mcp |
| 103 | `pypi:modelmux@0.4.3` | pypi | io.github.pure-maple/modelmux |
| 104 | `pypi:myai-mcp@0.2.0` | pypi | io.github.myaitoken/myai-mcp |
| 105 | `pypi:nudg3-mcp@1.1.0` | pypi | ai.nudg3/brand-intelligence |
| 106 | `pypi:observe-instrument-mcp@0.1.2` | pypi | io.github.alanzha2/observe-instrument-mcp |
| 107 | `pypi:ollama-handoff@0.1.2` | pypi | io.github.Michael-WhiteCapData/ollama-handoff |
| 108 | `pypi:omni-computer-use-mcp@1.0.2` | pypi | io.github.Jason26214/omni-computer-use |
| 109 | `pypi:perplexity-polza-mcp-server@0.1.1` | pypi | io.github.ivanantigravity-lgtm/perplexity-polza-mcp-server |
| 110 | `pypi:threadkeeper@0.13.1` | pypi | io.github.po4erk91/thread-keeper |
| 111 | `pypi:vaultit@0.6.1` | pypi | io.github.TheRealDataBoss/vaultit |
| 112 | `pypi:waypoint-mcp@0.5.2` | pypi | io.github.STiFLeR7/waypoint-mcp |
| 113 | `pypi:whisper-transcribe-mcp@1.1.3` | pypi | io.github.ZahiriNatZuke/whisper-transcribe-mcp |

</details>

<details><summary>vcs-hosting: 107 candidates</summary>

| # | package | downloads | registry name |
|---|---|---|---|
| 1 | `npm:@gitkraken/gk@3.1.77` | 289690 | com.gitkraken/gk-cli |
| 2 | `npm:bitbucket-mcp@5.0.5` | 24432 | io.github.MatanYemini/bitbucket-mcp |
| 3 | `npm:octocode-mcp@7.0.9` | 15477 | io.github.bgauryy/octocode-mcp |
| 4 | `npm:@reneturcios/actionpin@0.1.8` | 2328 | io.github.CloudCorpRecords/actionpin |
| 5 | `npm:appveyor-mcp@1.0.1` | 1113 | io.github.mrfentmen/appveyor-mcp |
| 6 | `npm:@mrfentmen/github-mcp@1.1.0` | 1105 | io.github.mrfentmen/github-mcp |
| 7 | `npm:landmines@0.2.2` | 1092 | tech.landmine/landmine |
| 8 | `npm:codeberg-mcp@1.0.1` | 924 | io.github.mrfentmen/codeberg-mcp |
| 9 | `npm:@mrfentmen/gitlab-mcp@1.0.0` | 919 | io.github.mrfentmen/gitlab-mcp |
| 10 | `npm:@reneturcios/flowcheck@0.1.2` | 896 | io.github.CloudCorpRecords/flowcheck |
| 11 | `npm:docfork@1.3.0` | 877 | com.docfork/docfork-mcp |
| 12 | `npm:@mrfentmen/bitbucket-mcp@1.0.0` | 875 | io.github.mrfentmen/bitbucket-mcp |
| 13 | `npm:projectpulse-mcp@1.10.0` | 794 | io.github.alexbypa/github-projectpulse-mcp |
| 14 | `npm:@driflyte/mcp-server@0.1.15` | 778 | com.driflyte/driflyte-mcp-server |
| 15 | `npm:github-webhook-mcp@0.8.2` | 778 | io.github.Liplus-Project/github-webhook-mcp |
| 16 | `npm:ci-guard-mcp@0.1.0` | 715 | io.github.carelessdept/ci-guard-mcp |
| 17 | `npm:@mrfentmen/youtrack-mcp@1.0.1` | 653 | io.github.mrfentmen/youtrack-mcp |
| 18 | `npm:whichlib@0.2.4` | 638 | io.github.josifb/whichlib |
| 19 | `npm:pkg-health-mcp@0.2.0` | 564 | io.github.orcsnren/pkg-health-mcp |
| 20 | `npm:connections-mcp@2.253.0` | 531 | io.github.Lunarwerx/connections |
| 21 | `npm:contri-mcp@0.2.0` | 516 | io.github.alphasafal/contri |
| 22 | `npm:gitcontribute@3.0.2` | 468 | io.github.morluto/gitcontribute |
| 23 | `npm:@paretools/github@0.7.1` | 466 | io.github.Dave-London/github |
| 24 | `npm:@paretools/github@0.8.1` | 466 | io.github.Dave-London/pare-github |
| 25 | `npm:@mrfentmen/gitea-mcp@1.0.0` | 465 | io.github.mrfentmen/gitea-mcp |
| 26 | `npm:github-intel-mcp@1.0.0` | 459 | io.github.mrfentmen/github-intel-mcp |
| 27 | `npm:@automatelab/content-distribution-mcp@2.2.1` | 453 | io.github.AutomateLab-tech/content-distribution |
| 28 | `npm:@the_warl0ck/harvest-mcp@0.1.0` | 451 | io.github.The-Warl0ck/harvest-mcp |
| 29 | `npm:bitbucket-datacenter-mcp@0.6.0` | 418 | io.github.MrRefactoring/atlassian-dc-mcp-bitbucket |
| 30 | `npm:@gitdealflow/mcp-signal@2.2.2` | 402 | io.github.kindrat86/vc-deal-flow-signal |
| 31 | `npm:@hookwarden/mcp@0.9.5` | 398 | io.github.Hookwarden/mcp |
| 32 | `npm:sexai-mcp@0.11.11` | 357 | dev.sexai/sexai-mcp |
| 33 | `npm:reuse-before-generate@0.2.3` | 352 | io.github.aradar46/reuse-before-generate |
| 34 | `npm:@readystack/actions-deprecation-lint-2026@0.1.6` | 346 | io.github.jmshinhwa/actions-deprecation-lint-2026 |
| 35 | `npm:@tigerdata/tiger-skills-mcp-server@0.1.4` | 314 | io.github.timescale/tiger-skills |
| 36 | `npm:@cocaxcode/devflow-mcp@0.1.8` | 313 | io.github.cocaxcode/devflow-mcp |
| 37 | `npm:@readystack/gitlab-ci-break-lint@1.0.1` | 307 | io.github.jmshinhwa/gitlab-ci-break-lint |
| 38 | `npm:qualien-mcp@0.6.2` | 304 | io.github.qualienai/qualien-mcp |
| 39 | `npm:cursor-telegram-chat@0.1.23` | 290 | io.github.udah1/cursor-chat-bridge |
| 40 | `npm:@readystack/action-runtime-sunset-lint@1.0.2` | 287 | io.github.jmshinhwa/action-runtime-sunset-lint |
| 41 | `npm:nockchain-mcp@0.1.0` | 272 | io.github.mizuki0x/nockchain-mcp |
| 42 | `npm:go-tokenless@1.1.0` | 261 | io.github.Continuous-Actions/go-tokenless |
| 43 | `npm:moltalyzer-mcp@1.7.0` | 255 | io.github.jcislo/moltalyzer-mcp |
| 44 | `npm:@sandovalrr/project-context-mcp@0.4.0` | 251 | io.github.sandovalrr/project-context |
| 45 | `npm:octocounts-mcp@0.2.0` | 243 | io.github.huanglizhuo/octocounts-mcp |
| 46 | `npm:github-status-mcp@1.0.0` | 238 | io.github.mrfentmen/github-status-mcp |
| 47 | `npm:@abhishekmcp/github@0.2.0` | 237 | io.github.Abhishekkumar2021/github |
| 48 | `npm:commitshow-mcp@0.2.2` | 234 | io.github.commitshow/audit |
| 49 | `npm:@regulatorysignals/mcp@0.1.2` | 232 | io.github.rikocr8orh8/regulatory-signals |
| 50 | `npm:@benchboss/mcp-client@0.3.1` | 226 | io.github.p4stoboy/benchboss |
| 51 | `npm:nexus3d-mcp@0.4.2` | 218 | io.github.richy7734/nexus3d-mcp |
| 52 | `npm:mcp-netassist@0.1.1` | 212 | io.github.Edge-Echo/mcp-netassist |
| 53 | `npm:@bitofacoder/omni-mcp-server@1.1.1` | 210 | io.github.bitofacoder/omni-mcp-server |
| 54 | `npm:beacon-mcp@0.1.1` | 210 | io.github.enrichgateagent-png/beacon-mcp |
| 55 | `npm:theabbie@2.0.0` | 203 | io.github.theabbie/theabbie |
| 56 | `npm:sharedoc-mcp@2.1.4` | 198 | io.github.AugustusW/sharedoc-mcp |
| 57 | `npm:mcp-server-github-actions@1.0.1` | 195 | io.github.ofershap/github-actions |
| 58 | `npm:github-project-info-mcp@0.1.3` | 189 | io.github.shubhtoy/github-project-info |
| 59 | `npm:taskbounty-check@0.1.6` | 189 | io.github.eliottreich/taskbounty-check |
| 60 | `npm:@weiseer/bounty-mcp@0.1.1` | 188 | io.github.weiseer/bounty-mcp |
| 61 | `npm:mcp-server-github-gist@1.0.2` | 188 | io.github.ofershap/github-gist |
| 62 | `npm:webhook-toolkit@0.1.1` | 187 | io.github.THE-KIPDEV/webhook-toolkit |
| 63 | `npm:atest-mcp-server-launcher@1.0.2` | 186 | io.github.LinuxSuRen/atest-mcp-server |
| 64 | `npm:mcp-server-research-signals@1.2.0` | 186 | io.github.joepangallo/mcp-server-research-signals |
| 65 | `npm:mizuki-mcp@0.1.2` | 186 | org.opencovenant/mizuki |
| 66 | `npm:@rakeshroushan/reposcout@0.1.1` | 178 | io.github.Rakesh1002/reposcout |
| 67 | `npm:@io.github.hj1003862396/draw-flow-mcp-server@1.0.2` | 169 | io.github.hj1003862396/draw-flow-mcp-server |
| 68 | `npm:@perceptdot/github@0.1.5` | 166 | io.github.perceptdot/github |
| 69 | `npm:mcp-oss-onramp@0.1.3` | 165 | io.github.ryotaro-tanaka/mcp-oss-onramp |
| 70 | `npm:@infoinlet/mcp-github@0.1.1` | 163 | io.github.infoinlet-marketplace/mcp-github |
| 71 | `npm:@remogram/mcp@0.2.0-beta.4` | 163 | io.github.attebury/remogram |
| 72 | `npm:zread-mcp@1.0.1` | 159 | io.github.ejfkdev/zread-mcp |
| 73 | `npm:standup-mcp@0.1.0` | 156 | io.github.sathvic-kollu/standup-mcp |
| 74 | `npm:retro-mcp@0.1.0` | 151 | io.github.sathvic-kollu/retro-mcp |
| 75 | `npm:x402-repohealth-mcp@0.1.0` | 149 | io.github.liminalpepe/x402-repohealth-mcp |
| 76 | `npm:@rog0x/mcp-github-tools@1.0.1` | 139 | io.github.rog0x/github |
| 77 | `npm:sovereign-github-stats-mcp@1.0.0` | 136 | io.github.ryudi84/github-stats |
| 78 | `pypi:agent-harnesses-mcp@0.8.0` | pypi | io.github.RyanAlberts/agent-harnesses |
| 79 | `pypi:apifacts@0.2.1` | pypi | io.github.Illouminus/apifacts |
| 80 | `pypi:awesome-core@2.0.1` | pypi | io.github.twojlogin/awesome-core |
| 81 | `pypi:bitbucket-mcp-py@1.29.2` | pypi | io.github.lawp09/bitbucket-mcp |
| 82 | `pypi:codeofpaper@0.3.2` | pypi | io.github.isagelswann/codeofpaper |
| 83 | `pypi:codereviewbuddy@0.37.0` | pypi | io.github.detailobsessed/codereviewbuddy |
| 84 | `pypi:delphi-code@0.3.4` | pypi | io.github.markdorof/delphi-code |
| 85 | `pypi:fake-star-audit@0.1.1` | pypi | io.github.Armada735/fake-star-audit |
| 86 | `pypi:feedback-synthesis-mcp@0.1.1` | pypi | io.github.sapph1re/feedback-synthesis-mcp |
| 87 | `pypi:fossick-mcp@0.1.4` | pypi | io.github.Lipdog/fossick |
| 88 | `pypi:gh-release-mcp@0.1.1` | pypi | io.github.zishuowang696/gh-release-mcp |
| 89 | `pypi:github-inside-claude-code@0.9.6` | pypi | io.github.Kirchlive/github-inside-claude-code |
| 90 | `pypi:github-mcp-server@2.5.7` | pypi | io.github.crypto-ninja/github-mcp-server |
| 91 | `pypi:github-twin@0.0.17` | pypi | io.github.ChristopherDavenport/github-twin |
| 92 | `pypi:hn-tech-signal-mcp@0.5.0` | pypi | io.github.malkreide/hn-tech-signal-mcp |
| 93 | `pypi:hotin@0.9.21` | pypi | io.github.abe238/hotin |
| 94 | `pypi:idea-reality-mcp@0.3.4` | pypi | io.github.mnemox-ai/idea-reality-mcp |
| 95 | `pypi:innoday@0.112.2-beta` | pypi | io.github.havilandsoftware/mcp-server-innoday |
| 96 | `pypi:jaimenbell-github-mcp@0.1.1` | pypi | io.github.jaimenbell/github-mcp |
| 97 | `pypi:lastseen-mcp@0.1.2` | pypi | dev.lastseen/mortality |
| 98 | `pypi:mcp-gitlab-crunchtools@0.4.1` | pypi | io.github.crunchtools/gitlab |
| 99 | `pypi:mcp-samsclub-ads@0.1.1` | pypi | io.github.alyiox/mcp-samsclub-ads |
| 100 | `pypi:mcp-walmart-marketplace@0.1.1` | pypi | io.github.alyiox/mcp-walmart-marketplace |
| 101 | `pypi:mcparmory-bitbucket@1.0.5` | pypi | com.mcparmory/bitbucket |
| 102 | `pypi:mcparmory-github@1.0.6` | pypi | com.mcparmory/github |
| 103 | `pypi:mcparmory-gitlab@1.0.3` | pypi | com.mcparmory/gitlab |
| 104 | `pypi:myopic@0.1.11` | pypi | io.github.SurajKGoyal/myopic |
| 105 | `pypi:n0s1-mcp@1.1.6` | pypi | io.github.spark1security/n0s1-mcp |
| 106 | `pypi:release-notes-mcp@1.0.1` | pypi | io.github.vaggeliskls/release-notes-mcp |
| 107 | `pypi:taken-gh@0.9.2` | pypi | io.github.RogueAlg0/taken |

</details>

<details><summary>database: 268 candidates</summary>

| # | package | downloads | registry name |
|---|---|---|---|
| 1 | `npm:run402-mcp@4.104.2` | 25423 | com.run402/mcp |
| 2 | `npm:@connorbritain/mssql-mcp-reader@0.3.1` | 11480 | io.github.ConnorBritain/mssql-reader |
| 3 | `npm:hana-cli@4.202607.1` | 6565 | io.github.SAP-samples/hana-cli |
| 4 | `npm:mcp-postgres-server@0.3.1` | 4867 | io.github.antonorlov/mcp-postgres-server |
| 5 | `npm:@profullstack/nichedb@0.1.0` | 4396 | dev.nichedb/nichedb |
| 6 | `npm:codex-supervisor-mcp@0.8.0` | 3043 | io.github.zriyox/codex-supervisor-mcp |
| 7 | `npm:migrationpilot@1.6.4` | 3027 | io.github.mickelsamuel/migrationpilot |
| 8 | `npm:titen-memory@0.7.2` | 2917 | io.github.RamaAditya49/titen-memory |
| 9 | `npm:@guardbee/mcp-db-gateway@0.3.5` | 2612 | io.github.4hmetuyar/db-gateway |
| 10 | `npm:chron-mcp@0.1.7` | 2025 | io.github.SirinivasK/chron |
| 11 | `npm:@remem-ai/remem@0.6.104` | 2008 | io.github.majiayu000/remem |
| 12 | `npm:biomcp@1.4.3` | 1981 | io.github.yeyuan98/biomcp-ts |
| 13 | `npm:sqlite-local-ai-memory@1.5.3` | 1926 | io.github.cheveguerra/sqlite-local-ai-memory |
| 14 | `npm:@guardbee/mcp-vector-store-scanner@0.1.1` | 1866 | io.github.4hmetuyar/vector-store-scanner |
| 15 | `npm:rowsmith-mcp@0.5.0` | 1809 | io.github.meiorz/rowsmith |
| 16 | `npm:@connorbritain/mssql-mcp-server@0.4.5` | 1577 | io.github.ConnorBritain/mssql |
| 17 | `npm:showboard@0.4.1` | 1411 | io.github.rohanbeingsocial/showboard |
| 18 | `npm:infrawise@1.0.0` | 1409 | io.github.Sidd27/infrawise |
| 19 | `npm:@cyanheads/ensembl-mcp-server@0.7.1` | 1382 | io.github.cyanheads/ensembl-mcp-server |
| 20 | `npm:@jarroba/mcp@0.3.0` | 1366 | io.github.Invarato/jarroba-tools |
| 21 | `npm:@homespunapps/mcp@1.6.98` | 1350 | dev.homespun/homespun |
| 22 | `npm:drizzle-mcp@0.1.1` | 1298 | io.github.Fredobumma/drizzle-mcp |
| 23 | `npm:baserow-mcp@1.0.0` | 1286 | io.github.mrfentmen/baserow-mcp |
| 24 | `npm:@lucasmella/mismem@0.2.0` | 1112 | io.github.lucasmella-stack/mismem |
| 25 | `npm:nvd-cve-mcp@1.0.0` | 967 | io.github.mrfentmen/nvd-cve-mcp |
| 26 | `npm:ainative-postgres-mcp@1.0.1` | 936 | io.github.AINative-Studio/ainative-postgres-mcp |
| 27 | `npm:demozoo-mcp@1.0.5` | 924 | io.github.mrfentmen/demozoo-mcp |
| 28 | `npm:chembl-mcp@1.0.1` | 909 | io.github.mrfentmen/chembl-mcp |
| 29 | `npm:@mrfentmen/ourairports-mcp@1.0.2` | 846 | io.github.mrfentmen/ourairports-mcp |
| 30 | `npm:@xultrax-web/agent-memory-mcp@0.15.0` | 839 | io.github.xultrax-web/agent-memory-mcp |
| 31 | `npm:brokre@0.2.36` | 786 | io.github.Furowu/brokre |
| 32 | `npm:perfume-picks-mcp@1.0.5` | 772 | io.github.bguillow-rgb/perfume-picks |
| 33 | `npm:@mrfentmen/sql-format-mcp@1.0.1` | 740 | io.github.mrfentmen/sql-format-mcp |
| 34 | `npm:@hovecapital/read-only-mysql-mcp-server@0.1.1` | 739 | capital.hove/read-only-local-mysql-mcp-server |
| 35 | `npm:dbatools-mcp-server@0.5.0` | 737 | io.github.dataplat/dbatools-mcp-server |
| 36 | `npm:flipside-mcp@1.0.0` | 707 | io.github.mrfentmen/flipside-mcp |
| 37 | `npm:jeero-mcp@2.0.0` | 700 | io.github.slimndap/jeero-mcp |
| 38 | `npm:@aistastudio/myc@0.3.13` | 697 | io.github.aistastudio/myc |
| 39 | `npm:@mrfentmen/fauna-mcp@1.0.1` | 697 | io.github.mrfentmen/fauna-mcp |
| 40 | `npm:rpgmaker-mz-mcp@1.4.0` | 692 | io.github.Redseb/rpgmaker-mz-mcp |
| 41 | `npm:@cyanheads/ilostat-mcp-server@0.3.0` | 663 | io.github.cyanheads/ilostat-mcp-server |
| 42 | `npm:rawg-mcp@1.0.0` | 638 | io.github.mrfentmen/rawg-mcp |
| 43 | `npm:hmem-mcp@1.6.7` | 612 | io.github.Bumblebiber/hmem-mcp |
| 44 | `npm:statecore-mcp@0.1.2` | 605 | io.github.yul761/statecore-mcp |
| 45 | `npm:@dockndevai/mcp-percona-pg@0.3.3` | 594 | io.github.dockndevai/mcp-percona-pg |
| 46 | `npm:mcp-sqlite-server@1.0.1` | 593 | io.github.ofershap/sqlite |
| 47 | `npm:monacloud-mcp@0.11.1` | 591 | vn.monacloud/monacloud-mcp |
| 48 | `npm:@sqlike/mcp@0.2.3` | 568 | io.github.orifisher2/sqlike-mcp |
| 49 | `npm:mcp-sqlite-tools@0.0.11` | 565 | io.github.spences10/mcp-sqlite-tools |
| 50 | `npm:sqemo-mcp@2.8.3` | 562 | io.github.sqemo/sqemo |
| 51 | `npm:@dmytro-prototypes/cadbridge-mcp@0.1.15` | 561 | net.dmytro-prototypes/cadbridge-mcp-autocad |
| 52 | `npm:quorum-mcp-server@4.0.0` | 553 | ai.quorumdb/quorum |
| 53 | `npm:@questdb/mcp-server-questdb@0.5.0` | 534 | io.github.questdb/mcp-server-questdb |
| 54 | `npm:ftp-ssh-mcp@1.0.3` | 526 | io.github.Chris221/ftp-ssh-mcp |
| 55 | `npm:nexql-mcp@0.2.4` | 518 | io.github.NexQL-OSS/nexql-mcp |
| 56 | `npm:ifdb-mcp-server@1.0.0` | 515 | io.github.mrfentmen/ifdb |
| 57 | `npm:delx-memory@0.2.3` | 511 | io.github.davidmosiah/delx-memory |
| 58 | `npm:@dataoil/mcp@0.1.5` | 509 | tech.dataoil/mcp |
| 59 | `npm:remem-mcp@0.5.17` | 508 | io.github.tinhien11/remem-mcp |
| 60 | `npm:dev-error-explainers@0.2.1` | 502 | io.github.mahdibrr/dev-error-explainers |
| 61 | `npm:db-mcp@1.0.2` | 500 | io.github.neverinfamous/db-mcp |
| 62 | `npm:@hovecapital/read-only-postgres-mcp-server@0.1.0` | 487 | capital.hove/read-only-local-postgres-mcp-server |
| 63 | `npm:@dinglebear/cortex@3.13.2` | 486 | ai.dinglebear/cortex |
| 64 | `npm:mac-lookup-mcp@1.0.0` | 460 | io.github.mrfentmen/mac-lookup-mcp |
| 65 | `npm:@opitacode/dark-memory-mcp@4.0.0-alpha.32` | 458 | io.github.Opita-Code/dark-memory-mcp |
| 66 | `npm:@o1-labs/mina-mcp-server@0.7.3` | 445 | io.github.MinaProtocol/mina-mcp-server |
| 67 | `npm:@mrfentmen/leetcode-mcp@1.0.0` | 440 | io.github.mrfentmen/leetcode-mcp |
| 68 | `npm:tdai-memory-mcp@0.3.0` | 440 | io.github.tinhien11/tdai-memory-mcp |
| 69 | `npm:@edelciomolina/postgres-mcp@1.7.0` | 437 | io.github.edelciomolina/postgres-mcp |
| 70 | `npm:jpl-sbdb-mcp@1.0.0` | 431 | io.github.mrfentmen/jpl-sbdb-mcp |
| 71 | `npm:saga-mcp@1.19.0` | 424 | io.github.spranab/saga-mcp |
| 72 | `npm:@mrfentmen/drug-shortages-mcp@1.0.0` | 422 | io.github.mrfentmen/drug-shortages-mcp |
| 73 | `npm:@upstash/redis-mcp@0.1.1` | 421 | io.github.upstash/redis-mcp |
| 74 | `npm:@readystack/license-flip-audit@0.1.3` | 420 | io.github.jmshinhwa/license-flip-audit |
| 75 | `npm:dbmole-mcp@0.2.0` | 420 | io.github.ed-smartass/dbmole-mcp |
| 76 | `npm:pbdb-mcp@1.0.0` | 415 | io.github.mrfentmen/pbdb-mcp |
| 77 | `npm:@rowsend/mcp@1.0.0` | 414 | com.rowsend/rowsend |
| 78 | `npm:crumbtrail-node@0.3.0` | 413 | io.github.CrumbtrailDev/crumbtrail |
| 79 | `npm:@cocaxcode/database-mcp@0.1.14` | 406 | io.github.cocaxcode/database-mcp |
| 80 | `npm:@neverinfamous/postgres-mcp@1.0.2` | 403 | io.github.neverinfamous/postgres-mcp |
| 81 | `npm:hasura-mcp@1.0.2` | 399 | io.github.mrfentmen/hasura-mcp |
| 82 | `npm:rls-doctor@0.5.8` | 386 | io.github.subhajitlucky/rls-doctor |
| 83 | `npm:@reneturcios/litebase@0.1.0` | 379 | io.github.CloudCorpRecords/litebase |
| 84 | `npm:migration-map-mcp@1.0.2` | 377 | io.github.mrfentmen/migration-map-mcp |
| 85 | `npm:@avi-total-recall/total-recall@0.2.3` | 375 | io.github.Avi-Bendetsky/total-recall |
| 86 | `npm:@avi-total-recall/total-recall@0.2.4` | 375 | io.github.BAS-More/total-recall |
| 87 | `npm:@mrfentmen/sqlite-mcp@1.0.0` | 374 | io.github.mrfentmen/sqlite-mcp |
| 88 | `npm:@mycobrain/mcp-server@1.3.0` | 370 | io.github.thegoodguysla/myco-brain |
| 89 | `npm:sql-preview@0.6.28` | 367 | io.github.fadnavismehul/sql-preview |
| 90 | `npm:@reneturcios/pgport@0.1.0` | 366 | io.github.CloudCorpRecords/pgport |
| 91 | `npm:@dockndevai/mcp-clickhouse@0.3.0` | 351 | io.github.dockndevai/mcp-clickhouse |
| 92 | `npm:@readystack/sql-card-data-lint@1.0.3` | 340 | io.github.jmshinhwa/sql-card-data-lint |
| 93 | `npm:@verygoodplugins/mcp-local-wp@2.0.0` | 340 | io.github.verygoodplugins/mcp-local-wp |
| 94 | `npm:@connorbritain/mssql-mcp-writer@0.3.1` | 339 | io.github.ConnorBritain/mssql-writer |
| 95 | `npm:@cevelas/mcp-sqlserver@3.3.0` | 330 | io.github.cvelasquez/mcp-sqlserver |
| 96 | `npm:@faucetdb/faucet@0.1.15` | 323 | io.github.faucetdb/faucet |
| 97 | `npm:@infino-ai/code-context@0.5.1` | 315 | io.github.infino-ai/code-context |
| 98 | `npm:@dmytro-prototypes/control-mcp-server@0.1.16` | 310 | net.dmytro-prototypes/control-mcp-server |
| 99 | `npm:@sota-io/mcp@1.5.0` | 306 | io.sota/mcp |
| 100 | `npm:qualien-mcp@0.6.2` | 304 | io.github.qualienai/qualien-mcp |
| 101 | `npm:datarunner@0.3.1` | 299 | app.datarunner/datarunner |
| 102 | `npm:@marcelo-ochoa/server-postgres@1.0.8` | 297 | io.github.marcelo-ochoa/postgres |
| 103 | `npm:@readystack/pg-migration-lock-lint@1.0.2` | 293 | io.github.jmshinhwa/pg-migration-lock-lint |
| 104 | `npm:mcp-database-doctor@0.1.2` | 289 | io.github.petrovicistefan/mcp-database-doctor |
| 105 | `npm:@rheopyrin/db-access-mcp@0.1.5` | 287 | io.github.Rheopyrin/db-access-mcp |
| 106 | `npm:@geek-fun/data-studio-mcp@0.1.10` | 282 | io.github.geek-fun/data-studio |
| 107 | `npm:settlemesh@0.1.92` | 282 | io.settlemesh/cli |
| 108 | `npm:@tharanabopearachchi/sql-server-mcp@1.0.4` | 280 | io.github.TharanaBope/sql-server-mcp |
| 109 | `npm:claude-amplifier@1.5.3` | 279 | io.github.Sisuthros/claude-amplifier |
| 110 | `npm:mneme-memory@0.1.1` | 279 | io.github.modusensus/mneme-memory |
| 111 | `npm:@j0hanz/memory-mcp@1.7.0` | 275 | io.github.j0hanz/memory-mcp |
| 112 | `npm:litescope@0.9.0` | 274 | io.github.croc100/litescope |
| 113 | `npm:@shibbirweb/mcp-mysql-read-only@1.1.6` | 270 | io.github.shibbirweb/mcp-mysql-read-only |
| 114 | `npm:@marcelo-ochoa/server-mysql@1.0.7` | 261 | io.github.marcelo-ochoa/mysql |
| 115 | `npm:sql-formatter-mcp@1.0.0` | 258 | io.github.mrfentmen/sql-formatter-mcp |
| 116 | `npm:@facthouse/mcp@0.31.0` | 257 | io.github.gordonkjlee/facthouse |
| 117 | `npm:@mrfentmen/wger-mcp@1.0.0` | 249 | io.github.mrfentmen/wger-mcp |
| 118 | `npm:mcp-db-connect@0.1.21` | 248 | io.github.phatngoit/mcp-db-connect |
| 119 | `npm:@dudko.dev/tabellum-mcp@0.1.2` | 247 | dev.dudko/tabellum |
| 120 | `npm:@openquality/mcp@0.2.0` | 247 | us.openquality/mcp |
| 121 | `npm:@shahid.la/cds-db-nlquery-mcp@0.7.3` | 245 | io.github.shahidla/cds-db-nlquery-mcp |
| 122 | `npm:agent-team-mcp@1.5.1` | 241 | io.github.RichardLemmon/agent-team |
| 123 | `npm:postgres-scout-mcp@1.0.3` | 241 | io.github.bluwork/postgres-scout-mcp |
| 124 | `npm:@learningnodes/elen-mcp@0.3.1` | 240 | com.learningnodes/elen |
| 125 | `npm:@shibbirweb/mcp-db-read-only@1.1.0` | 240 | io.github.shibbirweb/mcp-db-read-only |
| 126 | `npm:@mcpassure/mcp-tuss@0.1.2` | 239 | io.github.mcpassure/mcp-tuss |
| 127 | `npm:kryptheon-mcp@0.1.1` | 239 | io.github.jhashantanu987-beep/kryptheon |
| 128 | `npm:surrealdb-mcp@1.0.0` | 239 | io.github.mrfentmen/surrealdb-mcp |
| 129 | `npm:zektor@1.7.1` | 230 | io.github.m-akcan/zektor |
| 130 | `npm:sap-abap-sql-mcp@0.3.0` | 228 | run.daslab/sap-abap-sql |
| 131 | `npm:mnemon-mcp@1.0.1` | 227 | io.github.nikitacometa/mnemon-mcp |
| 132 | `npm:mongo-scout-mcp@1.0.3` | 226 | io.github.bluwork/mongo-scout-mcp |
| 133 | `npm:@hbarefoot/engram@1.6.3` | 223 | io.github.HBarefoot/engram |
| 134 | `npm:@retentioncheck/mcp-server@0.6.2` | 221 | io.github.brianfofficial/retentioncheck-mcp-server |
| 135 | `npm:tableau-lineage-mcp@1.0.1` | 217 | io.github.andey0Saikiran/tableau-lineage |
| 136 | `npm:@dbconvert/stream-mcp@2.7.3` | 216 | com.dbconvert/streams |
| 137 | `npm:@md-musaraf/sentinal-mcp@1.0.5` | 213 | io.github.Musaraf-M/sentinal-mcp |
| 138 | `npm:@mockherodev/mcp-server@0.2.0` | 210 | io.github.dinosaur24/mockhero |
| 139 | `npm:pour-picks-mcp@1.0.4` | 209 | io.github.bguillow-rgb/pour-picks |
| 140 | `npm:@copilot-datagate/cli@0.4.0` | 208 | io.github.afurlane/copilot-datagate |
| 141 | `npm:@theyahia/claude-webcache@0.1.5` | 208 | io.github.theYahia/claude-webcache |
| 142 | `npm:@factmem/mcp@0.26.0` | 205 | io.github.gordonkjlee/factmem |
| 143 | `npm:@infoinlet/mcp-postgres-nl-query@0.1.1` | 205 | io.github.infoinlet-marketplace/mcp-postgres-nl-query |
| 144 | `npm:@n3wth/r3@1.3.2` | 205 | io.github.n3wth/r3 |
| 145 | `npm:@nuzo/memory-mcp@1.2.0` | 204 | io.github.fabionfsc/nuzo-memory |
| 146 | `npm:dbhub-analytics@0.2.0` | 202 | io.github.amansingh63/dbhub-analytics |
| 147 | `npm:@2hemi/backendgen-mcp@0.2.2` | 198 | io.github.SiTouhemi/backendgen |
| 148 | `npm:@itunified.io/mcp-postgres@2026.4.10-1` | 197 | io.github.itunified-io/postgres |
| 149 | `npm:@mrfentmen/tmdb-mcp@1.0.0` | 196 | io.github.mrfentmen/tmdb-mcp |
| 150 | `npm:debug-recorder-mcp@1.1.3` | 195 | io.github.oaslananka/debug-recorder-mcp |
| 151 | `npm:@gluip/chart-canvas-mcp@0.3.2` | 194 | io.github.gluip/chart-canvas |
| 152 | `npm:razi-tools-mcp@2.1.2` | 194 | io.github.razikallayi/razi-tools |
| 153 | `npm:@joecwales/cartographer-mcp@0.1.3` | 189 | io.github.Metatronsdoob369/cartographer-mcp |
| 154 | `npm:@krimto-labs/krimto@0.2.47` | 189 | io.github.krimto-labs/krimto |
| 155 | `npm:@tharanabopearachchi/sql-server-mcp-macos@1.0.4` | 189 | io.github.TharanaBope/sql-server-mcp-macos |
| 156 | `npm:@abhishekmcp/sql@0.1.0` | 186 | io.github.Abhishekkumar2021/sql |
| 157 | `npm:claude-memory-fts@1.0.1` | 185 | io.github.kurovu146/memory-fts |
| 158 | `npm:postgres-connector@1.0.2` | 184 | io.github.martymarkenson/postgres-connector |
| 159 | `npm:percolate-mcp@1.0.2` | 182 | io.github.bguillow-rgb/percolate |
| 160 | `npm:mcp-schema-designer@1.1.4` | 181 | io.github.vpatser1/mcp-schema-designer |
| 161 | `npm:india-reg-mcp@1.0.1` | 179 | io.github.Akhilgovind02/india-regulatory-mcp |
| 162 | `npm:@infoinlet/mcp-mysql@0.1.1` | 178 | io.github.infoinlet-marketplace/mcp-mysql |
| 163 | `npm:@heshamfsalama/mcp-tool-factory@0.1.0` | 174 | io.github.HeshamFS/mcp-tool-factory |
| 164 | `npm:@mukundakatta/sqlfmt-mcp@0.1.0` | 169 | io.github.MukundaKatta/sqlfmt-mcp |
| 165 | `npm:freshtrack-mcp-server@1.0.1` | 167 | io.github.chrisbusbin-pixel/freshtrack |
| 166 | `npm:chassis-mcp@0.1.2` | 166 | io.github.dvd90/chassis-mcp |
| 167 | `npm:spreadsheet-db-mcp@0.1.1` | 166 | io.github.ManddarinShop/spreadsheet-db-mcp |
| 168 | `npm:@instanode/mcp@0.7.2` | 161 | io.github.InstaNode-dev/mcp |
| 169 | `npm:mysql-ops-mcp@1.0.0` | 161 | io.github.GT-dinuo/mysql-ops-mcp |
| 170 | `npm:@rdrco/mcp-ordali-memory@1.0.1` | 158 | io.github.robin-deruyck/mcp-ordali-memory |
| 171 | `npm:@seraviahealth/glp1search-mcp@2.0.1` | 158 | io.github.Sndevore77/glp1search |
| 172 | `npm:@infoinlet/mcp-mongodb@0.1.1` | 157 | io.github.infoinlet-marketplace/mcp-mongodb |
| 173 | `npm:@memharness/mcp@0.1.2` | 156 | io.github.las7/memharness |
| 174 | `npm:mcp-pg-server@1.0.0` | 153 | io.github.ofershap/postgres |
| 175 | `npm:database-admin-mcp@1.0.1` | 152 | io.github.cybeleri/database-admin |
| 176 | `npm:@infoinlet/mcp-redis@0.1.1` | 150 | io.github.infoinlet-marketplace/mcp-redis |
| 177 | `npm:@rog0x/mcp-database-tools@1.0.1` | 149 | io.github.rog0x/database |
| 178 | `npm:@unclick/igdb-mcp@0.1.0` | 148 | io.github.malamutemayhem/igdb |
| 179 | `npm:@infoinlet/mcp-data@0.1.1` | 143 | io.github.infoinlet-marketplace/mcp-data |
| 180 | `npm:locksmith-mcp@0.1.1` | 141 | io.github.cxk280/locksmith |
| 181 | `npm:@nodeproxy/vectorcache@0.1.1` | 125 | io.github.pgalyen1987/vectorcache |
| 182 | `npm:zotero-bridge@1.0.3` | 100 | io.github.Combjellyshen/zotero-bridge |
| 183 | `npm:mcp-debug-recorder@1.0.1` | 0 | io.github.oaslananka/mcp-debug-recorder |
| 184 | `pypi:a2db@0.2.1` | pypi | io.github.agentic-eng/a2db |
| 185 | `pypi:agentramen@0.2.5` | pypi | io.github.palrajjp/agentramen |
| 186 | `pypi:aifp@0.1.1` | pypi | io.github.aryanduntley/aifp |
| 187 | `pypi:amormorri-memory-kernel@0.3.2` | pypi | io.github.Artem362/memory-kernel |
| 188 | `pypi:anamnesis-memory@0.1.3` | pypi | io.github.oscardvs/anamnesis |
| 189 | `pypi:b280-olca-mcp@1.16.0` | pypi | io.github.Below280/b280-olca-mcp |
| 190 | `pypi:bollard-mcp@0.1.4` | pypi | io.github.ImDeepaksingh/bollard-mcp |
| 191 | `pypi:boyce@0.1.1` | pypi | io.github.boyce-io/boyce |
| 192 | `pypi:colabfit-mcp@0.0.3` | pypi | io.github.colabfit/colabfit-mcp |
| 193 | `pypi:cpersona@2.5.3` | pypi | io.github.Cloto-dev/cpersona |
| 194 | `pypi:crowbar-cli@0.1.5` | pypi | io.github.kushvinth/crowbar |
| 195 | `pypi:custom-mcp-database@0.6.2` | pypi | io.github.renanlido/custom-mcp-database |
| 196 | `pypi:dagpipe-core@0.2.3` | pypi | io.github.devilsfave/dagpipe |
| 197 | `pypi:datasaudi-mcp@0.1.0` | pypi | io.github.mohsinmshabbir/datasaudi-mcp |
| 198 | `pypi:dataxplan-mcp@0.1.0` | pypi | io.github.arikanatakan/dataxplan-mcp |
| 199 | `pypi:db-compare-mcp@v0.1.1` | pypi | io.github.yadu-tv/db-compare |
| 200 | `pypi:db-explorer-mcp-server@0.1.0` | pypi | io.github.AYUSH-148/db-explorer-mcp-server |
| 201 | `pypi:db-metadata-extractor-mcp@0.1.6` | pypi | io.github.Optisol-Business/db-metadata-extractor-mcp |
| 202 | `pypi:fastbcp-mcp@0.1.5` | pypi | io.github.arpe-io/fastbcp-mcp |
| 203 | `pypi:fastmcp-sqltools@0.3.0` | pypi | io.github.atarkowska/fastmcp-sqltools |
| 204 | `pypi:firebird-mcp@0.1.0` | pypi | io.github.lucasgabriel0802/firebird-mcp |
| 205 | `pypi:garmin-local-mcp@0.1.9` | pypi | io.github.anup-shesh/garmin-local-mcp |
| 206 | `pypi:gnosis-mcp@0.17.5` | pypi | io.github.nicholasglazer/gnosis |
| 207 | `pypi:greptimedb-mcp-server@0.6.0` | pypi | io.github.GreptimeTeam/greptimedb-mcp-server |
| 208 | `pypi:knowledge-graph-rdbms@0.1.9` | pypi | io.github.cunicopia-dev/knowledge-graph-rdbms |
| 209 | `pypi:lakexpress-mcp@0.1.6` | pypi | io.github.arpe-io/lakexpress-mcp |
| 210 | `pypi:lean-memory@0.3.0` | pypi | io.github.Wuesteon/lean-memory |
| 211 | `pypi:local-faiss-mcp@0.2.0-rc.3` | pypi | io.github.nonatofabio/local-faiss-mcp |
| 212 | `pypi:localhost-doctor@0.1.0` | pypi | io.github.Jazzfer-2003/localhost-doctor |
| 213 | `pypi:mcp-code-index@1.0.6` | pypi | io.github.achreftlili/code-index |
| 214 | `pypi:mcp-feed-reader-crunchtools@0.1.2` | pypi | io.github.crunchtools/feed-reader |
| 215 | `pypi:mcp-memex@0.1.9` | pypi | io.github.pragneshbagary/memex |
| 216 | `pypi:mcp-mysql-connector@0.1.1` | pypi | io.github.daedalus/mcp-mysql-connector |
| 217 | `pypi:mcp-psycopg2@0.1.0` | pypi | io.github.daedalus/mcp-psycopg2 |
| 218 | `pypi:mcp-redis-server@0.1.0` | pypi | io.github.daedalus/mcp-redis-server |
| 219 | `pypi:mcp-sequential-thinking@0.7.0` | pypi | io.github.arben-adm/mcp-sequential-thinking |
| 220 | `pypi:mcp-server-mssql@0.1.0` | pypi | io.github.daedalus/mcp-server-mssql |
| 221 | `pypi:mcp-server-spreadsheet@0.3.3` | pypi | io.github.marekrost/mcp-server-spreadsheet |
| 222 | `pypi:mcp-server-vector-memory@0.4.4` | pypi | io.github.NeerajG03/vector-memory |
| 223 | `pypi:mcp-snowflake-server-nsp@0.14.4` | pypi | io.github.nsphung/mcp-snowflake-server |
| 224 | `pypi:mcp-sql-querystore@0.1.1` | pypi | io.github.deepeshd87/mcp-sql-querystore |
| 225 | `pypi:mcparmory-pinecone@1.0.2` | pypi | com.mcparmory/pinecone |
| 226 | `pypi:mcpsmith@0.6.0` | pypi | io.github.sepehr071/mcpsmith |
| 227 | `pypi:memory-hive-mcp@0.1.9` | pypi | io.github.330899935/hive-memory |
| 228 | `pypi:memorymesh@4.1.0` | pypi | io.github.sparkvibe-io/memorymesh |
| 229 | `pypi:memtether@0.1.0a73` | pypi | io.github.lanbass869-cell/memtether |
| 230 | `pypi:memwright@0.1.3` | pypi | io.github.bolnet/memwright |
| 231 | `pypi:microquery-mcp@1.0.3` | pypi | io.github.microqueryhq/microquery-mcp |
| 232 | `pypi:migratorxpress-mcp@0.1.6` | pypi | io.github.arpe-io/migratorxpress-mcp |
| 233 | `pypi:misata@0.9.8` | pypi | io.github.rasinmuhammed/misata |
| 234 | `pypi:mlx-memo@4.16.0` | pypi | io.github.jagoff/memo |
| 235 | `pypi:mofi-tools@0.1.0` | pypi | io.github.harrisonmo/mofi |
| 236 | `pypi:mysql-audit-ai-agent@0.3.3` | pypi | io.github.jimmyjan0824/mysql-audit |
| 237 | `pypi:n3memorycore-mcp-lite@1.6.2` | pypi | io.github.NeuralNexusNote/n3mc-workingmemory |
| 238 | `pypi:openchronicle-mcp@3.0.0.dev1` | pypi | io.github.CSOAI-ORG/openchronicle-mcp |
| 239 | `pypi:orionbelt-analytics@0.5.0` | pypi | io.github.ralfbecher/orionbelt-analytics |
| 240 | `pypi:orionbelt-semantic-layer@0.3.0` | pypi | io.github.ralfbecher/orionbelt-semantic-layer |
| 241 | `pypi:pensieve-mcp@0.1.0` | pypi | io.github.praveen-ilangovan/pensieve |
| 242 | `pypi:pg-bloat-detective@0.1.6` | pypi | io.github.r69shabh/pg-bloat-detective |
| 243 | `pypi:pg-cve-mcp@1.0.4` | pypi | io.github.meob/pg-cve-mcp |
| 244 | `pypi:pgtriage@0.3.0` | pypi | io.github.pgtriage/pgtriage |
| 245 | `pypi:pgtuner-mcp@0.5.2` | pypi | io.github.isdaniel/pgtuner_mcp |
| 246 | `pypi:pitstop-f1@0.5.0` | pypi | io.github.praneethravuri/pitstop |
| 247 | `pypi:pyspark-tools@0.1.0` | pypi | io.github.AnnasMazhar/pyspark-mcp |
| 248 | `pypi:redis-mcp-server@0.5.1` | pypi | io.github.redis/mcp-redis |
| 249 | `pypi:repo-memory-mcp-ai@0.2.0` | pypi | io.github.Umarjaum/repo-memory-mcp |
| 250 | `pypi:rowbase-db@0.3.0` | pypi | io.github.djstreet11/rowbase |
| 251 | `pypi:simpliq-mcp-server-dev-test@0.1.1` | pypi | io.github.gersonfreire/simpliq-server |
| 252 | `pypi:skillmem@0.13.0` | pypi | io.github.liza-studio/skillmem |
| 253 | `pypi:sling@1.4.23.post1` | pypi | io.slingdata/sling-cli |
| 254 | `pypi:sql-builder-ai-mcp@1.0.8` | pypi | io.github.CSOAI-ORG/sql-builder-ai-mcp |
| 255 | `pypi:sqlbenchdag@0.1.2` | pypi | io.github.rctruta/sqlbenchdag |
| 256 | `pypi:sqlglass@0.1.0` | pypi | io.github.S-CurveLabs/sqlglass |
| 257 | `pypi:sqlite-mcp-server-enhanced@2.6.3` | pypi | io.github.neverinfamous/sqlite-mcp-server |
| 258 | `pypi:tablebridge@0.1.1` | pypi | io.github.Michael-WhiteCapData/tablebridge-mcp |
| 259 | `pypi:termdat-mcp@0.2.0` | pypi | io.github.malkreide/termdat-mcp |
| 260 | `pypi:terminal-mcp@0.3.1` | pypi | io.github.mkpvishnu/terminal-mcp |
| 261 | `pypi:tether-memory@0.6.1` | pypi | io.github.sidyellur/tether |
| 262 | `pypi:text-spreadsheet@0.5.0` | pypi | io.github.demos-ra/text-spreadsheet |
| 263 | `pypi:tinysuite-context@0.5.4` | pypi | io.github.TinySuiteHQ/tinycontext |
| 264 | `pypi:toolsmelt@0.8.0` | pypi | io.github.sepehr071/toolsmelt |
| 265 | `pypi:universal-db-mcp@1.1.2` | pypi | io.github.Fashad-Ahmed/universal-db-mcp |
| 266 | `pypi:vault-index@0.4.2` | pypi | io.github.GitGudatCodeing/vault-index |
| 267 | `pypi:w8s-astro-mcp@0.15.2` | pypi | io.github.w8s/w8s-astro-mcp |
| 268 | `pypi:wherewent@0.4.1` | pypi | io.github.habibafaisal/wherewent |

</details>

<details><summary>messaging: 154 candidates</summary>

| # | package | downloads | registry name |
|---|---|---|---|
| 1 | `npm:emailmd@0.13.2` | 19455 | dev.emailmd/emailmd |
| 2 | `npm:@fairquery/agent-trust-mcp@1.1.10` | 4526 | com.getfairquery/agent-trust-mcp |
| 3 | `npm:@fairquery/agent-trust-mcp@1.1.2` | 4526 | io.github.fairquery/fairquery-agent-trust-mcp |
| 4 | `npm:imap-mcp-server@2.2.0` | 4021 | io.github.nikolausm/imap-mcp-server |
| 5 | `npm:@codefuturist/email-mcp@0.6.0` | 3848 | io.github.codefuturist/email-mcp |
| 6 | `npm:@kaptionai/mcp-extension@0.5.11` | 3462 | io.github.Kaption-AI/mcp-extension |
| 7 | `npm:netintel-mcp@1.1.68` | 2049 | io.github.kjgueye/netintel-mcp |
| 8 | `npm:@mrfentmen/telegram-mcp@1.1.0` | 2004 | io.github.mrfentmen/telegram-mcp |
| 9 | `npm:@marlinjai/email-mcp@1.2.3` | 1515 | io.github.marlinjai/email-mcp |
| 10 | `npm:intodns-mcp@1.11.3` | 1499 | ai.intodns/scanner |
| 11 | `npm:@littlebearapps/outlook-assistant@3.14.1` | 1482 | io.github.littlebearapps/outlook-assistant |
| 12 | `npm:brevo-mcp@1.0.1` | 1325 | io.github.mrfentmen/brevo-mcp |
| 13 | `npm:@ismalicious/mcp-server@0.8.0` | 1323 | com.ismalicious/mcp-server |
| 14 | `npm:pickle-mcp@1.1.0` | 1215 | io.github.adityaarsharma/pickle |
| 15 | `npm:@mrfentmen/slack-mcp@1.1.0` | 1199 | io.github.mrfentmen/slack-mcp |
| 16 | `npm:@tmhs/tailscale-mcp@0.4.0` | 1186 | io.github.TMHSDigital/tailscale-mcp |
| 17 | `npm:gws-mcp-server@0.4.1` | 1169 | io.github.conorbronsdon/gws-mcp-server |
| 18 | `npm:email-validator-mcp@1.0.2` | 1116 | io.github.mrfentmen/email-validator-mcp |
| 19 | `npm:@mrfentmen/resend-mcp@1.1.0` | 1057 | io.github.mrfentmen/resend-mcp |
| 20 | `npm:disify-mcp@1.0.2` | 1018 | io.github.mrfentmen/disify-mcp |
| 21 | `npm:atxp@1.21.1` | 991 | io.github.atxp-dev/atxp |
| 22 | `npm:doh-mcp@1.0.0` | 944 | io.github.mrfentmen/doh-mcp |
| 23 | `npm:payperscreen-mcp@0.1.3` | 931 | io.github.TonytheTiger22/payperscreen |
| 24 | `npm:@misarmail/mcp@5.1.2` | 910 | io.github.Misar-AI/misarmail-mcp |
| 25 | `npm:@aaronsb/slack-mcp@2.8.1` | 901 | io.github.aaronsb/slack-mcp |
| 26 | `npm:@palisadeemail/mcp@0.2.1` | 878 | email.palisade/palisade |
| 27 | `npm:mbox-mcp@0.1.1` | 863 | io.github.arose26/mbox-mcp |
| 28 | `npm:gambot-mcp@1.9.1` | 840 | io.github.gambot-ai/gambot-mcp |
| 29 | `npm:@voidly/mcp-email@2.1.1` | 831 | io.github.voidly-ai/mcp-email |
| 30 | `npm:tgcloud-mcp@0.3.3` | 812 | io.github.sdamarketing/tgcloud-mcp |
| 31 | `npm:x402-paid-checks-mcp@0.1.1` | 800 | io.github.dario933/x402-paid-checks |
| 32 | `npm:softbot-mcp@0.2.0` | 768 | io.github.softbot-studio/softbot-mcp |
| 33 | `npm:@ar-agents/mcp@0.4.11` | 733 | io.github.ar-agents/mcp |
| 34 | `npm:matrix-tsunagi@0.4.0` | 657 | io.github.mushitaro/matrix-tsunagi-mapping |
| 35 | `npm:@mrfentmen/qr-mcp@1.0.1` | 648 | io.github.mrfentmen/qr-mcp |
| 36 | `npm:mcpj-mailtrap@0.1.4` | 613 | io.github.pijusz/mcp-mailtrap |
| 37 | `npm:monacloud-mcp@0.11.1` | 591 | vn.monacloud/monacloud-mcp |
| 38 | `npm:mailbox-mcp@0.13.1` | 565 | io.github.jgalea/mailbox-mcp |
| 39 | `npm:tdl-mcp@1.1.0` | 554 | io.github.rixile9999/tdl-mcp |
| 40 | `npm:domain-radar@1.2.0` | 552 | surf.insight/domain-radar |
| 41 | `npm:@opafex/mcp-enrichment@0.1.1` | 541 | io.github.Opafex/mcp-enrichment |
| 42 | `npm:@mepmail/mcp@0.3.2` | 524 | io.github.JE4NVRG/mepmail |
| 43 | `npm:multi-gmail-account-mcp@0.3.0` | 492 | io.github.psdgator/multi-gmail-account-mcp |
| 44 | `npm:neverbounce-mcp@1.0.0` | 475 | io.github.mrfentmen/neverbounce-mcp |
| 45 | `npm:@massrelayai/comparegraph@0.1.3` | 469 | io.github.MassRelayAI/comparegraph |
| 46 | `npm:mailcycle-mcp@0.6.2` | 461 | email.mailcycle/mailcycle |
| 47 | `npm:matrix-tsunagi-migration@0.4.0` | 452 | io.github.mushitaro/matrix-tsunagi-migration |
| 48 | `npm:mailbridge-mcp@2.6.1` | 438 | io.github.Creativestefan/mailbridge |
| 49 | `npm:markdown-to-whatsapp@1.0.3` | 434 | io.github.drsound/markdown-to-whatsapp |
| 50 | `npm:gmail-workspace-mcp-server@0.4.12` | 426 | com.pulsemcp/gmail |
| 51 | `npm:proxyllm-mcp@1.0.2` | 424 | ai.proxyllm/proxyllm-mcp |
| 52 | `npm:mail-tm-mcp@1.0.0` | 418 | io.github.mrfentmen/mail-tm-mcp |
| 53 | `npm:@rowsend/mcp@1.0.0` | 414 | com.rowsend/rowsend |
| 54 | `npm:@sendkuy/mcp@1.0.0` | 412 | com.sendkuy/mcp |
| 55 | `npm:replylayer-mcp@0.15.1` | 412 | ai.replylayer/replylayer |
| 56 | `npm:@clize/inbox@0.35.5` | 409 | ai.clize/inbox |
| 57 | `npm:@chamade/mcp-server@5.1.0` | 395 | io.chamade/server |
| 58 | `npm:easy-email-builder-mcp@0.1.3` | 378 | io.github.Shahkarkhan440/easy-email-builder |
| 59 | `npm:@pntr/cli@0.3.3` | 375 | dev.pntr/pntr |
| 60 | `npm:@readystack/email-footer-law-lint@1.0.6` | 362 | io.github.jmshinhwa/email-footer-law-lint |
| 61 | `npm:opensdr-mcp@1.0.1` | 356 | io.github.arif-js/opensdr-mcp |
| 62 | `npm:email-guard-mcp@1.3.0` | 340 | io.github.mlawsonking/email-guard-mcp |
| 63 | `npm:emptyinbox-mcp@1.5.0` | 339 | io.github.cnohall/emptyinbox |
| 64 | `npm:mail-index@1.0.0` | 324 | io.github.alunsoldantarctica/mail-index |
| 65 | `npm:mail-index@1.5.1` | 324 | io.github.unsoldgroup/mail-index |
| 66 | `npm:@multimail/mcp-server@0.13.0` | 314 | dev.multimail/mcp-server |
| 67 | `npm:multi-gmail-mcp@1.0.1` | 305 | io.github.gx-55/multi-gmail-mcp |
| 68 | `npm:@myotp/mcp@0.1.14` | 300 | io.github.brntech/myotp |
| 69 | `npm:salamailer@1.0.0` | 297 | fi.salamailer/salamailer |
| 70 | `npm:agentsbase-mcp@1.0.1` | 296 | net.agentsbase/mcp |
| 71 | `npm:@readystack/outlook-email-html-lint@0.1.1` | 292 | io.github.jmshinhwa/outlook-email-html-lint |
| 72 | `npm:cursor-telegram-chat@0.1.23` | 290 | io.github.udah1/cursor-chat-bridge |
| 73 | `npm:@p-l-ta/mail-mcp@1.3.5` | 288 | io.github.p-l-ta/mail-mcp |
| 74 | `npm:mcp-whatsapp-web@1.2.0` | 287 | io.github.mario-andreschak/mcp-whatsapp-web |
| 75 | `npm:agentcanary-mcp@1.4.8` | 281 | io.github.MrCerq/agentcanary |
| 76 | `npm:limzo-mcp@1.3.1` | 279 | com.limzo/telegram-group-stats |
| 77 | `npm:radmail-mcp@0.5.0` | 277 | ai.radmail/radmail-mcp |
| 78 | `npm:@rheopyrin/ox-mcp@0.1.4` | 274 | io.github.Rheopyrin/ox-mcp |
| 79 | `npm:telegram-slack-mcp@0.5.1` | 273 | io.github.nileshpatil6/telegram-slack-mcp |
| 80 | `npm:@keyid/agent-kit@0.4.1` | 265 | io.github.KeyID-AI/keyid |
| 81 | `npm:@ascendkit/cli@0.3.22` | 263 | dev.ascendkit/ascendkit |
| 82 | `npm:@chartone/mcp@0.1.7` | 251 | io.github.zhugejun/chartone |
| 83 | `npm:nintact-mcp@0.5.1` | 245 | com.nintact/nintact |
| 84 | `npm:zerosmtp-mcp@1.0.2` | 240 | io.github.msgwing/zerosmtp |
| 85 | `npm:@mbeato/apimesh-mcp-server@1.8.2` | 238 | io.github.mbeato/apimesh |
| 86 | `npm:agent-cold-email@0.2.2` | 238 | io.github.YS-projectcalc/agent-cold-email |
| 87 | `npm:@mrfentmen/discord-mcp@1.0.0` | 227 | io.github.mrfentmen/discord-mcp |
| 88 | `npm:microsoft-outlook-mcp@1.0.1` | 227 | io.github.0xka13b/microsoft-outlook-mcp |
| 89 | `npm:@worldcitisim/mcp-esim@0.2.2` | 224 | com.worldcitisim/mcp-esim |
| 90 | `npm:octapi-mcp@0.1.1` | 211 | app.octapi/mcp |
| 91 | `npm:@bitofacoder/omni-mcp-server@1.1.1` | 210 | io.github.bitofacoder/omni-mcp-server |
| 92 | `npm:@sendsoon/mcp@0.3.8` | 208 | io.github.sendsoon/mcp |
| 93 | `npm:@gamercc-apps/mockscreenshots-mcp@0.1.6` | 205 | io.github.gamercc-apps/mockscreenshots-mcp |
| 94 | `npm:mailappmcp@0.4.1` | 205 | io.github.aernouddekker/mailappmcp |
| 95 | `npm:@arcxs-protocol/mcp-server@1.0.3` | 202 | io.github.ARCXS-Protocol/mcp-server |
| 96 | `npm:@intelagent/mcp-enrichment@0.1.1` | 201 | io.github.IntelagentStudios/mcp-enrichment |
| 97 | `npm:telemost-mcp-server@0.2.2` | 201 | io.telemost/telemost-mcp-server |
| 98 | `npm:@dancumberland/kit-mcp@1.0.1` | 199 | io.github.dancumberland/kit-mcp |
| 99 | `npm:@egosbr/guard-brasil-mcp@0.2.3` | 195 | io.github.enioxt/guard-brasil-mcp |
| 100 | `npm:broke2built-skills-mcp@1.1.1` | 194 | io.github.lordbasilaiassistant-sudo/broke2built-skills-mcp |
| 101 | `npm:sendmux-mcp@1.0.0` | 192 | io.github.Sendmux/sendmux-mcp |
| 102 | `npm:@warmysender/mcp@1.0.1` | 190 | com.warmysender/mcp |
| 103 | `npm:@x402-tools/mcp@1.8.0` | 181 | io.github.acrylicfiddle/x402tools |
| 104 | `npm:neuron-mcp-server@1.0.1` | 180 | io.github.conquext/neuron |
| 105 | `npm:namecatcher-mcp@0.1.1` | 173 | io.github.productmap/namecatcher-skills |
| 106 | `npm:best-tempmail-mcp@1.0.2` | 172 | io.github.mbilalawan926-sys/best-tempmail-mcp |
| 107 | `npm:@infoinlet/mcp-email@0.1.1` | 164 | io.github.infoinlet-marketplace/mcp-email |
| 108 | `npm:mcp-server-security-audit@1.0.3` | 164 | io.github.joepangallo/mcp-server-security-audit |
| 109 | `npm:mcpdomain@1.0.7` | 163 | io.github.danboabes/mcpdomain |
| 110 | `npm:@sathergate/notifykit@0.1.0` | 162 | io.github.sathergate/notifykit |
| 111 | `npm:mail7-mcp@0.1.1` | 157 | net.mail7/email-validation |
| 112 | `npm:standup-mcp@0.1.0` | 156 | io.github.sathvic-kollu/standup-mcp |
| 113 | `npm:retro-mcp@0.1.0` | 151 | io.github.sathvic-kollu/retro-mcp |
| 114 | `npm:@furlow/mcp@1.0.1` | 118 | io.github.virgilvox/furlow-mcp |
| 115 | `npm:telegram-channel-scraper-mcp-server@1.0.1` | 0 | io.github.khadinakbaronline/telegram-channel-scraper-mcp |
| 116 | `pypi:adelaidasofia-whatsapp-mcp@0.1.1` | pypi | io.github.adelaidasofia/whatsapp-mcp |
| 117 | `pypi:agentmailkit@0.2.2` | pypi | io.github.ariaxhan/agentmailkit |
| 118 | `pypi:apex-mcp-framework@1.1.1` | pypi | io.github.ogconstrutorasp/apex-contabil |
| 119 | `pypi:byteplant-mcp@1.1.0` | pypi | io.github.byteplant-devops/byteplant-mcp |
| 120 | `pypi:dead-letter@0.4.10` | pypi | io.github.BigCactusLabs/dead-letter |
| 121 | `pypi:email-tool-mcp@5.6.0` | pypi | io.github.skhan61/email-tool |
| 122 | `pypi:exchange-mcp-server@1.0.1` | pypi | io.github.nhype/owa-exchange-mcp |
| 123 | `pypi:gauge-mcp@0.2.1` | pypi | io.github.seayniclabs/gauge |
| 124 | `pypi:gigamail@0.3.4` | pypi | io.github.adecubed/gigamail |
| 125 | `pypi:gmail-agent@0.3.1` | pypi | io.github.dremok/gmail-agent |
| 126 | `pypi:gmail-attachments-mcp@0.1.0` | pypi | io.github.zayansalman/gmail-attachments-mcp |
| 127 | `pypi:grandline-mcp@0.2.1` | pypi | io.github.dmsnavin/grandline-mcp |
| 128 | `pypi:grandline-mcp@0.2.2` | pypi | io.github.luzomi/grandline-mcp |
| 129 | `pypi:guarded-whatsapp-mcp@0.1.0` | pypi | io.github.peter-tnc-453/guarded-whatsapp-mcp |
| 130 | `pypi:inbox-to-action@0.2.11` | pypi | io.github.tarunlnmiit/inbox-to-action |
| 131 | `pypi:jaimenbell-discord-mcp@0.1.1` | pypi | io.github.jaimenbell/discord-mcp |
| 132 | `pypi:kiprio-mcp@0.6.0` | pypi | com.kiprio/kiprio-mcp |
| 133 | `pypi:mcp-notify@0.1.11` | pypi | io.github.aahl/mcp-notify |
| 134 | `pypi:mcp-slack-crunchtools@0.1.2` | pypi | io.github.crunchtools/slack |
| 135 | `pypi:mcp-telegram-bot@0.1.0` | pypi | io.github.daedalus/mcp-telegram-bot |
| 136 | `pypi:mcp-telegram-bridge@0.2.1` | pypi | io.github.antonio-castellon/mcp-telegram-bridge |
| 137 | `pypi:mcparmory-google-gmail@1.0.4` | pypi | com.mcparmory/google-gmail |
| 138 | `pypi:mcparmory-klaviyo@1.0.3` | pypi | com.mcparmory/klaviyo |
| 139 | `pypi:mcparmory-postmark@1.0.2` | pypi | com.mcparmory/postmark |
| 140 | `pypi:mcparmory-slack@1.0.1` | pypi | com.mcparmory/slack |
| 141 | `pypi:mcpproducts-mail@0.1.1` | pypi | com.mcpproducts/mail |
| 142 | `pypi:multi-account-gmail-mcp@0.3.0` | pypi | io.github.cunicopia-dev/multi-account-gmail-mcp |
| 143 | `pypi:n0s1-mcp@1.1.6` | pypi | io.github.spark1security/n0s1-mcp |
| 144 | `pypi:n24q02m-telegram@4.23.0` | pypi | io.github.n24q02m/better-telegram-mcp |
| 145 | `pypi:rubit-mcp-mail@1.0.0` | pypi | io.github.bgalmes/rubit-mcp-mail |
| 146 | `pypi:slack-enterprise-mcp@1.0.9` | pypi | io.github.CSOAI-ORG/slack-enterprise-mcp |
| 147 | `pypi:telegram-ai-cli-mcp@0.1.3` | pypi | io.github.stufently/telegram-ai-cli-mcp |
| 148 | `pypi:telegram-managed-bot-factory@0.1.0` | pypi | io.github.laser54/bot-factory |
| 149 | `pypi:telegram-mcp-jgalea@0.1.2` | pypi | io.github.jgalea/telegram-mcp |
| 150 | `pypi:validator-ai-mcp@1.0.11` | pypi | io.github.CSOAI-ORG/validator-ai-mcp |
| 151 | `pypi:wa-chat-reader@0.1.0` | pypi | io.github.NabheetCloud/wa-chat-reader |
| 152 | `pypi:webhook-mcp-server@3.0.0` | pypi | io.github.zebbern/webhook-mcp-server |
| 153 | `pypi:webvoice-mcp@0.2.1` | pypi | io.github.supermarco74/webvoice-mcp |
| 154 | `pypi:whatsapp-mcp-macos@0.1.1` | pypi | io.github.kalki-kgp/whatsapp-macos |

</details>

<details><summary>web: 188 candidates</summary>

| # | package | downloads | registry name |
|---|---|---|---|
| 1 | `npm:@perplexity-ai/mcp-server@1.2.1` | 132575 | ai.perplexity/mcp-server |
| 2 | `npm:@perplexity-ai/mcp-server@0.7.0` | 132575 | io.github.perplexityai/mcp-server |
| 3 | `npm:smart-web-mcp@1.10.19` | 5178 | io.github.jojo-labs/smart-web |
| 4 | `npm:smart-web-mcp@0.8.4` | 5178 | io.github.rich-jojo/smart-web |
| 5 | `npm:poltertab@1.12.0` | 3939 | io.github.abhinav162/poltertab |
| 6 | `npm:@1claw/mcp@0.56.3` | 2930 | io.github.1clawAI/1claw-mcp |
| 7 | `npm:@decodo/mcp-server@1.7.0` | 2738 | io.github.Decodo/mcp-server |
| 8 | `npm:@youdotcom-oss/mcp@4.0.7` | 2724 | io.github.youdotcom-oss/mcp |
| 9 | `npm:@cyanheads/wikidata-mcp-server@0.3.0` | 1847 | io.github.cyanheads/wikidata-mcp-server |
| 10 | `npm:xactions@3.5.0` | 1742 | io.github.nirholas/xactions |
| 11 | `npm:pitworld@0.5.0` | 1683 | world.pit/pit |
| 12 | `npm:@openserp/mcp@0.1.12` | 1637 | org.openserp/mcp |
| 13 | `npm:@cyanheads/noaa-marine-mcp-server@0.7.1` | 1480 | io.github.cyanheads/noaa-marine-mcp-server |
| 14 | `npm:@cyanheads/worms-marine-taxa-mcp-server@0.2.0` | 1424 | io.github.cyanheads/worms-marine-taxa-mcp-server |
| 15 | `npm:@contextfetch/mcp@1.1.0` | 1384 | dev.contextfetch/mcp |
| 16 | `npm:@crabcrop/mcp@0.1.0` | 1367 | io.github.crabcrop/crabcrop |
| 17 | `npm:@cyanheads/openlibrary-mcp-server@0.4.0` | 1271 | io.github.cyanheads/openlibrary-mcp-server |
| 18 | `npm:@eurafaeldecarvalho/browser-scraper@0.8.3` | 1271 | io.github.eurafaeldecarvalho/browser-scraper |
| 19 | `npm:search-memory-mcp@1.2.0` | 1233 | io.github.kefyusuf/search-memory-mcp |
| 20 | `npm:@cyanheads/stackexchange-mcp-server@0.2.0` | 1171 | io.github.cyanheads/stackexchange-mcp-server |
| 21 | `npm:search-rotation@0.4.10` | 1097 | io.github.localfoundry/search-rotation |
| 22 | `npm:webpeel@0.3.0` | 1068 | io.github.JakeLiuMe/webpeel |
| 23 | `npm:one-search-mcp@1.2.4` | 1062 | io.github.yokingma/one-search-mcp |
| 24 | `npm:comment-scraper-mcp@0.1.3` | 1057 | io.github.supertj/comment-scraper-mcp |
| 25 | `npm:searxng-mcp-server@1.0.1` | 953 | io.github.bumbaRasch/searxng-mcp-server |
| 26 | `npm:commoncrawl-mcp@1.0.1` | 930 | io.github.mrfentmen/commoncrawl-mcp |
| 27 | `npm:brandbrain-flow-orchestrator-mcp@0.4.0` | 922 | dev.brandbrain/flow-orchestrator |
| 28 | `npm:books-mcp@1.0.0` | 908 | io.github.mrfentmen/books-mcp |
| 29 | `npm:celestrak-mcp@1.0.1` | 877 | io.github.mrfentmen/celestrak-mcp |
| 30 | `npm:mcp-lrclib@2.1.0` | 870 | io.github.smeet666/mcp-lrclib |
| 31 | `npm:@cryptoapis-io/mcp-x402-pay@0.5.3` | 850 | io.github.CryptoAPIs-io/mcp-x402-pay |
| 32 | `npm:@j0hanz/fetch-url-mcp@3.0.1` | 815 | io.github.j0hanz/fetch-url-mcp |
| 33 | `npm:ellmos-filecommander-mcp@1.11.4` | 812 | io.github.ellmos-ai/ellmos-filecommander-mcp |
| 34 | `npm:scrape-le-mcp@2.6.0` | 810 | io.github.nolindnaidoo/scrape-le |
| 35 | `npm:geo-optimizer-mcp@0.5.1` | 766 | com.causabi/geo-optimizer-mcp |
| 36 | `npm:jvmsrc@1.16.0` | 764 | io.github.Sintexer/jvmsrc |
| 37 | `npm:@mrfentmen/duckduckgo-mcp@1.0.1` | 741 | io.github.mrfentmen/duckduckgo-mcp |
| 38 | `npm:@mrfentmen/ucsc-genome-mcp@1.0.1` | 726 | io.github.mrfentmen/ucsc-genome-mcp |
| 39 | `npm:designmark@1.0.0` | 723 | io.github.xecin-inc/designmark |
| 40 | `npm:flipside-mcp@1.0.0` | 707 | io.github.mrfentmen/flipside-mcp |
| 41 | `npm:agent-search-mcp@3.2.1` | 679 | io.github.lennney/agent-search-mcp |
| 42 | `npm:maiday-mcp@0.1.3` | 677 | io.github.35furkan/maiday |
| 43 | `npm:google-news-scraper-mcp@0.1.2` | 657 | io.github.lewisdonovan/google-news |
| 44 | `npm:mcp-lyricscom@2.1.0` | 643 | io.github.smeet666/mcp-lyricscom |
| 45 | `npm:tileio-mcp@1.0.0` | 623 | com.tileio/tileio |
| 46 | `npm:@pulsemcp/pulse-fetch@0.3.3` | 616 | com.pulsemcp/pulse-fetch |
| 47 | `npm:@aliasmode/anyfetch@0.8.3` | 593 | io.github.aliasmode/anyfetch |
| 48 | `npm:hermes-atlas-mcp@0.2.0` | 584 | io.github.ksimback/hermes-atlas-mcp |
| 49 | `npm:@queryrev/ai-readiness-mcp@1.0.0` | 581 | com.queryrev/ai-readiness |
| 50 | `npm:unrendered-mcp@0.1.4` | 554 | io.github.missiongrowth/unrendered-ai-crawler-checker |
| 51 | `npm:xfuel-mcp@0.1.1` | 552 | io.github.XFuel-Lab/xfuel-mcp |
| 52 | `npm:@agent-infra/mcp-server-search@latest` | 541 | io.github.bytedance/mcp-server-search |
| 53 | `npm:@opafex/mcp-web-research@0.1.0` | 529 | io.github.Opafex/mcp-web-research |
| 54 | `npm:websearch-api-eval-mcp@1.1.0` | 518 | io.github.psinglap/websearch-api-eval |
| 55 | `npm:auxiliar-mcp@0.22.1` | 485 | io.github.Tlalvarez/auxiliar-mcp |
| 56 | `npm:http-inspector-mcp@1.0.0` | 451 | io.github.mrfentmen/http-inspector-mcp |
| 57 | `npm:nodebench-mcp@2.31.2` | 426 | io.github.HomenShum/nodebench |
| 58 | `npm:@helloaigent-dev/subscriber@0.2.1` | 419 | io.github.helloaigent-dev/helloaigent-subscriber |
| 59 | `npm:@scrapio/mcp@1.10.0` | 406 | io.github.xsronhou/scrapio-mcp |
| 60 | `npm:camoufox-mcp@1.0.0` | 375 | io.github.baixianger/camoufox-mcp |
| 61 | `npm:gate402-mcp@0.8.1` | 374 | io.github.pgalyen1987/gate402-mcp |
| 62 | `npm:@apollo_ai/mcp-proxy@4.8.1` | 369 | team.apolloai/intelligence |
| 63 | `npm:@reneturcios/pageport@0.1.0` | 365 | io.github.CloudCorpRecords/pageport |
| 64 | `npm:@reneturcios/feedport@0.1.0` | 364 | io.github.CloudCorpRecords/feedport |
| 65 | `npm:litescrape-mcp-server@0.2.0` | 359 | com.litescrape/litescrape-mcp-server |
| 66 | `npm:@agentmanifest/mcp-server@0.1.5` | 357 | com.agent-manifest/amp-mcp |
| 67 | `npm:@munition/mcp@0.0.16` | 341 | io.github.benjammartin/munition |
| 68 | `npm:mcp-server-scraper@1.0.1` | 326 | io.github.ofershap/scraper |
| 69 | `npm:twittertools-mcp@1.2.2` | 323 | io.github.steley/twittertools-mcp |
| 70 | `npm:@iliasabk/geolint@0.4.0` | 321 | io.github.iliasabk/geolint |
| 71 | `npm:@readystack/robots-txt-ai-crawler-audit@0.1.3` | 321 | io.github.jmshinhwa/robots-txt-ai-crawler-audit |
| 72 | `npm:pokeapi-mcp-server@1.12.0` | 318 | io.github.Asthanaji05/pokeapi-mcp-server |
| 73 | `npm:@readystack/tdm-reservation-lint@1.0.5` | 305 | io.github.jmshinhwa/tdm-reservation-lint |
| 74 | `npm:@idleprotocol/mcp@1.0.1` | 303 | com.earnidle/mcp |
| 75 | `npm:crixin@0.7.2` | 303 | com.crixin/voice |
| 76 | `npm:ai-daily-insights-mcp@0.5.0` | 292 | io.github.WhaleCupl/ai-daily-insights-mcp |
| 77 | `npm:web-tools-mcp@1.3.0` | 291 | io.github.mlawsonking/web-tools-mcp |
| 78 | `npm:@bitbooth/mcp-fetch@2.3.1` | 287 | io.github.Drock91/bitbooth-fetch |
| 79 | `npm:codewiki-mcp@1.1.1` | 283 | io.github.izzzzzi/codewiki-mcp |
| 80 | `npm:deep-research-mcp-server@1.0.2` | 267 | io.github.Perufitlife/deep-research-mcp-server |
| 81 | `npm:@sylphx/lookout@0.3.3` | 266 | io.github.SylphxAI/lookout |
| 82 | `npm:@mrfentmen/wikipedia-mcp@1.0.0` | 262 | io.github.mrfentmen/wikipedia-mcp |
| 83 | `npm:maxaeo-ai-visibility-mcp@0.4.0` | 262 | io.github.maxaeo/maxaeo-ai-visibility-mcp |
| 84 | `npm:anyapi-mcp@0.1.5` | 258 | io.github.getanyapi-com/anyapi |
| 85 | `npm:defuddle-fetch-mcp-server@1.0.4` | 257 | io.github.domdomegg/defuddle-fetch-mcp-server |
| 86 | `npm:netlens-mcp@0.2.3` | 250 | io.github.pzalutski-pixel/netlens |
| 87 | `npm:kitbag-mcp@1.1.2` | 246 | io.github.syedtaj7/kitbag-mcp |
| 88 | `npm:@ioserviceslabs/searchio-mcp@0.1.1` | 245 | io.github.IOServicesLabs/searchio |
| 89 | `npm:searxng-deepdive@0.4.1` | 240 | io.github.burakaydinofficial/searxng-deepdive |
| 90 | `npm:@three-ws/loom-mcp@0.1.3` | 235 | io.github.nirholas/loom-mcp |
| 91 | `npm:webbersites-x402-mcp@0.3.0` | 228 | io.github.webberdesign/webbersites-x402-mcp |
| 92 | `npm:@gera-services/mcp-gerapodcast@0.1.1` | 225 | io.github.geraservicesuk/mcp-gerapodcast |
| 93 | `npm:@firsthandapi/mcp-server@0.3.1` | 224 | com.firsthandapi/mcp-server |
| 94 | `npm:@swins/vault-knowledge-mcp@0.1.0` | 215 | com.seanwinslow/vault-knowledge |
| 95 | `npm:geo-tool-check@1.0.1` | 214 | io.github.shufflethis/geo-tool-check |
| 96 | `npm:@molpha/mcp@0.1.2` | 213 | io.github.molpha/mcp |
| 97 | `npm:tolca-mcp@1.0.0` | 212 | io.github.yayabough/tolca |
| 98 | `npm:@bitofacoder/omni-mcp-server@1.1.1` | 210 | io.github.bitofacoder/omni-mcp-server |
| 99 | `npm:@mrfentmen/pubmed-mcp@1.1.0` | 210 | io.github.mrfentmen/pubmed-mcp |
| 100 | `npm:sovereign-web-scraper-mcp@1.0.0` | 210 | io.github.ryudi84/web-scraper |
| 101 | `npm:seo-backlinks-mcp@0.1.2` | 208 | io.github.mouhabmzibra-rgb/seo-backlinks |
| 102 | `npm:@labtoolsstudio/fetchmcp@0.1.1` | 207 | io.github.labtools-studio/fetchmcp |
| 103 | `npm:rechtspraak-mcp@0.1.1` | 206 | io.github.Prudai/rechtspraak-mcp |
| 104 | `npm:obscura-mcp@0.1.1` | 204 | io.github.Metadrama/obscura-mcp |
| 105 | `npm:regionfetch-mcp@0.1.1` | 204 | dev.regionfetch/mcp |
| 106 | `npm:thecrawler@0.5.8` | 204 | io.github.manchittlab/thecrawler |
| 107 | `npm:@evidinvest/aether-mcp@0.3.3` | 203 | io.github.EvidInvest/aether-developer |
| 108 | `npm:l402-search-mcp@0.1.0` | 201 | io.github.llmops-pro/l402-search-mcp |
| 109 | `npm:mcp-retriever@0.0.24` | 199 | io.github.keiranhaax/mcp-retriever |
| 110 | `npm:webrecipe@0.1.5` | 199 | io.github.Pillsoon/webrecipe |
| 111 | `npm:@forum-labs/payfetch@1.0.0` | 196 | io.github.forum-labs/payfetch |
| 112 | `npm:sylex-search@0.1.2` | 195 | io.github.MastadoonPrime/sylex-search |
| 113 | `npm:@codeagentjp/egov-law-mcp@0.1.1` | 185 | io.github.SHAYOUWORLD/egov-law-mcp |
| 114 | `npm:cvjson-mcp@1.1.1` | 183 | io.github.freecvorg/cvjson |
| 115 | `npm:@nor-data/statfin-mcp@0.1.0` | 182 | io.github.3121n/statfin-mcp |
| 116 | `npm:@infoinlet/mcp-browser-research@0.1.1` | 180 | io.github.infoinlet-marketplace/mcp-browser-research |
| 117 | `npm:geo-inspector-mcp@0.1.2` | 179 | io.github.Bigsupe55/geo-inspector-mcp |
| 118 | `npm:quran-search-engine-mcp@0.2.1` | 179 | io.github.adelpro/quran-search-engine-mcp |
| 119 | `npm:data-aggregator-mcp@1.1.4` | 176 | io.github.vpatser1/data-aggregator-mcp |
| 120 | `npm:secret-design-mcp@0.6.0` | 174 | io.github.yyeongjin/secret-mcp |
| 121 | `npm:@robot-resources/scraper-mcp@0.1.2` | 173 | io.github.robot-resources/scraper |
| 122 | `npm:aeo-mcp@1.0.1` | 172 | io.github.arthurcarlsonn/aeo-mcp |
| 123 | `npm:witnessd-mcp@0.1.1` | 167 | vip.witnessd/witnessd |
| 124 | `npm:iteratools-mcp@1.0.5` | 166 | io.github.fredpsantos33/iteratools |
| 125 | `npm:@infoinlet/mcp-s3@0.1.1` | 165 | io.github.infoinlet-marketplace/mcp-s3 |
| 126 | `npm:ilo415-research-mcp@1.1.0` | 159 | io.github.ilo415/research |
| 127 | `npm:@evocrawl/evocrawl-mcp@4.0.1` | 158 | io.github.superaihuman/evocrawl-mcp |
| 128 | `npm:@infoinlet/mcp-fetch@0.1.1` | 158 | io.github.infoinlet-marketplace/mcp-fetch |
| 129 | `npm:@rileycraig/agent-toolbelt@2.0.2` | 158 | io.github.rccola990-cloud/agent-toolbelt |
| 130 | `npm:robotstxt-ai-mcp@1.0.1` | 158 | io.github.sharozdawa/robotstxt-ai |
| 131 | `npm:aifeed-mcp-server@1.0.0-draft.2` | 156 | io.github.denyn1/aifeed-mcp-server |
| 132 | `npm:@rog0x/mcp-web-tools@1.0.1` | 155 | io.github.rog0x/web |
| 133 | `npm:fetch-price@1.0.2` | 154 | io.github.fusionx212/fetch-price |
| 134 | `npm:@mukundakatta/html-to-markdown-mcp@0.1.0` | 151 | io.github.MukundaKatta/html-to-markdown-mcp |
| 135 | `npm:tweetsave-mcp@1.0.3` | 148 | io.github.zezeron/tweetsave-mcp |
| 136 | `npm:feed-reader-mcp@0.1.0` | 145 | io.github.tono628develop/feed-reader |
| 137 | `npm:@erikirby/web-network-tools@1.0.0` | 131 | io.github.erikirby/web-network-tools |
| 138 | `npm:telegram-channel-scraper-mcp-server@1.0.1` | 0 | io.github.khadinakbaronline/telegram-channel-scraper-mcp |
| 139 | `npm:@veilquota/mcp@0.3.0` | -1 | io.github.omkardongre/veilquota |
| 140 | `pypi:agentfetch-mcp@1.0.1` | pypi | io.github.bch1212/agentfetch |
| 141 | `pypi:ai-first-scraper-mcp@1.0.2` | pypi | io.github.yubinkim444/ai-first-scraper-mcp |
| 142 | `pypi:bing-webmaster-mcp@0.1.3` | pypi | io.github.surendranb/bing-webmaster-mcp |
| 143 | `pypi:cluefinch@0.1.4` | pypi | io.github.cluefinch/mcp |
| 144 | `pypi:cn-scraper-mcp@0.4.1` | pypi | io.github.goesByhc/cn-scraper-mcp |
| 145 | `pypi:crawleyes@0.2.0` | pypi | io.github.waiky-github/CrawlEyes |
| 146 | `pypi:delhaize-mcp@0.1.0` | pypi | io.github.SHIMABEIGI/delhaize-mcp |
| 147 | `pypi:fetchv2-mcp-server@2.0.0` | pypi | io.github.praveenc/fetchv2-mcp-server |
| 148 | `pypi:hkex-filing-scraper@2.4.3` | pypi | com.ascent-partners/hkex-filings |
| 149 | `pypi:huoshui-fetch@1.0.0` | pypi | io.github.huoshuiai42/huoshui-fetch |
| 150 | `pypi:jp-eli-mcp@0.3.3` | pypi | io.github.matematicsolutions/jp-eli-mcp |
| 151 | `pypi:kiprio-mcp@0.6.0` | pypi | com.kiprio/kiprio-mcp |
| 152 | `pypi:mcp-bing-scraper@0.2.0` | pypi | io.github.iridite/bing-search-free |
| 153 | `pypi:mcp-exa@0.1.1` | pypi | io.github.daedalus/mcp-exa |
| 154 | `pypi:mcp-job-search-mp@0.2.0` | pypi | io.github.michalper/mcp-job-search |
| 155 | `pypi:mcp-search-server@0.1.1` | pypi | io.github.KazKozDev/search |
| 156 | `pypi:mcp-webgate@0.1.31` | pypi | io.github.annibale-x/mcp-webgate |
| 157 | `pypi:mcp-webgate@0.1.33` | pypi | io.github.x-hannibal/mcp-webgate |
| 158 | `pypi:mcp-webgate@0.1.32` | pypi | io.github.x-monk/mcp-webgate |
| 159 | `pypi:mcparmory-apify@1.0.5` | pypi | com.mcparmory/apify |
| 160 | `pypi:mcparmory-firecrawl@1.0.3` | pypi | com.mcparmory/firecrawl |
| 161 | `pypi:mcparmory-google-search@1.0.2` | pypi | com.mcparmory/google-search |
| 162 | `pypi:mcparmory-linkup@1.0.2` | pypi | com.mcparmory/linkup |
| 163 | `pypi:mcparmory-scrapingant@1.0.1` | pypi | com.mcparmory/scrapingant |
| 164 | `pypi:mcpsurfr@1.2.3` | pypi | io.github.nkapila6/mcpsurfr |
| 165 | `pypi:my-eli-mcp@0.3.3` | pypi | io.github.matematicsolutions/my-eli-mcp |
| 166 | `pypi:oxylabs-mcp@0.10.2` | pypi | io.oxylabs/oxylabs-mcp |
| 167 | `pypi:polish-archives-mcp@0.1.1` | pypi | io.github.ianderso/polish-archives-mcp |
| 168 | `pypi:pyrecrawl@0.8.1` | pypi | io.github.SanggonBoy/PyreCrawl |
| 169 | `pypi:pyscrappy@1.5.9` | pypi | io.github.mldsveda/pyscrappy |
| 170 | `pypi:ragstack-mcp@0.1.4` | pypi | io.github.HatmanStack/ragstack |
| 171 | `pypi:scrapegraph-mcp@1.0.1` | pypi | io.github.ScrapeGraphAI/scrapegraph-mcp |
| 172 | `pypi:searxncrawl@0.33.1` | pypi | io.github.DasDigitaleMomentum/searxncrawl |
| 173 | `pypi:searxng@0.1.2` | pypi | io.github.danchev/searxng |
| 174 | `pypi:sentinelseo@1.0.0` | pypi | io.github.IliasSami/scrawly |
| 175 | `pypi:sg-eli-mcp@0.3.3` | pypi | io.github.matematicsolutions/sg-eli-mcp |
| 176 | `pypi:shortsmash@0.3.0` | pypi | io.github.hydope/shortsmash |
| 177 | `pypi:siftdog@0.3.0` | pypi | io.github.khsarvar/siftdog |
| 178 | `pypi:skdev-websearch-mcp@1.10.0` | pypi | io.github.SK-DEV-AI/websearch |
| 179 | `pypi:thealgorithms-mcp@0.3.1` | pypi | io.github.mcande21/thealgorithms-mcp |
| 180 | `pypi:tilion@0.1.3` | pypi | io.github.tiliondev/fortress |
| 181 | `pypi:trackman-mcp@0.4.0` | pypi | io.github.bjornj12/trackman-mcp |
| 182 | `pypi:vexor@0.31.0` | pypi | io.github.scarletkc/vexor |
| 183 | `pypi:videoctx@0.1.5` | pypi | io.github.dunfred/videoctx |
| 184 | `pypi:wayforth-mcp@0.1.3` | pypi | io.github.WayforthOfficial/wayforth |
| 185 | `pypi:web-research-mcp@1.0.8` | pypi | io.github.CSOAI-ORG/web-research-mcp |
| 186 | `pypi:webfetch-llm@0.1.3` | pypi | io.github.firish/webfetch |
| 187 | `pypi:websearch-skill@0.2.6` | pypi | io.github.hec-ovi/web-search |
| 188 | `pypi:whipscribe-mcp@0.1.5` | pypi | io.github.neugence/whipscribe-mcp |

</details>

<details><summary>file: 589 candidates</summary>

| # | package | downloads | registry name |
|---|---|---|---|
| 1 | `npm:emailmd@0.13.2` | 19455 | dev.emailmd/emailmd |
| 2 | `npm:@adeu/mcp-server@1.7.1` | 4969 | ai.adeu/adeu |
| 3 | `npm:@mcp-z/mcp-pdf@1.0.3` | 4222 | io.github.kmalakoff/mcp-pdf |
| 4 | `npm:@mcp-z/mcp-pdf@3.4.0` | 4222 | io.github.mcp-z/mcp-pdf |
| 5 | `npm:@guardbee/mcp-secret-scanner@0.2.10` | 3693 | io.github.4hmetuyar/secret-scanner |
| 6 | `npm:tabellio@0.1.12` | 2932 | io.github.yffo/tabellio |
| 7 | `npm:@guardbee/mcp-model-scanner@0.1.2` | 2137 | io.github.4hmetuyar/model-scanner |
| 8 | `npm:@pressa/mcp@0.11.4` | 1876 | io.github.pressa-dev/pressa |
| 9 | `npm:jotview@0.7.0` | 1866 | io.github.jotbins/jotview |
| 10 | `npm:rowsmith-mcp@0.5.0` | 1809 | io.github.meiorz/rowsmith |
| 11 | `npm:@ostico/bruno-mcp@2.5.0` | 1620 | io.github.Ostico/bruno-mcp-studio |
| 12 | `npm:word-to-markdown@0.9.0` | 1439 | io.github.benbalter/word-to-markdown |
| 13 | `npm:gridpath@0.5.0` | 1426 | io.github.pixelsmasher13/gridpath |
| 14 | `npm:ezpzfile-mcp@0.3.3` | 1420 | io.github.ezpzfile/ezpzfile |
| 15 | `npm:showboard@0.4.1` | 1411 | io.github.rohanbeingsocial/showboard |
| 16 | `npm:vecline@2.1.4` | 1390 | io.github.shunyagatha/vecline |
| 17 | `npm:@contextfetch/mcp@1.1.0` | 1384 | dev.contextfetch/mcp |
| 18 | `npm:dejared-mcp@1.0.0` | 1306 | io.github.HuynhKhanh1402/dejared |
| 19 | `npm:@mdedit/mcp-server@0.3.4` | 1296 | io.github.mangoappstudio/mdedit |
| 20 | `npm:@ariferol01/tuval-studio-mcp@1.0.7` | 1294 | io.github.ariferol01/tuval-studio |
| 21 | `npm:@stratta/mcp@1.20.1` | 1282 | ch.stratta/mcp |
| 22 | `npm:sealnet-mcp@0.11.2` | 1282 | net.seal/mcp |
| 23 | `npm:@eurafaeldecarvalho/browser-scraper@0.8.3` | 1271 | io.github.eurafaeldecarvalho/browser-scraper |
| 24 | `npm:@cyanheads/stackexchange-mcp-server@0.2.0` | 1171 | io.github.cyanheads/stackexchange-mcp-server |
| 25 | `npm:@diagrams-so/mcp@1.4.7` | 1121 | io.github.RedHold/diagrams-so-mcp |
| 26 | `npm:doc2video@0.2.3` | 1120 | io.github.doc2video/d2v |
| 27 | `npm:@chrischall/skill-mcp@1.2.3` | 1119 | io.github.chrischall/skill-mcp |
| 28 | `npm:@gpambrozio/onshape-mcp@0.3.0` | 1103 | io.github.gpambrozio/onshape |
| 29 | `npm:vortex-notes@0.1.11` | 1090 | io.github.vortex-303/vortex-notes |
| 30 | `npm:webpeel@0.3.0` | 1068 | io.github.JakeLiuMe/webpeel |
| 31 | `npm:adobe-mcp-indesign@2.5.0` | 1034 | io.github.zachshallbetter/adobe-mcp-indesign |
| 32 | `npm:@mrfentmen/csv-mcp@1.0.1` | 1020 | io.github.mrfentmen/csv-mcp |
| 33 | `npm:@validatefin/mcp@1.2.1` | 1002 | io.github.elnicaise/validatefin |
| 34 | `npm:cuecaps-mcp@0.1.2` | 1000 | io.github.Pantheonn3D/cuecaps-mcp |
| 35 | `npm:apick-subagent@1.0.5` | 995 | app.apick/subagent |
| 36 | `npm:companies-house-mcp@4.0.1` | 966 | io.github.aicayzer/companies-house |
| 37 | `npm:boxpdf@1.0.3` | 959 | io.github.earonesty/boxpdf |
| 38 | `npm:@mrfentmen/document-generator-mcp@1.0.1` | 944 | io.github.mrfentmen/document-generator-mcp |
| 39 | `npm:lovemarkdown-mcp@1.0.2` | 922 | io.github.coolnico/lovemarkdown-mcp |
| 40 | `npm:app-ionelul-mcp@0.12.0` | 916 | com.ionelul/app |
| 41 | `npm:@cyanheads/sweden-parliament-mcp-server@0.1.2` | 897 | io.github.cyanheads/sweden-parliament-mcp-server |
| 42 | `npm:local-skills-mcp@0.2.1` | 891 | io.github.rkdpa/local-skills-mcp |
| 43 | `npm:@mrfentmen/diff-mcp@1.0.1` | 875 | io.github.mrfentmen/diff-mcp |
| 44 | `npm:numbers-le-mcp@2.8.0` | 870 | io.github.nolindnaidoo/numbers-le |
| 45 | `npm:kybase-mcp@0.2.4` | 867 | io.github.Kyrzin/kybase |
| 46 | `npm:@sheetsmcp/server@1.4.0` | 862 | io.github.atc07/sheets-mcp |
| 47 | `npm:@anthony-maio/cartograph@1.3.0` | 855 | io.github.anthony-maio/cartograph |
| 48 | `npm:lakeboard-converter@0.5.0` | 845 | io.github.FelixFangX/lakeboard-converter |
| 49 | `npm:@xultrax-web/agent-memory-mcp@0.15.0` | 839 | io.github.xultrax-web/agent-memory-mcp |
| 50 | `npm:documenso-mcp@1.0.0` | 829 | io.github.mrfentmen/documenso-mcp |
| 51 | `npm:handinloop-mcp-server@0.9.1` | 825 | io.github.handinloop/handinloop-mcp-server |
| 52 | `npm:handinloop-mcp-server@0.5.0` | 825 | io.github.lesofi/handinloop-mcp-server |
| 53 | `npm:envsync-le-mcp@2.5.0` | 820 | io.github.nolindnaidoo/envsync-le |
| 54 | `npm:@j0hanz/fetch-url-mcp@3.0.1` | 815 | io.github.j0hanz/fetch-url-mcp |
| 55 | `npm:ellmos-filecommander-mcp@1.11.4` | 812 | io.github.ellmos-ai/ellmos-filecommander-mcp |
| 56 | `npm:@dravensoft/arena-mcp@13.0.0` | 803 | io.github.dravensoft-dev/arena |
| 57 | `npm:docspell-mcp@1.0.0` | 802 | io.github.mrfentmen/docspell-mcp |
| 58 | `npm:@mrfentmen/pinata-mcp@1.0.2` | 792 | io.github.mrfentmen/pinata-mcp |
| 59 | `npm:@us-all/android-mcp@1.14.4` | 789 | io.github.us-all/android |
| 60 | `npm:chmi-mcp@1.0.0` | 781 | io.github.mrfentmen/chmi-mcp |
| 61 | `npm:figme-mcp@1.1.1` | 762 | io.github.ntson9p/figme-mcp |
| 62 | `npm:@eiler2005/slidecraft@0.7.7` | 755 | io.github.eiler2005/slidecraft |
| 63 | `npm:intercept-mcp@3.0.8` | 750 | io.github.bighippoman/intercept-mcp |
| 64 | `npm:@mrfentmen/federal-register-mcp@1.0.1` | 749 | io.github.mrfentmen/federal-register-mcp |
| 65 | `npm:@abhishekmcp/notes@0.4.1` | 738 | io.github.Abhishekkumar2021/notes |
| 66 | `npm:@apireno/domshell@2.0.10` | 735 | io.github.apireno/domshell |
| 67 | `npm:@mrfentmen/jsondiff-mcp@1.0.1` | 734 | io.github.mrfentmen/jsondiff-mcp |
| 68 | `npm:esm-mcp@1.0.1` | 727 | io.github.mrfentmen/esm-mcp |
| 69 | `npm:@ojodotso/mcp-server@0.9.0` | 718 | so.ojo/mcp-server |
| 70 | `npm:@andrea9293/mcp-documentation-server@1.15.3` | 713 | io.github.andrea9293/mcp-documentation-server |
| 71 | `npm:samsung-health-mcp-unofficial@0.5.0` | 711 | io.github.davidmosiah/samsung-health-mcp |
| 72 | `npm:argosor-mcp@1.0.1` | 710 | com.argosor/mcp |
| 73 | `npm:@contentasoft/contenta-photo-converter-mcp@1.0.4` | 709 | com.contenta-software/contenta-photo-converter |
| 74 | `npm:@appmonster/mcp-hwp@0.1.1` | 708 | io.github.groove79/mcp-hwp |
| 75 | `npm:ato-mcp@2.3.0` | 700 | au.com.ato-mcp/ato-mcp |
| 76 | `npm:@mrfentmen/excel-mcp@1.0.1` | 697 | io.github.mrfentmen/excel-mcp |
| 77 | `npm:@page-scanner/mcp@0.4.5` | 687 | io.github.sbd530/page-scanner |
| 78 | `npm:@mrfentmen/ical-mcp@1.0.1` | 669 | io.github.mrfentmen/ical-mcp |
| 79 | `npm:@aspicio/mcp@0.13.2` | 657 | io.github.frontsail-ai/aspicio |
| 80 | `npm:@curtisai/mcp@0.1.1` | 653 | io.github.JordanNewell/curtis-mcp |
| 81 | `npm:boxpdf-html@1.7.0` | 653 | io.github.earonesty/boxpdf-html |
| 82 | `npm:visimark-mcp@0.4.1` | 652 | io.github.michal-niedzwiedzki/visimark |
| 83 | `npm:zas-agent@0.12.0` | 647 | io.github.soke1556/zas-agent |
| 84 | `npm:adobe-commerce-mcp@0.1.0` | 642 | io.github.zeluizr/adobe-commerce-mcp |
| 85 | `npm:string-le-mcp@2.5.1` | 639 | io.github.nolindnaidoo/string-le |
| 86 | `npm:sandboxer-mcp@0.1.0` | 616 | com.sandboxer/mcp |
| 87 | `npm:paths-le-mcp@2.4.1` | 591 | io.github.nolindnaidoo/paths-le |
| 88 | `npm:@optimalai/optibot-mcp@1.4.1` | 584 | ai.getoptimal/optibot |
| 89 | `npm:@virsanghavi/axis-server@1.14.2` | 573 | dev.useaxis/axis |
| 90 | `npm:@contentasoft/videorecompress-mcp@1.0.2` | 563 | com.contenta-software/videorecompress |
| 91 | `npm:@dmytro-prototypes/cadbridge-mcp@0.1.15` | 561 | net.dmytro-prototypes/cadbridge-mcp-autocad |
| 92 | `npm:dates-le-mcp@2.5.0` | 553 | io.github.nolindnaidoo/dates-le |
| 93 | `npm:one-design-mcp@0.2.4` | 551 | io.github.axworks1/one-design |
| 94 | `npm:cohort-mcp@0.1.0` | 550 | io.github.magnusmage/cohort-mcp |
| 95 | `npm:@community-access/accessibility-agents-mcp@7.1.0` | 547 | io.github.Community-Access/accessibility-agents |
| 96 | `npm:papyrio-mcp@0.1.4` | 544 | io.github.atabekdemurtaza/papyrio-mcp |
| 97 | `npm:jh-presentation@0.9.0` | 534 | io.github.pei-jz/jh-presentation |
| 98 | `npm:@207studio/pptx-mcp@0.1.0` | 524 | io.github.207studio/pptx-mcp |
| 99 | `npm:ai-context-kit@0.1.2` | 521 | io.github.ofershap/ai-context-kit |
| 100 | `npm:@korala/mcp@0.9.0` | 519 | ai.korala/mcp |
| 101 | `npm:@getpopapi/pop-mcp@2.1.0` | 504 | io.github.popapidev/pop-mcp |
| 102 | `npm:@robthepcguy/rag-vault@1.5.3` | 503 | io.github.RobThePCGuy/rag-vault |
| 103 | `npm:openreadout@0.4.0` | 501 | io.github.openreadout/openreadout |
| 104 | `npm:@aryanbv/pdf-toolkit-mcp@0.3.1` | 499 | io.github.AryanBV/pdf-toolkit-mcp |
| 105 | `npm:ics-generator-mcp@1.0.0` | 491 | io.github.mrfentmen/ics-generator-mcp |
| 106 | `npm:@contentasoft/cad-converter-mcp@1.0.2` | 489 | com.contenta-software/cad-converter |
| 107 | `npm:docraptor-mcp@1.0.0` | 489 | io.github.mrfentmen/docraptor-mcp |
| 108 | `npm:filesystem-mcp@1.3.0` | 484 | io.github.domdomegg/filesystem-mcp |
| 109 | `npm:@spideriq/mcp-media@1.1.0` | 469 | ai.spideriq/media |
| 110 | `npm:coolftp@0.1.4` | 469 | io.github.anivdel/coolftp |
| 111 | `npm:@briefgate/mcp@0.10.7` | 462 | io.github.sekera-radim/briefgate |
| 112 | `npm:@hypawave/mcp@0.6.1` | 461 | io.github.hypawave/mcp |
| 113 | `npm:agent-skill-loader@1.2.1` | 458 | io.github.back1ply/agent-skill-loader |
| 114 | `npm:@commenteme/adobe-commerce-mcp@0.2.0` | 456 | io.github.commentemeapp/adobe-commerce-mcp |
| 115 | `npm:@opsmaxx/mcp@0.1.3` | 456 | io.github.OpsMaxx/opsmaxx |
| 116 | `npm:markdown-to-whatsapp@1.0.3` | 434 | io.github.drsound/markdown-to-whatsapp |
| 117 | `npm:@levnikolaevich/hex-ssh-mcp@1.9.2` | 433 | io.github.levnikolaevich/hex-ssh-mcp |
| 118 | `npm:@readystack/base-image-eol-lint@0.1.1` | 433 | io.github.jmshinhwa/base-image-eol-lint |
| 119 | `npm:mneme-mcp-server@4.1.0` | 425 | io.github.OnourImpram/mneme |
| 120 | `npm:mneme-mcp-server@3.5.0` | 425 | io.github.TheGoatPsy/mneme |
| 121 | `npm:knmi-mcp@1.0.0` | 422 | io.github.mrfentmen/knmi-mcp |
| 122 | `npm:@xchucx/agent-memory@0.6.1` | 420 | io.github.xChuCx/agent-memory |
| 123 | `npm:@mybestie/check@0.3.0` | 417 | io.github.HireBestie/bestie-check |
| 124 | `npm:lassocut-mcp@1.1.0` | 417 | io.github.jaupin94/lassocut-mcp |
| 125 | `npm:mcp-server-markview@1.7.2` | 414 | io.github.paulhkang94/markview |
| 126 | `npm:olkcli@1.16.1` | 414 | io.github.rlrghb/outlook |
| 127 | `npm:visus-mcp@0.13.0` | 414 | io.github.visus-mcp/visus-mcp |
| 128 | `npm:@reneturcios/npmpreflight@0.1.0` | 412 | io.github.CloudCorpRecords/npmpreflight |
| 129 | `npm:spoken-mcp@0.4.3` | 412 | io.github.spokenmd/spoken |
| 130 | `npm:aigroup-mdtoword-mcp@4.0.2` | 404 | io.github.jackdark425/aigroup-mdtoword-mcp |
| 131 | `npm:@appmonster/mcp-ofd@0.1.0` | 403 | io.github.groove79/mcp-ofd |
| 132 | `npm:xlsx-audit-mcp@0.1.0` | 403 | io.github.arose26/xlsx-audit-mcp |
| 133 | `npm:glashaus-mcp@0.4.41` | 399 | io.github.addiinnocent/glashaus-mcp |
| 134 | `npm:@parryhotter/office-mcp@0.10.2` | 398 | io.github.gauravvvvvvvvvv/office-mcp |
| 135 | `npm:@mindstone/mcp-server-replit-ssh@0.2.2` | 395 | io.github.mindstone/mcp-server-replit-ssh |
| 136 | `npm:google-search-console-connector@0.1.3` | 393 | io.github.malaysherasia-ai/google-search-console-connector |
| 137 | `npm:@shieldfive/mcp@0.7.1` | 381 | io.github.shieldfive/mcp |
| 138 | `npm:lupa-mcp@0.2.0` | 379 | io.github.paeyoungpark-web/lupa-mcp |
| 139 | `npm:lupa-mcp@0.3.1` | 379 | io.github.under71/lupa-mcp |
| 140 | `npm:@sunsato/vulcanus@0.6.3` | 378 | io.github.sunsatosolutions/vulcanus |
| 141 | `npm:@zenitheditor/zenith-mcp@0.0.8` | 377 | io.github.zenitheditor/zenith |
| 142 | `npm:@shipi18n/mcp@2.3.2` | 376 | io.github.Shipi18n/shipi18n |
| 143 | `npm:compendio-mcp@1.7.2` | 376 | io.github.RuloGB/compendio-mcp |
| 144 | `npm:@memofs/mcp-server@1.3.0-beta.3` | 372 | dev.memofs/mcp-server |
| 145 | `npm:@mycobrain/mcp-server@1.3.0` | 370 | io.github.thegoodguysla/myco-brain |
| 146 | `npm:@reneturcios/pageport@0.1.0` | 365 | io.github.CloudCorpRecords/pageport |
| 147 | `npm:@vk0/agent-claim-mcp@1.0.2` | 365 | io.github.vk0dev/agent-claim-mcp |
| 148 | `npm:pdfkit-mcp@1.0.7` | 362 | com.hellobasestation/pdfkit |
| 149 | `npm:pdfkit-mcp@1.0.2` | 362 | io.github.benhuang21828/pdfkit |
| 150 | `npm:@mnemodb/mcp@0.1.22` | 359 | dev.mnemodb/mnemodb |
| 151 | `npm:@three-ws/blender-mcp@0.5.0` | 359 | io.github.nirholas/blender-mcp |
| 152 | `npm:@tomd4vs/prumo@0.9.7` | 359 | io.github.TomD4vs/prumo |
| 153 | `npm:@truepathpdf/mcp-server@0.3.0` | 358 | io.github.JoyTruepath/truepath-pdf-mcp |
| 154 | `npm:girder-mcp@0.4.0` | 353 | io.github.dhishwasher/girder |
| 155 | `npm:csvto-mcp@0.1.2` | 351 | io.github.Bishop81/csvto-mcp |
| 156 | `npm:margins-mcp@0.15.3` | 351 | io.github.cflorczyk9/margins |
| 157 | `npm:mcp-server-markdown@1.0.1` | 351 | io.github.ofershap/markdown |
| 158 | `npm:@readystack/firebase-deploy-leak-audit@1.0.5` | 346 | io.github.jmshinhwa/firebase-deploy-leak-audit |
| 159 | `npm:yaktool-pdf-mcp@0.7.0` | 346 | com.yaktool/pdf |
| 160 | `npm:@attestwire/mcp@1.2.2` | 343 | com.attestwire/en16931 |
| 161 | `npm:feishu-markdown-mcp@0.1.3` | 342 | io.github.huandu/feishu-markdown-mcp |
| 162 | `npm:@munition/mcp@0.0.16` | 341 | io.github.benjammartin/munition |
| 163 | `npm:@averra/extract-mcp@0.1.5` | 340 | dev.averra/extract |
| 164 | `npm:@polyxd/mcp@0.4.6` | 338 | com.polyxd/mcp |
| 165 | `npm:tamperlens-mcp@1.43.0` | 338 | com.tamperlens/mcp |
| 166 | `npm:@dockndevai/mcp-outlook@0.4.1` | 337 | io.github.dockndevai/mcp-outlook |
| 167 | `npm:@kitewright/mcp@0.1.1` | 337 | io.github.kitewright/mcp |
| 168 | `npm:neurostack@0.12.0` | 335 | io.github.raphasouthall/neurostack |
| 169 | `npm:magictex-mcp@0.1.10` | 331 | io.github.ZoeLinUTS/magictex |
| 170 | `npm:@bzdos/hubd@0.4.2` | 329 | io.github.bzdOS/hubd |
| 171 | `npm:@exactpdf/mcp@0.2.19` | 328 | com.exactpdf/mcp |
| 172 | `npm:@readystack/green-claim-lint-empco@1.0.4` | 326 | io.github.jmshinhwa/green-claim-lint-empco |
| 173 | `npm:mcp-server-scraper@1.0.1` | 326 | io.github.ofershap/scraper |
| 174 | `npm:@n0zer0d4y/vulcan-file-ops@1.3.0` | 324 | io.github.n0zer0d4y/vulcan-file-ops |
| 175 | `npm:@vrun-design/openflowkit-mcp@0.2.1` | 324 | io.github.Vrun-design/openflowkit-mcp |
| 176 | `npm:reportflow-mcp@1.4.0` | 322 | io.github.re-port-flow/reportflow-mcp |
| 177 | `npm:turnback@0.9.1` | 322 | io.github.MFaizR77/turnback |
| 178 | `npm:@quario/mcp@0.3.0` | 320 | com.getquario/mcp |
| 179 | `npm:armadoc@0.2.1` | 320 | link.armadoc/armadoc |
| 180 | `npm:@readystack/verfahrensdoku-gobd-check@1.0.5` | 317 | io.github.jmshinhwa/verfahrensdoku-gobd-check |
| 181 | `npm:@thrain/blackout-mcp@1.3.0` | 316 | ai.thrain/blackout |
| 182 | `npm:ainative-prd-mcp@1.1.1` | 315 | io.github.AINative-Studio/ainative-prd-mcp |
| 183 | `npm:@dsbissett/excel-webview2-mcp@0.0.13` | 313 | io.github.dsbissett/excel-webview2-mcp |
| 184 | `npm:local-workspace-mcp@0.2.2` | 312 | io.github.peter4leadson/local-workspace-mcp |
| 185 | `npm:pdf-suite-mcp@2.1.1` | 312 | io.github.beepboop2025/pdf-toolkit-mcp |
| 186 | `npm:@readystack/svg-asset-compliance-lint@1.0.4` | 311 | io.github.jmshinhwa/svg-asset-compliance-lint |
| 187 | `npm:kiriya@0.3.0` | 311 | io.github.SatPaingOo/kiriya |
| 188 | `npm:@dmytro-prototypes/control-mcp-server@0.1.16` | 310 | net.dmytro-prototypes/control-mcp-server |
| 189 | `npm:@spazio-genesi/attest-mcp@0.4.1` | 309 | io.github.SPAZIO-GENESI/attest-mcp |
| 190 | `npm:@url2md-io/mcp@0.1.5` | 308 | io.url2md/mcp |
| 191 | `npm:adops-mcp-server@1.3.0` | 306 | io.github.enzoemir1/adops-mcp |
| 192 | `npm:qualien-mcp@0.6.2` | 304 | io.github.qualienai/qualien-mcp |
| 193 | `npm:@counterpoint-studio/audio-file-mcp-app@1.1.1` | 302 | io.github.counterpoint-studio/audio-file-mcp-app |
| 194 | `npm:statementsure-mcp@0.1.1` | 302 | com.statementsure/statementsure |
| 195 | `npm:@readystack/dora-register-lint@1.0.1` | 300 | io.github.jmshinhwa/dora-register-lint |
| 196 | `npm:invokeport-mcp@0.2.0` | 300 | io.github.gerefull/invokeport |
| 197 | `npm:skim-mcp@0.2.5` | 299 | io.github.JessieJanie/skim402 |
| 198 | `npm:salamailer@1.0.0` | 297 | fi.salamailer/salamailer |
| 199 | `npm:vibe-coding-mcp@2.12.1` | 297 | io.github.MUSE-CODE-SPACE/vibe-coding |
| 200 | `npm:@aimino/opendocswork-mcp@0.2.1` | 295 | io.github.Aimino-Tech/office-oxide-mcp |
| 201 | `npm:@readystack/jest-snapshot-pii-audit@1.0.2` | 293 | io.github.jmshinhwa/jest-snapshot-pii-audit |
| 202 | `npm:drawing-anonymizer-mcp@0.1.0` | 291 | com.imnoo/drawing-anonymizer |
| 203 | `npm:web-tools-mcp@1.3.0` | 291 | io.github.mlawsonking/web-tools-mcp |
| 204 | `npm:@noamjose/schemasure@0.4.0` | 289 | io.github.noamjose/schemasure |
| 205 | `npm:@readystack/dsfinv-k-export-lint@1.0.1` | 289 | io.github.jmshinhwa/dsfinv-k-export-lint |
| 206 | `npm:@readystack/config-dsl-lint-snippet-pack@0.1.4` | 288 | io.github.jmshinhwa/config-dsl-lint-snippet-pack |
| 207 | `npm:@theyahia/1c-rest-mcp@1.2.1` | 288 | io.github.theYahia/1c-rest-mcp |
| 208 | `npm:@dsbissett/office-addin-mcp@0.8.0` | 287 | io.github.dsbissett/office-addin-mcp |
| 209 | `npm:@pdfmakerapi/mcp@1.0.0` | 287 | io.github.GerardoBarrera/pdfmakerapi-mcp |
| 210 | `npm:logisheets-mcp@0.6.0` | 286 | io.github.logisky/logisheets-mcp |
| 211 | `npm:rangefind-mcp@0.3.2` | 286 | io.github.xjodoin/rangefind |
| 212 | `npm:@nogoo9/mcp-server-cloud-fs@0.7.0` | 285 | io.github.nogoo9/mcp-server-cloud-fs |
| 213 | `npm:pdfcrowd-mcp-pdf-export@1.2.2` | 282 | io.github.pdfcrowd/pdfcrowd-mcp-pdf-export |
| 214 | `npm:@readystack/eu-health-claim-lint@1.0.2` | 281 | io.github.jmshinhwa/eu-health-claim-lint |
| 215 | `npm:pdf-it-mcp@2.1.0` | 281 | io.github.mrslbt/pdf-it |
| 216 | `npm:@den.dance/network-diagram-mcp@1.0.7` | 279 | io.github.den-indance/network-diagram-mcp |
| 217 | `npm:@open-agreements/contract-templates-mcp@0.10.2` | 278 | io.github.open-agreements/open-agreements |
| 218 | `npm:dyer-md-mcp@2.1.1` | 278 | io.github.Srishesh-Archik/dyer-md |
| 219 | `npm:env-forge-mcp@1.0.1` | 277 | io.github.ryudi84/env-forge-mcp |
| 220 | `npm:@type-atlas/mcp@1.0.0` | 276 | io.github.tyler-mitchell/type-atlas |
| 221 | `npm:@domscout/mcp@1.0.8` | 275 | io.github.jkresearch8/domscout |
| 222 | `npm:@alipajand/agent-readiness-mcp@0.1.2` | 272 | io.github.alipajand/agent-readiness |
| 223 | `npm:sepa-validator-mcp@0.2.0` | 272 | io.github.wenboteng/sepa-validator |
| 224 | `npm:@readystack/vvt-pruefer-art-30-dsgvo@1.0.3` | 269 | io.github.jmshinhwa/vvt-pruefer-art-30-dsgvo |
| 225 | `npm:supernote-mcp@0.2.2` | 269 | io.github.ridget/supernote-mcp |
| 226 | `npm:rulestack-mcp@0.1.0` | 268 | tech.thecompound/rulestack |
| 227 | `npm:freethetools@0.1.2` | 265 | io.github.sapience-design/freethetools |
| 228 | `npm:haoyoubox-mcp@1.0.0` | 265 | com.haoyoubox/publish |
| 229 | `npm:ritoko@0.2.0` | 264 | io.github.Swih/ritoko |
| 230 | `npm:yaktool-mcp@0.4.2` | 263 | com.yaktool/yaktool |
| 231 | `npm:@xjtlumedia/markdown-mcp-server@1.0.5` | 258 | io.github.XJTLUmedia/markdown-formatter |
| 232 | `npm:opsecforge-mcp@0.1.1` | 255 | io.github.cyberdroid2077/opsecforge |
| 233 | `npm:msglens-cli@0.2.1` | 254 | io.github.AndyLiu0427/msglens |
| 234 | `npm:slideshot-mcp@4.4.0` | 254 | io.github.06ketan/slideshot |
| 235 | `npm:vrm-toolkit-mcp@0.1.1` | 254 | io.github.dwarehouse1/vrm-toolkit-mcp |
| 236 | `npm:@file-kiwi/filekiwi-mcp-server@1.0.10` | 253 | io.github.file-kiwi/filekiwi-mcp-server |
| 237 | `npm:@chartone/mcp@0.1.7` | 251 | io.github.zhugejun/chartone |
| 238 | `npm:netlens-mcp@0.2.3` | 250 | io.github.pzalutski-pixel/netlens |
| 239 | `npm:puzzletide-mcp@0.2.1` | 250 | io.github.catorch/puzzletide |
| 240 | `npm:test-coverage-mcp@1.1.0` | 250 | io.github.goldbergyoni/test-coverage-mcp |
| 241 | `npm:@waxseal/mcp@1.0.2` | 249 | io.github.degenlegion-com/waxseal |
| 242 | `npm:agent-data-api-mcp@1.0.1` | 249 | io.github.Ptrgit1/agent-data-api |
| 243 | `npm:whats-loaded-mcp@0.2.5` | 248 | io.github.stcmain/whats-loaded-mcp |
| 244 | `npm:readme-forge-mcp@1.0.1` | 247 | io.github.ryudi84/readme-forge-mcp |
| 245 | `npm:@dashboardbase/mcp@1.0.1` | 246 | com.dashboardbase/mcp |
| 246 | `npm:yaktool-labels-mcp@0.3.1` | 246 | com.yaktool/labels |
| 247 | `npm:memory-vault@0.5.0` | 244 | io.github.apurv101/memory-vault |
| 248 | `npm:@readystack/dividenden-quellensteuer-lint@1.0.1` | 243 | io.github.jmshinhwa/dividenden-quellensteuer-lint |
| 249 | `npm:postmd-mcp-server@2.6.1` | 243 | io.github.reinlainer/postmd-mcp-server |
| 250 | `npm:lorem-mcp@0.2.3` | 242 | io.github.AnkitaShanbhag30/lorem |
| 251 | `npm:markdown-forge-mcp@1.0.3` | 242 | io.github.ryudi84/markdown |
| 252 | `npm:markdown-forge-mcp@1.0.1` | 242 | io.github.ryudi84/markdown-forge-mcp |
| 253 | `npm:ms-sharepoint-mcp@1.0.1` | 240 | io.github.0xka13b/ms-sharepoint-mcp |
| 254 | `npm:searxng-deepdive@0.4.1` | 240 | io.github.burakaydinofficial/searxng-deepdive |
| 255 | `npm:@abhishekmcp/github@0.2.0` | 237 | io.github.Abhishekkumar2021/github |
| 256 | `npm:@waterfallbridge/mcp@1.2.4` | 236 | io.github.waterfallbridge/mcp |
| 257 | `npm:bulkrender-mcp@1.1.1` | 234 | io.github.ayo-nci/bulkrender |
| 258 | `npm:env-secret-exposure-analyzer-mcp@0.2.0` | 233 | io.github.vola-trebla/env-secret-exposure-analyzer-mcp |
| 259 | `npm:fabrx@1.0.3` | 232 | io.github.cc1988cc/fabrx |
| 260 | `npm:idml-mcp@0.1.1` | 232 | io.github.jimprivate/idml-mcp |
| 261 | `npm:siteglass-mcp@0.1.5` | 232 | io.siteglass/mcp |
| 262 | `npm:@agenson-horrowitz/document-parser-mcp@1.0.8` | 231 | io.github.agenson-horrowitz/document-parser |
| 263 | `npm:teedy-mcp@1.0.0` | 231 | io.github.mrfentmen/teedy-mcp |
| 264 | `npm:whats-inherited-mcp@0.1.6` | 231 | io.github.stcmain/whats-inherited-mcp |
| 265 | `npm:suprasuta-markdown-mcp@0.1.4` | 230 | io.github.Narashiman-K/markdown-notes-mcp |
| 266 | `npm:sketchdex@0.1.2` | 228 | io.github.lucasr1b/sketchdex |
| 267 | `npm:@evan-moon/memex@0.5.0` | 226 | io.github.evan-moon/memex |
| 268 | `npm:@thrain/spotlight-mcp@0.1.2` | 226 | ai.thrain/spotlight |
| 269 | `npm:bach-filecommander-mcp@1.7.0` | 226 | io.github.lukisch/bach-filecommander-mcp |
| 270 | `npm:logreducer@0.1.1` | 226 | io.github.imankha/log-reducer |
| 271 | `npm:mindbase-mcp@0.1.3` | 226 | io.github.frankchu91/mindbase |
| 272 | `npm:@leafwright/mcp@0.2.4` | 225 | co.leafwright/leafwright |
| 273 | `npm:wick-mcp@0.1.0` | 225 | io.github.myleshorton/wick |
| 274 | `npm:wick-mcp@0.5.0` | 225 | io.github.wickproject/wick |
| 275 | `npm:@firsthandapi/mcp-server@0.3.1` | 224 | com.firsthandapi/mcp-server |
| 276 | `npm:bovedia@2.7.0` | 224 | io.github.jmpdsevilla/bovedia |
| 277 | `npm:@maias/mcp@0.5.1` | 221 | io.github.MAIAS-project/maias |
| 278 | `npm:ms-onedrive-mcp@1.0.1` | 221 | io.github.0xka13b/ms-onedrive-mcp |
| 279 | `npm:sourceforge-mcp@1.0.2` | 221 | io.github.mrfentmen/sourceforge-mcp |
| 280 | `npm:@gambadio/apple-productivity-mcp@3.0.0` | 220 | io.github.gambadio/apple-productivity-mcp |
| 281 | `npm:3d-texture-toolkit-mcp@0.1.1` | 219 | io.github.JiangShan118/3d-texture-toolkit |
| 282 | `npm:invovate-mcp-server@0.1.1` | 218 | io.github.LightSpeedPlusOne/invovate-mcp-server |
| 283 | `npm:localize-mcp@0.1.6` | 218 | io.github.JoblessJoe/localize |
| 284 | `npm:@dbconvert/stream-mcp@2.7.3` | 216 | com.dbconvert/streams |
| 285 | `npm:fimemory@0.5.0` | 216 | io.github.FutureAiIndustries/fimemory |
| 286 | `npm:@bitofacoder/omni-mcp-server@1.1.1` | 210 | io.github.bitofacoder/omni-mcp-server |
| 287 | `npm:@mockherodev/mcp-server@0.2.0` | 210 | io.github.dinosaur24/mockhero |
| 288 | `npm:fs-mcp-rs@1.2.4` | 210 | io.github.nihmadev/fs-mcp-rs |
| 289 | `npm:swiadectwo-energetyczne24-mcp@1.2.0` | 210 | pl.swiadectwo-energetyczne24/zamowienia |
| 290 | `npm:@formatix-ai/mcp@0.1.1` | 209 | io.github.FormatixAI/mcp-server |
| 291 | `npm:@sendsoon/mcp@0.3.8` | 208 | io.github.sendsoon/mcp |
| 292 | `npm:@labtoolsstudio/fetchmcp@0.1.1` | 207 | io.github.labtools-studio/fetchmcp |
| 293 | `npm:printgo@0.2.0` | 207 | io.github.Nishkalkashyap/printgo |
| 294 | `npm:@rcs-kz/bitrix24-mcp@1.0.1` | 206 | io.github.RCS-kz/bitrix24-mcp |
| 295 | `npm:diemdesk-mcp@0.1.2` | 206 | com.diemdesk/mcp |
| 296 | `npm:md-feedback@1.5.6` | 205 | io.github.yeominux/md-feedback |
| 297 | `npm:bank-statement-sheet-mcp@0.1.1` | 204 | com.bankstatementsheet/bank-statement-sheet-mcp |
| 298 | `npm:thecrawler@0.5.8` | 204 | io.github.manchittlab/thecrawler |
| 299 | `npm:picright-mcp@0.1.0` | 203 | io.github.ChloePark85/picright |
| 300 | `npm:@fixpixel/filewash-api@0.1.0` | 202 | io.github.cassilup/filewash |
| 301 | `npm:@yafldev/mcp@0.1.6` | 201 | dev.yafl/mcp |
| 302 | `npm:shippage-mcp@1.2.1` | 201 | io.github.jieshu666/shippage |
| 303 | `npm:clean-markdown-mcp@1.1.3` | 199 | io.github.damonwill78-a11y/clean-markdown |
| 304 | `npm:sharedoc-mcp@2.1.4` | 198 | io.github.AugustusW/sharedoc-mcp |
| 305 | `npm:sparkbites-mcp@0.1.1` | 197 | io.github.educlopez/sparkbites |
| 306 | `npm:quality-control-plan-mcp@0.1.0` | 196 | com.imnoo/quality-control-plan |
| 307 | `npm:@br8n/mcp@0.1.2` | 195 | io.br8n/mcp |
| 308 | `npm:mintpdf-mcp@0.1.3` | 195 | io.github.TrendTweekers/mintpdf |
| 309 | `npm:@docweave/mcp@0.2.0` | 194 | io.github.NicolasMartalog/docweave-mcp |
| 310 | `npm:@gluip/chart-canvas-mcp@0.3.2` | 194 | io.github.gluip/chart-canvas |
| 311 | `npm:razi-tools-mcp@2.1.2` | 194 | io.github.razikallayi/razi-tools |
| 312 | `npm:@fablenator/tiled-mcp@1.0.3` | 193 | io.github.fablenator/tiled-mcp |
| 313 | `npm:distill-mcp-server@0.1.1` | 193 | io.github.lakshgk/distill-mcp |
| 314 | `npm:@oscarmarin/mcp-devtools@1.0.1` | 192 | io.github.marin1321/mcp-devtools |
| 315 | `npm:envibe-mcp@0.2.7` | 191 | io.github.dominic-righthere/envibe |
| 316 | `npm:quillpdf-mcp@0.2.0` | 191 | io.github.PurpleDirective/quillpdf-mcp |
| 317 | `npm:jsx-notation@0.1.6` | 190 | io.github.SebastianMaciel/jsx-notation |
| 318 | `npm:@flyfish-dev/file-ai@0.1.1` | 189 | io.github.flyfish-dev/file-ai |
| 319 | `npm:@krimto-labs/krimto@0.2.47` | 189 | io.github.krimto-labs/krimto |
| 320 | `npm:vocce-transcribe-mcp@1.1.0` | 188 | io.github.cmoonagent/vocce-agent |
| 321 | `npm:yaktool-store-mcp@0.1.0` | 188 | com.yaktool/store |
| 322 | `npm:random-design-mcp@2.1.0` | 187 | io.github.yanislav-igonin/random-design-mcp |
| 323 | `npm:visa-info-mcp@1.0.2` | 187 | io.github.rajat79suri/visa-info |
| 324 | `npm:@seamless-engineering/datev-extf-mcp@0.1.0` | 186 | engineering.seamless/datev-extf |
| 325 | `npm:mcp-media-forge@0.2.0` | 186 | io.github.PavelGuzenfeld/media-forge |
| 326 | `npm:@keyhalve/verify-mcp@0.1.0` | 185 | com.keyhalve/verify |
| 327 | `npm:i18n-codelens-mcp@2.0.0` | 184 | io.github.hepter/i18n-codelens-mcp |
| 328 | `npm:mcp-await@0.1.3` | 184 | io.github.ricardo-hdrn/mcp-await |
| 329 | `npm:beleg2datev-mcp@1.0.2` | 183 | io.github.igorkazazic1989/beleg2datev-mcp |
| 330 | `npm:@infoinlet/mcp-filesystem@0.1.1` | 181 | io.github.infoinlet-marketplace/mcp-filesystem |
| 331 | `npm:@intenttext/mcp-server@1.0.1` | 181 | io.github.intenttext/intenttext-mcp |
| 332 | `npm:@x402-tools/mcp@1.8.0` | 181 | io.github.acrylicfiddle/x402tools |
| 333 | `npm:spa-reader-mcp@1.0.2` | 181 | io.github.XXO47OXX/spa-reader-mcp |
| 334 | `npm:confdiff-mcp@0.17.1` | 180 | io.github.esperanza-volkov/confdiff-mcp |
| 335 | `npm:@dockndevai/mcp-macos@0.2.1` | 179 | io.github.dockndevai/mcp-macos |
| 336 | `npm:vectorizer-mcp@0.2.0` | 179 | io.github.JonathanWeerakkody/vectorise |
| 337 | `npm:@mukundakatta/csv-tools-mcp@0.1.0` | 177 | io.github.MukundaKatta/csv-tools-mcp |
| 338 | `npm:pdf-letter-mcp@1.0.3` | 177 | io.github.bitterdev/pdf-letter-mcp |
| 339 | `npm:tooldash-mcp@1.0.2` | 176 | io.github.LassiB999/tooldash-mcp |
| 340 | `npm:faktuj-mcp@1.2.0` | 175 | io.github.dpozimski/faktuj-mcp |
| 341 | `npm:@ellul-estate/batesio-com-batesio-document-management-tools-mcp@1.0.0` | 174 | com.batesio/batesio-document-management-tools |
| 342 | `npm:stayput-mcp@0.1.0` | 174 | io.github.keenanlk/stayput |
| 343 | `npm:@klarefi/mcp@0.3.0` | 173 | com.klarefi/mcp |
| 344 | `npm:@robot-resources/scraper-mcp@0.1.2` | 173 | io.github.robot-resources/scraper |
| 345 | `npm:@textavia/mcp@0.1.2` | 173 | io.github.catorch/textavia-mcp |
| 346 | `npm:agentbase-mcp@1.0.1` | 173 | io.github.izworskic/openclaw-registry |
| 347 | `npm:@lattis-dev/cli@0.4.0` | 172 | dev.lattis/mcp |
| 348 | `npm:company-gibraltar-mcp@1.0.0` | 172 | io.github.Company-Gibraltar/company-gibraltar |
| 349 | `npm:devkits-mcp-server@1.0.0` | 172 | io.github.hezeclark/devkits |
| 350 | `npm:@passwerk/server@0.1.1` | 171 | io.github.ShahriarBijoy/passwerk |
| 351 | `npm:parseflow-mcp-server@1.0.2` | 171 | io.github.Libres-coder/parseflow |
| 352 | `npm:tableaugen-mcp@0.1.1` | 171 | io.github.twilize5/tableaugen-mcp |
| 353 | `npm:soul-mcp-server@1.0.0` | 170 | io.github.AntonioTF5/soul-mcp-server |
| 354 | `npm:@unstringify/mcp@0.1.1` | 168 | io.github.tekinnnnn/unstringify |
| 355 | `npm:@macbookgenesis/genesis-mcp@1.0.2` | 167 | io.github.palsus2023-eng/genesis-mcp |
| 356 | `npm:@pharmatools/groundwork@0.4.1` | 167 | io.github.nickjlamb/groundwork |
| 357 | `npm:docx-forge-mcp@0.1.1` | 167 | io.github.mdfifty50-boop/docx-forge |
| 358 | `npm:iteratools-mcp@1.0.5` | 166 | io.github.fredpsantos33/iteratools |
| 359 | `npm:@deckflow/deckprobe-mcp@0.1.1` | 165 | io.github.deckflow/deckprobe |
| 360 | `npm:@mnemoscope/mcp-server@0.2.0` | 165 | io.github.toonight/mnemoscope |
| 361 | `npm:company-gi-mcp@1.0.1` | 165 | io.github.Company-Gibraltar/company-gi |
| 362 | `npm:@printyourduck/mcp@0.1.1` | 164 | com.printyourduck/quote |
| 363 | `npm:snapforge-mcp@1.3.0` | 164 | org.snapforge/snapforge |
| 364 | `npm:@infoinlet/mcp-github@0.1.1` | 163 | io.github.infoinlet-marketplace/mcp-github |
| 365 | `npm:docbot-mcp@1.0.4` | 163 | io.github.rflukerii-dev/docbot-mcp |
| 366 | `npm:pdffr-mcp@0.1.1` | 163 | io.github.AmerSarhan/pdffr-mcp |
| 367 | `npm:@edititall/mcp@0.2.1` | 162 | io.github.Subcue/edititall-mcp |
| 368 | `npm:@filearchitect/blankfiles-mcp@1.0.1` | 161 | io.github.filearchitect/blankfiles-mcp |
| 369 | `npm:@jayjex/pdfcheck-mcp@0.1.1` | 161 | io.github.jayjex/pdfcheck-mcp |
| 370 | `npm:mcp-ratchet-clinical-charting@0.1.0` | 161 | io.github.m2ai-mcp-servers/mcp-ratchet-clinical-charting |
| 371 | `npm:loremfile@0.2.0` | 160 | io.github.kumarprabhashanand/loremfile |
| 372 | `npm:pdf-triage-mcp@0.1.2` | 159 | io.github.vishalmeena2211/pdf-triage-mcp |
| 373 | `npm:@infoinlet/mcp-fetch@0.1.1` | 158 | io.github.infoinlet-marketplace/mcp-fetch |
| 374 | `npm:@rog0x/mcp-markdown-tools@1.0.2` | 158 | io.github.rog0x/markdown |
| 375 | `npm:silverbullet-mcp@1.0.0` | 157 | io.github.wicahma/silverbullet-mcp |
| 376 | `npm:aifeed-mcp-server@1.0.0-draft.2` | 156 | io.github.denyn1/aifeed-mcp-server |
| 377 | `npm:convertisseur-ia-mcp@1.0.1` | 156 | io.github.Walmes1/convertisseur-ia |
| 378 | `npm:@rog0x/mcp-web-tools@1.0.1` | 155 | io.github.rog0x/web |
| 379 | `npm:syncbridge-mcp@0.1.1` | 155 | io.github.rehmansherazi/syncbridge-mcp |
| 380 | `npm:memocall@0.1.0` | 153 | io.github.baodq06/memocall |
| 381 | `npm:x402-codesearch-mcp@0.1.0` | 152 | io.github.liminalpepe/x402-codesearch-mcp |
| 382 | `npm:@dicepdf/mcp@0.1.0` | 151 | io.github.ishan-maheshwari/dicepdf |
| 383 | `npm:@mukundakatta/html-to-markdown-mcp@0.1.0` | 151 | io.github.MukundaKatta/html-to-markdown-mcp |
| 384 | `npm:upnext-mcp@0.3.1` | 151 | io.github.tothienbao6a0/upnext |
| 385 | `npm:mcp-server-web-fetcher@0.1.0` | 149 | io.github.vojtisprime11/web-fetcher |
| 386 | `npm:@ctalasila/pdf-report-generator@1.0.1` | 148 | io.github.themoddedcube/pdf-report-generator |
| 387 | `npm:easysend-mcp@1.0.1` | 148 | io.github.Easysend-co/easysend |
| 388 | `npm:@infoinlet/mcp-jp-doc-intel@0.1.0` | 147 | io.github.infoinlet-marketplace/mcp-jp-doc-intel |
| 389 | `npm:datascoop-mcp@1.0.0` | 147 | io.datascoop/datascoop |
| 390 | `npm:tabletemplates-mcp@0.1.0` | 147 | io.github.tresor4k/tabletemplates-mcp |
| 391 | `npm:@mrfentmen/meilisearch-mcp@1.0.2` | 146 | io.github.mrfentmen/meilisearch-mcp |
| 392 | `npm:@dmarc-examiner/mcp@1.1.0` | 145 | io.github.dmarc-examiner/mcp |
| 393 | `npm:@dockndevai/mcp-mac-control@0.3.1` | 145 | io.github.dockndevai/mcp-mac-control |
| 394 | `npm:pdfspark-mcp@1.2.0` | 145 | io.github.dpozimski/pdfspark-mcp |
| 395 | `npm:pagewatch-mcp@0.1.0` | 144 | dev.pagelens/pagewatch |
| 396 | `npm:@devpick/mcp-server@1.0.1` | 143 | io.github.kimbobmarley03/devpick |
| 397 | `npm:@infoinlet/mcp-data@0.1.1` | 143 | io.github.infoinlet-marketplace/mcp-data |
| 398 | `npm:@rog0x/mcp-json-tools@1.0.1` | 143 | io.github.rog0x/json |
| 399 | `npm:@vijayst/invoice-studio@1.0.0` | 141 | io.github.vijayst/invoice-studio |
| 400 | `npm:@sitharaj88/winctl@1.0.2` | 132 | io.github.sitharaj88/winctl |
| 401 | `npm:zotero-bridge@1.0.3` | 100 | io.github.Combjellyshen/zotero-bridge |
| 402 | `npm:font-proof-mcp@0.1.0` | 96 | io.github.jakefleming/font-proof-mcp |
| 403 | `npm:image-puma@1.0.0` | 85 | io.github.panth-net/Image-Puma |
| 404 | `npm:local-llm-worker@0.1.4` | 80 | io.github.JoblessJoe/local-llm-worker |
| 405 | `pypi:Mac-letterhead@0.25.0` | pypi | io.github.easytocloud/mac-letterhead |
| 406 | `pypi:achlens@0.1.2` | pypi | io.github.mscott9160-web/achlens |
| 407 | `pypi:acpi-mcp@0.1.0` | pypi | io.github.0xmortuex/acpi-mcp |
| 408 | `pypi:agent-booster@0.6.4` | pypi | io.github.sseshachala/agent-booster |
| 409 | `pypi:agent-coherence@0.14.1` | pypi | io.github.Cohexa-ai/stale-write-guard-fs |
| 410 | `pypi:agentfetch-mcp@1.0.1` | pypi | io.github.bch1212/agentfetch |
| 411 | `pypi:agentic-csv-cleaner@0.1.3` | pypi | io.github.wesseltl/data-cleaner-agent |
| 412 | `pypi:agentmailkit@0.2.2` | pypi | io.github.ariaxhan/agentmailkit |
| 413 | `pypi:agentrender-mcp@0.1.3` | pypi | io.github.corbinvachal48/agentrender-mcp |
| 414 | `pypi:agents-md-generator@0.6.1` | pypi | io.github.nushey/agents-md-generator |
| 415 | `pypi:ai-first-scraper-mcp@1.0.2` | pypi | io.github.yubinkim444/ai-first-scraper-mcp |
| 416 | `pypi:anamnesis-memory@0.1.3` | pypi | io.github.oscardvs/anamnesis |
| 417 | `pypi:aon-agent@1.0.2` | pypi | io.github.leo007-htun/aon |
| 418 | `pypi:archsteer@0.10.0` | pypi | io.github.einvoice-dev1/archsteer |
| 419 | `pypi:basic-memory@1.0.0` | pypi | io.github.basicmachines-co/basic-memory |
| 420 | `pypi:bawbel-mcp@1.1.0` | pypi | io.github.bawbel/bawbel-mcp |
| 421 | `pypi:bawbel-scanner@1.1.1` | pypi | io.github.bawbel/bawbel-scanner |
| 422 | `pypi:bawbel-scanner@1.2.3` | pypi | io.github.bawbel/scanner |
| 423 | `pypi:bettermemory@8.0.0` | pypi | io.github.0Mattias/bettermemory |
| 424 | `pypi:boltwork-mcp@0.1.12` | pypi | io.github.Squidboy30/boltwork-mcp |
| 425 | `pypi:clichefactory-mcp@0.1.8` | pypi | io.github.ClicheFactory/clichefactory-mcp |
| 426 | `pypi:clio-kit@2.2.3` | pypi | io.github.iowarp/geojson-mcp |
| 427 | `pypi:clio-kit@2.2.3` | pypi | io.github.iowarp/sac-mcp |
| 428 | `pypi:code-context-engine@0.4.13` | pypi | io.github.ai-elara/code-context-engine |
| 429 | `pypi:colab-cli-mcp@0.1.0` | pypi | io.github.amgallego8/colab-mcp |
| 430 | `pypi:comdirect-mcp@0.6.1` | pypi | io.github.mad4ms/comdirect-mcp |
| 431 | `pypi:comparer-mcp@0.2.1` | pypi | io.github.raulkivi/comparer-mcp |
| 432 | `pypi:content-mcp@0.8.5` | pypi | io.github.LatentNoise/content |
| 433 | `pypi:convergeqa-mcp@0.2.0` | pypi | io.github.convergeqa/reviews |
| 434 | `pypi:data-profiler-mcp@0.4.0` | pypi | io.github.haiiibin/data-profiler-mcp |
| 435 | `pypi:dataset-explorer-mcp@0.2.2` | pypi | io.github.khanarmaghanrasheed-18/dataset-explorer |
| 436 | `pypi:datumline-agent-guard@0.2.0` | pypi | io.github.datumline/agent-guard |
| 437 | `pypi:de-eli-mcp@0.5.4` | pypi | io.github.matematicsolutions/de-eli-mcp |
| 438 | `pypi:dead-letter@0.4.10` | pypi | io.github.BigCactusLabs/dead-letter |
| 439 | `pypi:doc-control@0.10.1` | pypi | io.github.nuncaeslupus/doc-control |
| 440 | `pypi:docalyze-mcp-server@0.2.1` | pypi | io.github.LunarPerovskite/docalyze |
| 441 | `pypi:docauto-mcp@0.3.0` | pypi | io.github.gzucob/docauto-mcp |
| 442 | `pypi:docconv-mcp@1.0.2` | pypi | io.github.nicklee002e/docconv-mcp |
| 443 | `pypi:docmancer@0.9.17` | pypi | dev.docmancer/docmancer |
| 444 | `pypi:docpick@0.1.2` | pypi | io.github.ArkNill/docpick |
| 445 | `pypi:docsift@0.5.7` | pypi | io.github.anishmoncivarghese/docsift |
| 446 | `pypi:docsonar@0.1.1` | pypi | io.github.ribhav-jain/docsonar |
| 447 | `pypi:drawio-mcp@1.0.2` | pypi | io.github.yohasacura/drawio-mcp |
| 448 | `pypi:embgrep@0.1.0` | pypi | io.github.ArkNill/embgrep |
| 449 | `pypi:epwforge-mcp@0.3.1` | pypi | io.github.guzz-labs/epwforge-mcp |
| 450 | `pypi:excel-agent-mcp@0.1.2` | pypi | io.github.wesseltl/excel-mcp |
| 451 | `pypi:excel-vision-mcp@1.2.1` | pypi | io.github.VOYAGER-Inc/excel-vision-mcp |
| 452 | `pypi:ezmd-mcp@0.1.1` | pypi | io.github.larpey/ezmd |
| 453 | `pypi:fastbcp-mcp@0.1.5` | pypi | io.github.arpe-io/fastbcp-mcp |
| 454 | `pypi:flanner@0.16.0` | pypi | io.github.jaysonmulwa/flanner |
| 455 | `pypi:fullbleed-mcp@0.1.1` | pypi | io.github.fullbleed-engine/fullbleed-mcp |
| 456 | `pypi:glin-ml@0.1.5` | pypi | io.github.AkashChatterjee/glin |
| 457 | `pypi:goldenflow@2.2.0` | pypi | io.github.benseverndev-oss/goldenflow |
| 458 | `pypi:google-drive-comments-mcp@0.1.0` | pypi | io.github.zayansalman/google-drive-comments-mcp |
| 459 | `pypi:google-drive-files-mcp@0.3.0` | pypi | io.github.zayansalman/google-drive-files-mcp |
| 460 | `pypi:hardly@1.0.0` | pypi | io.github.b1tninja/hardly |
| 461 | `pypi:hayward@1.4.1` | pypi | io.github.hedgerow-dev/hayward |
| 462 | `pypi:huoshui-file-converter@1.0.0` | pypi | io.github.huoshuiai42/huoshui-file-converter |
| 463 | `pypi:huoshui-pdf-converter@1.0.0` | pypi | io.github.huoshuiai42/huoshui-pdf-converter |
| 464 | `pypi:huoshui-pdf-translator@1.0.0` | pypi | io.github.huoshuiai42/huoshui-pdf-translator |
| 465 | `pypi:imprint-pdf@0.14.0` | pypi | io.github.263311487-ux/imprint-pdf |
| 466 | `pypi:inclusio@0.0.8` | pypi | io.github.sebastienrousseau/inclusio-mcp |
| 467 | `pypi:iwork-studio@2.6.1` | pypi | io.github.Arkanji/iwork-studio |
| 468 | `pypi:jidoseal-mcp@0.2.0` | pypi | com.jidoseal/jidoseal-mcp |
| 469 | `pypi:journald-mcp-server@0.1.0` | pypi | io.github.james116blue/journald-mcp-server |
| 470 | `pypi:juscaba-mcp@0.3.1` | pypi | io.github.hernan-cc/juscaba-mcp |
| 471 | `pypi:justfill-mcp@0.4.10` | pypi | io.github.mrmaciej1/justfill-pdf-forms |
| 472 | `pypi:kitchensink4word@3.0.1` | pypi | io.github.KitchenSink4AI/kitchensink4word |
| 473 | `pypi:kitchensink4xl@2.0.0` | pypi | io.github.KitchenSink4AI/kitchensink4xl |
| 474 | `pypi:labmcp-ms-data@0.1.1` | pypi | io.github.K-Dense-AI/labmcp-ms-data |
| 475 | `pypi:lanternkb@0.1.3` | pypi | io.github.ankitb073/lanternkb |
| 476 | `pypi:latex-mcp@0.1.3` | pypi | io.github.SepineTam/latex-mcp |
| 477 | `pypi:lathe-mcp@0.4.1` | pypi | io.github.seayniclabs/lathe |
| 478 | `pypi:legal-document-ai-mcp@1.0.10` | pypi | io.github.CSOAI-ORG/legal-document-ai-mcp |
| 479 | `pypi:letin@0.2.0` | pypi | io.github.S-CurveLabs/letin |
| 480 | `pypi:librarian-cli@0.1.1` | pypi | io.github.Terobyte/librarian |
| 481 | `pypi:lightpaper-mcp@0.1.1` | pypi | org.lightpaper/lightpaper-mcp |
| 482 | `pypi:linza-mcp@0.2.2` | pypi | io.github.Semiotronika/LINZA-MCP |
| 483 | `pypi:local-faiss-mcp@0.2.0-rc.3` | pypi | io.github.nonatofabio/local-faiss-mcp |
| 484 | `pypi:locus-mcp@0.6.2` | pypi | io.github.EDKarlsson/locus |
| 485 | `pypi:locus-mcp@0.9.0` | pypi | io.github.Nano-Nimbus/locus |
| 486 | `pypi:luffysolution-omnischolar@0.1.0` | pypi | io.github.luffysolution-svg/omnischolar |
| 487 | `pypi:magpie-search@1.3.1` | pypi | io.github.xfloukiex-lab/magpie-search |
| 488 | `pypi:mainbook-mcp@0.5.1` | pypi | ai.mainbook/bank-statement-converter |
| 489 | `pypi:markdown-ai-mcp@1.0.10` | pypi | io.github.CSOAI-ORG/markdown-ai-mcp |
| 490 | `pypi:markgrab@0.1.2` | pypi | io.github.ArkNill/markgrab |
| 491 | `pypi:markitai@2.3.2` | pypi | io.github.Ynewtime/markitai |
| 492 | `pypi:mcp-biomodelling-servers@2.5.2` | pypi | io.github.marcorusc/PhysiCell |
| 493 | `pypi:mcp-contradiction-check@0.1.0` | pypi | io.github.onetrueclaude-creator/mcp-contradiction-check |
| 494 | `pypi:mcp-curiosity-engine@0.1.0` | pypi | io.github.onetrueclaude-creator/mcp-curiosity-engine |
| 495 | `pypi:mcp-data-profiler@0.1.1` | pypi | io.github.Ridadata/mcp-data-profiler |
| 496 | `pypi:mcp-docs-ask@0.4.0` | pypi | io.github.alyiox/mcp-docs-ask |
| 497 | `pypi:mcp-document-converter@0.2.2` | pypi | io.github.xt765/mcp-document-converter |
| 498 | `pypi:mcp-documents-reader@1.3.1` | pypi | io.github.xt765/mcp_documents_reader |
| 499 | `pypi:mcp-ooxml-ledger@0.3.0` | pypi | io.github.Anselmoo/mcp-ooxml-ledger |
| 500 | `pypi:mcp-pymupdf@0.1.1` | pypi | io.github.penny4nonsense/mcp-pymupdf |
| 501 | `pypi:mcp-search-server@0.1.1` | pypi | io.github.KazKozDev/search |
| 502 | `pypi:mcp-server-akf@1.6.2` | pypi | io.github.HMAKT99/akf |
| 503 | `pypi:mcp-server-spreadsheet@0.3.3` | pypi | io.github.marekrost/mcp-server-spreadsheet |
| 504 | `pypi:mcp-server-vector-memory@0.4.4` | pypi | io.github.NeerajG03/vector-memory |
| 505 | `pypi:mcp-server-xlwings@0.4.1` | pypi | io.github.geniuskey/mcp-server-xlwings |
| 506 | `pypi:mcp-stl@0.1.0` | pypi | io.github.daedalus/mcp-stl |
| 507 | `pypi:mcparmory-box@1.0.5` | pypi | com.mcparmory/box |
| 508 | `pypi:mcparmory-convertapi@1.0.4` | pypi | com.mcparmory/convertapi |
| 509 | `pypi:mcparmory-figma@1.0.6` | pypi | com.mcparmory/figma |
| 510 | `pypi:mcparmory-files-com@1.0.3` | pypi | com.mcparmory/files-com |
| 511 | `pypi:mcparmory-google-drive@1.0.2` | pypi | com.mcparmory/google-drive |
| 512 | `pypi:mcparmory-outline@1.0.2` | pypi | com.mcparmory/outline |
| 513 | `pypi:mcparmory-pdfco@1.0.2` | pypi | com.mcparmory/pdfco |
| 514 | `pypi:mcparmory-ragie@1.0.2` | pypi | com.mcparmory/ragie |
| 515 | `pypi:mcpcap@0.10.0` | pypi | ai.mcpcap/mcpcap |
| 516 | `pypi:mcpproducts-extract@0.1.1` | pypi | com.mcpproducts/extract |
| 517 | `pypi:mcpproducts-office@0.1.1` | pypi | com.mcpproducts/office |
| 518 | `pypi:md-to-pdf-mcp@1.0.1` | pypi | io.github.wmarceau/md-to-pdf |
| 519 | `pypi:mhlabs-mcp-tools@0.0.5` | pypi | io.github.MusaddiqueHussainLabs/mhlabs_mcp_tools |
| 520 | `pypi:mineru-open-mcp@1.0.20` | pypi | io.github.opendatalab/mineru-open-mcp |
| 521 | `pypi:minirag-mcp@1.0.0` | pypi | io.github.sfrangulov/minirag-mcp |
| 522 | `pypi:mio-cua@0.1.5` | pypi | io.github.mldlbs/mio-cua |
| 523 | `pypi:mitos-adr@0.20.0` | pypi | io.github.dovahkiin-v/mitos |
| 524 | `pypi:mnemex@0.5.2` | pypi | io.github.simplemindedbot/mnemex |
| 525 | `pypi:modelrisk-mcp@0.4.5` | pypi | io.github.vosesoftware/modelrisk-mcp |
| 526 | `pypi:moysklad-mcp-ru@0.2.0` | pypi | io.github.ilyautov/moysklad-mcp-ru |
| 527 | `pypi:ms-graph-mcp@0.3.0` | pypi | io.github.nitin27may/ms-graph-mcp |
| 528 | `pypi:naver-mybox-mcp@0.1.0` | pypi | io.github.java-jaydev/naver-mybox-mcp |
| 529 | `pypi:navig@3.27.5` | pypi | io.github.navig-run/navig |
| 530 | `pypi:nira-file-intel@1.0.1` | pypi | io.github.pachote/nira-file-intel |
| 531 | `pypi:nodeproxy-tools@0.2.0` | pypi | io.github.pgalyen1987/nodeproxy |
| 532 | `pypi:ofdkit@0.4.0` | pypi | io.github.Edgar-311/ofdkit |
| 533 | `pypi:onsense@0.3.20` | pypi | io.github.hufirst/onsense |
| 534 | `pypi:openclaw-skill-vetter-mcp@1.1.2` | pypi | io.github.temurkhan13/openclaw-skill-vetter-mcp |
| 535 | `pypi:optical-context-mcp@0.1.5` | pypi | io.github.ChrBoebel/optical-context-mcp |
| 536 | `pypi:oxidize-pdf@0.23.0` | pypi | io.github.bzsanti/oxidize-pdf-mcp |
| 537 | `pypi:p6xer-mcp-server@0.1.3` | pypi | io.github.osama-ata/p6xer-mcp-server |
| 538 | `pypi:paper-format-agent@3.1.0` | pypi | io.github.zxyasfas/paper-format-agent |
| 539 | `pypi:pdf-agent-mcp@0.1.2` | pypi | io.github.wesseltl/pdf-mcp |
| 540 | `pypi:pdf-card-mcp@0.1.2` | pypi | io.github.velyan/pdf-card-mcp |
| 541 | `pypi:pdf-document-mcp@1.0.8` | pypi | io.github.CSOAI-ORG/pdf-document-mcp |
| 542 | `pypi:pdf-form-proof@0.1.1` | pypi | io.github.EssenceAlignment/pdf-form-proof |
| 543 | `pypi:pdf-insight-mcp@0.2.1` | pypi | io.github.Xvvln/pdf-reader-mcp |
| 544 | `pypi:pdf-merge-ai-mcp@1.0.8` | pypi | io.github.CSOAI-ORG/pdf-merge-ai-mcp |
| 545 | `pypi:pdf-modifier@1.10.1` | pypi | io.github.mlorentedev/pdf-modifier |
| 546 | `pypi:pdf-modifier-mcp@1.6.0` | pypi | io.github.mlorentedev/pdf-modifier-mcp |
| 547 | `pypi:pdf-tools-ai-mcp@1.0.9` | pypi | io.github.CSOAI-ORG/pdf-tools-ai-mcp |
| 548 | `pypi:pdf4me-mcp@1.0.0` | pypi | io.github.pdf4me/pdf4me-mcp |
| 549 | `pypi:pdf4vllm-mcp@1.0.2` | pypi | io.github.PyJudge/pdf4vllm |
| 550 | `pypi:pdfmux@1.8.7` | pypi | io.github.NameetP/pdfmux |
| 551 | `pypi:perception-mcp@0.1.7` | pypi | io.github.egorthinks/perception |
| 552 | `pypi:petroleum-mcp@0.8.1` | pypi | io.github.ameyxd/petromcp |
| 553 | `pypi:pressready@0.1.0` | pypi | io.github.ridhwaan-ai/pressready |
| 554 | `pypi:promptready-mcp@0.4.0` | pypi | io.github.hydrojwh/promptready-mcp |
| 555 | `pypi:pvliesdonk-paperless-mcp@3.0.0` | pypi | io.github.pvliesdonk/paperless-mcp |
| 556 | `pypi:qaradar@0.3.5` | pypi | io.github.MuratKus/qaradar |
| 557 | `pypi:qrfile-mcp@0.2.11` | pypi | io.github.hkturtco/qrfile |
| 558 | `pypi:rdl-mcp@0.1.0` | pypi | io.github.bethmaloney/rdl-mcp |
| 559 | `pypi:refigure@0.3.5` | pypi | io.github.HelgDemidov/refigure |
| 560 | `pypi:rejstrik-mcp@0.9.2` | pypi | io.github.janF19/rejstrik-mcp |
| 561 | `pypi:remarkable-mcp@2.1.0` | pypi | io.github.SamMorrowDrums/remarkable |
| 562 | `pypi:render-mcp@0.2.2` | pypi | io.github.raulkivi/render-mcp |
| 563 | `pypi:sayou@0.2.2` | pypi | io.github.pixell-global/sayou |
| 564 | `pypi:searxncrawl@0.33.1` | pypi | io.github.DasDigitaleMomentum/searxncrawl |
| 565 | `pypi:semantic-cache-mcp@0.7.0` | pypi | io.github.CoderDayton/semantic-cache-mcp |
| 566 | `pypi:sentor-mcp@1.0.5` | pypi | io.github.NIKX-Tech/sentor-mcp |
| 567 | `pypi:shelfmark@0.4.9` | pypi | io.github.Dankaro-projects/shelfmark |
| 568 | `pypi:shuck-convert@1.0.0` | pypi | io.github.Shan-Zhu/shuck-convert |
| 569 | `pypi:shuck-file@2.0.4` | pypi | io.github.Shan-Zhu/shuck-file |
| 570 | `pypi:skillguard-cli@0.2.5` | pypi | io.github.RudrenduPaul/skillguard |
| 571 | `pypi:skim-mcp@0.1.1` | pypi | io.github.helloderekg/skim-mcp |
| 572 | `pypi:tablebridge@0.1.1` | pypi | io.github.Michael-WhiteCapData/tablebridge-mcp |
| 573 | `pypi:tablestakes@1.1.0` | pypi | io.github.oborchers/tablestakes |
| 574 | `pypi:techtenstein-pdf-mcp@1.0.2` | pypi | io.github.sathvic-kollu/techtenstein-pdf |
| 575 | `pypi:text-spreadsheet@0.5.0` | pypi | io.github.demos-ra/text-spreadsheet |
| 576 | `pypi:twilize@0.34.0` | pypi | io.github.subhatta123/twilize |
| 577 | `pypi:ugs-mcp@0.1.1` | pypi | io.github.zackpeters93/ugs-mcp |
| 578 | `pypi:vault-index@0.4.2` | pypi | io.github.GitGudatCodeing/vault-index |
| 579 | `pypi:vexor@0.31.0` | pypi | io.github.scarletkc/vexor |
| 580 | `pypi:vibelawyer@0.1.3` | pypi | io.github.Jack-mi/vibelawyer |
| 581 | `pypi:vs-filesystem-mcp-server@0.1.4` | pypi | io.github.Oncorporation/filesystem-server |
| 582 | `pypi:waitbus@0.2.0` | pypi | io.github.astrogilda/waitbus |
| 583 | `pypi:web-to-markdown-mcp@0.6.0` | pypi | io.github.sidney/web-to-markdown-mcp |
| 584 | `pypi:websearch-skill@0.2.6` | pypi | io.github.hec-ovi/web-search |
| 585 | `pypi:whipscribe-mcp@0.1.5` | pypi | io.github.neugence/whipscribe-mcp |
| 586 | `pypi:word-mcp-server-swadegeiger1@1.0.0` | pypi | io.github.swadegeiger1/word-mcp |
| 587 | `pypi:xlide-mcp@1.2.4` | pypi | io.github.WilliamSmithEdward/xlide-excel-office-vba-mcp |
| 588 | `pypi:xlide-mcp@1.0.1` | pypi | io.github.WilliamSmithEdward/xlide-mcp |
| 589 | `pypi:xlsx-tools-mcp@0.3.2` | pypi | io.github.ruriazz/xlsx-tools-mcp |

</details>

<details><summary>dev-tools: 276 candidates</summary>

| # | package | downloads | registry name |
|---|---|---|---|
| 1 | `npm:kubernetes-mcp-server@0.1.0` | 199511 | io.github.containers/kubernetes-mcp-server |
| 2 | `npm:emailmd@0.13.2` | 19455 | dev.emailmd/emailmd |
| 3 | `npm:podman-mcp-server@0.0.15` | 9383 | io.github.manusa/podman-mcp-server |
| 4 | `npm:mcp-postgres-server@0.3.1` | 4867 | io.github.antonorlov/mcp-postgres-server |
| 5 | `npm:@weiseer/cve-cache-mcp@0.1.1` | 4549 | io.github.weiseer/cve-cache |
| 6 | `npm:@guardbee/mcp-dependency-auditor@0.2.4` | 2373 | io.github.4hmetuyar/dependency-auditor |
| 7 | `npm:mcp-docker-server@1.0.1` | 1996 | io.github.ofershap/docker |
| 8 | `npm:@guardbee/mcp-slopsquat-scanner@0.1.1` | 1850 | io.github.4hmetuyar/slopsquat-scanner |
| 9 | `npm:@nekzus/mcp-server@1.26.1` | 1850 | io.github.Nekzus/npm-sentinel-mcp |
| 10 | `npm:@robinmordasiewicz/f5xc-terraform-mcp@3.24.0` | 1275 | io.github.robinmordasiewicz/f5xc-terraform-mcp |
| 11 | `npm:@hypnosis/docker-mcp-server@2.0.1` | 1201 | io.github.hypnosis/docker-mcp-server |
| 12 | `npm:@diagrams-so/mcp@1.4.7` | 1121 | io.github.RedHold/diagrams-so-mcp |
| 13 | `npm:containerization-assist-mcp@1.5.0` | 1116 | io.github.Azure/containerization-assist |
| 14 | `npm:@mrfentmen/sentry-mcp@1.1.0` | 1101 | io.github.mrfentmen/sentry-mcp |
| 15 | `npm:stalemap@0.4.1` | 1098 | io.github.Umair/stalemap |
| 16 | `npm:landmines@0.2.2` | 1092 | tech.landmine/landmine |
| 17 | `npm:@vfarcic/dot-ai@0.112.0` | 1040 | io.github.vfarcic/dot-ai |
| 18 | `npm:docker-hub-mcp@1.0.1` | 908 | io.github.mrfentmen/docker-hub-mcp |
| 19 | `npm:kubeview-mcp@2.3.0` | 901 | io.github.mikhae1/kubeview |
| 20 | `npm:@mrfentmen/bundlephobia-mcp@1.0.1` | 873 | io.github.mrfentmen/bundlephobia-mcp |
| 21 | `npm:@nickw8/bash-mcp@5.0.1` | 839 | io.github.nickw8/bash-mcp |
| 22 | `npm:@mcpskillsio/server@2.5.3` | 762 | io.mcpskills/server |
| 23 | `npm:esm-mcp@1.0.1` | 727 | io.github.mrfentmen/esm-mcp |
| 24 | `npm:@paretools/docker@0.8.0` | 724 | io.github.Dave-London/docker |
| 25 | `npm:@paretools/docker@0.8.1` | 724 | io.github.Dave-London/pare-docker |
| 26 | `npm:@mrfentmen/npm-registry-mcp@1.0.1` | 708 | io.github.mrfentmen/npm-registry-mcp |
| 27 | `npm:@droidagentkit/launcher@0.3.2-alpha` | 699 | io.github.iVamsi/android-agent-kit |
| 28 | `npm:@aivolution/isitdone@0.9.0` | 652 | io.github.raimondasl/isitdone |
| 29 | `npm:@dockndevai/mcp-kubernetes@0.3.3` | 629 | io.github.dockndevai/mcp-kubernetes |
| 30 | `npm:sandboxer-mcp@0.1.0` | 616 | com.sandboxer/mcp |
| 31 | `npm:@devopsagent/mcp-server@1.0.7` | 612 | io.github.shittuay/devops-agent |
| 32 | `npm:@dockndevai/mcp-percona-pg@0.3.3` | 594 | io.github.dockndevai/mcp-percona-pg |
| 33 | `npm:lema-mcp@0.22.2` | 594 | io.github.lemahq/lema-mcp |
| 34 | `npm:@paretools/lint@0.8.0` | 591 | io.github.Dave-London/lint |
| 35 | `npm:@paretools/lint@0.8.1` | 591 | io.github.Dave-London/pare-lint |
| 36 | `npm:pkg-health-mcp@0.2.0` | 564 | io.github.orcsnren/pkg-health-mcp |
| 37 | `npm:@paretools/npm@0.8.0` | 555 | io.github.Dave-London/npm |
| 38 | `npm:@paretools/npm@0.8.1` | 555 | io.github.Dave-London/pare-npm |
| 39 | `npm:signalint-mcp@1.2.1` | 553 | io.github.TranQui004/signalint |
| 40 | `npm:overwing-mcp@0.15.0` | 548 | ai.overwing/mcp |
| 41 | `npm:packkit-mcp@0.2.2` | 532 | io.github.DanMat/packkit-mcp |
| 42 | `npm:eu-cloud-mcp@0.1.0` | 529 | io.github.moveinfra/eu-cloud-mcp |
| 43 | `npm:jira-datacenter-mcp@0.6.0` | 525 | io.github.MrRefactoring/atlassian-dc-mcp-jira |
| 44 | `npm:ai-context-kit@0.1.2` | 521 | io.github.ofershap/ai-context-kit |
| 45 | `npm:@reneturcios/shipcheck@0.2.0` | 510 | io.github.CloudCorpRecords/shipcheck |
| 46 | `npm:dev-error-explainers@0.2.1` | 502 | io.github.mahdibrr/dev-error-explainers |
| 47 | `npm:safeinstall-cli@0.12.0` | 496 | io.github.Mickdownunder/safeinstall |
| 48 | `npm:k8scortex-mcp@1.1.3` | 495 | io.github.apatilgtn/k8scortex-mcp |
| 49 | `npm:@automatelab/n8n-mcp@0.3.0` | 489 | io.github.ratamaha-git/n8n-mcp |
| 50 | `npm:dugganusa-cli@1.3.4` | 484 | io.github.pduggusa/dugganusa-cli |
| 51 | `npm:@readystack/cron-schedule-lint@0.1.3` | 482 | io.github.jmshinhwa/cron-schedule-lint |
| 52 | `npm:@pkgproof/mcp@0.2.1` | 479 | net.pkgproof/pkgproof |
| 53 | `npm:@supernova123/docker-mcp-server@0.3.5` | 478 | io.github.friendlygeorge/docker-mcp-server |
| 54 | `npm:@alisaitteke/docker-mcp@0.2.4` | 475 | io.github.alisaitteke/docker-mcp |
| 55 | `npm:@readystack/einvoice-mandate-lint@1.0.4` | 445 | io.github.jmshinhwa/einvoice-mandate-lint |
| 56 | `npm:@readystack/base-image-eol-lint@0.1.1` | 433 | io.github.jmshinhwa/base-image-eol-lint |
| 57 | `npm:saga-mcp@1.19.0` | 424 | io.github.spranab/saga-mcp |
| 58 | `npm:@readystack/security-headers-csp-lint@0.1.3` | 422 | io.github.jmshinhwa/security-headers-csp-lint |
| 59 | `npm:@readystack/license-flip-audit@0.1.3` | 420 | io.github.jmshinhwa/license-flip-audit |
| 60 | `npm:@dinglebear/synapse@1.0.0` | 415 | ai.dinglebear/synapse |
| 61 | `npm:@reneturcios/npmpreflight@0.1.0` | 412 | io.github.CloudCorpRecords/npmpreflight |
| 62 | `npm:npms-mcp@1.0.0` | 409 | io.github.mrfentmen/npms-mcp |
| 63 | `npm:@readystack/cbpr-address-lint@1.0.1` | 401 | io.github.jmshinhwa/cbpr-address-lint |
| 64 | `npm:zapier-dev-mcp@0.2.0` | 394 | io.github.arose26/zapier-dev-mcp |
| 65 | `npm:@attestd/mcp@0.3.1` | 388 | io.github.attestd-io/attestd-mcp |
| 66 | `npm:proof-of-commitment@1.36.0` | 377 | io.github.piiiico/proof-of-commitment |
| 67 | `npm:@readystack/coverage-gate-lint@1.0.3` | 375 | io.github.jmshinhwa/coverage-gate-lint |
| 68 | `npm:@mrfentmen/package-registry-mcp@1.0.0` | 370 | io.github.mrfentmen/package-registry-mcp |
| 69 | `npm:@readystack/email-footer-law-lint@1.0.6` | 362 | io.github.jmshinhwa/email-footer-law-lint |
| 70 | `npm:@readystack/mcp-2026-migration-lint@0.1.5` | 362 | io.github.jmshinhwa/mcp-2026-migration-lint |
| 71 | `npm:@readystack/model-card-lint-gpai@1.0.3` | 361 | io.github.jmshinhwa/model-card-lint-gpai |
| 72 | `npm:@readystack/cra-24-72-14-reporting-lint@1.0.6` | 360 | io.github.jmshinhwa/cra-24-72-14-reporting-lint |
| 73 | `npm:modelbound-mcp@0.1.2` | 355 | io.github.ModelBound/modelbound-mcp |
| 74 | `npm:@nogoo9/no-crd@0.18.0` | 354 | io.github.nogoo9/no-crd |
| 75 | `npm:reuse-before-generate@0.2.3` | 352 | io.github.aradar46/reuse-before-generate |
| 76 | `npm:@readystack/vsix-publish-lint@1.0.4` | 351 | io.github.jmshinhwa/vsix-publish-lint |
| 77 | `npm:@readystack/jct-transition-lint-2026@0.1.5` | 350 | io.github.jmshinhwa/jct-transition-lint-2026 |
| 78 | `npm:@readystack/pqc-deprecation-lint@1.0.3` | 350 | io.github.jmshinhwa/pqc-deprecation-lint |
| 79 | `npm:@readystack/wcag22-css-lint@1.0.4` | 348 | io.github.jmshinhwa/wcag22-css-lint |
| 80 | `npm:@readystack/actions-deprecation-lint-2026@0.1.6` | 346 | io.github.jmshinhwa/actions-deprecation-lint-2026 |
| 81 | `npm:@notharshhaa/devops-mcp@2.1.1` | 344 | io.github.NotHarshhaa/devops-mcp |
| 82 | `npm:@readystack/k8s-removed-api-lint@1.0.3` | 342 | io.github.jmshinhwa/k8s-removed-api-lint |
| 83 | `npm:@readystack/sql-card-data-lint@1.0.3` | 340 | io.github.jmshinhwa/sql-card-data-lint |
| 84 | `npm:@readystack/jdk25-upgrade-blocker-lint@1.0.4` | 338 | io.github.jmshinhwa/jdk25-upgrade-blocker-lint |
| 85 | `npm:@readystack/pld-liability-window-lint@1.0.4` | 337 | io.github.jmshinhwa/pld-liability-window-lint |
| 86 | `npm:@readystack/france-einvoice-reception-lint@1.0.5` | 332 | io.github.jmshinhwa/france-einvoice-reception-lint |
| 87 | `npm:@readystack/privacy-manifest-lint@0.1.3` | 332 | io.github.jmshinhwa/privacy-manifest-lint |
| 88 | `npm:@readystack/play-release-blocker-lint@0.1.5` | 330 | io.github.jmshinhwa/play-release-blocker-lint |
| 89 | `npm:@readystack/wordpress-privacy-lint@1.0.5` | 329 | io.github.jmshinhwa/wordpress-privacy-lint |
| 90 | `npm:@readystack/security-txt-cra-lint@1.0.7` | 328 | io.github.jmshinhwa/security-txt-cra-lint |
| 91 | `npm:@readystack/pytest-deprecation-lint@1.0.2` | 327 | io.github.jmshinhwa/pytest-deprecation-lint |
| 92 | `npm:@readystack/green-claim-lint-empco@1.0.4` | 326 | io.github.jmshinhwa/green-claim-lint-empco |
| 93 | `npm:@readystack/terraform-provider-pin-lint@1.0.2` | 326 | io.github.jmshinhwa/terraform-provider-pin-lint |
| 94 | `npm:@readystack/tls-cert-lifetime-lint@0.1.5` | 326 | io.github.jmshinhwa/tls-cert-lifetime-lint |
| 95 | `npm:@readystack/impressum-lint-de@1.0.1` | 325 | io.github.jmshinhwa/impressum-lint-de |
| 96 | `npm:@readystack/rechnung-pflichtangaben-lint-de@1.0.3` | 322 | io.github.jmshinhwa/rechnung-pflichtangaben-lint-de |
| 97 | `npm:@iliasabk/geolint@0.4.0` | 321 | io.github.iliasabk/geolint |
| 98 | `npm:@readystack/openapi-security-contract-lint@1.0.2` | 321 | io.github.jmshinhwa/openapi-security-contract-lint |
| 99 | `npm:@readystack/autorenew-signup-lint@1.0.5` | 320 | io.github.jmshinhwa/autorenew-signup-lint |
| 100 | `npm:@readystack/eaa-form-lint-wcag22@1.0.4` | 318 | io.github.jmshinhwa/eaa-form-lint-wcag22 |
| 101 | `npm:@readystack/sepa-pain001-reject-lint@1.0.2` | 318 | io.github.jmshinhwa/sepa-pain001-reject-lint |
| 102 | `npm:@readystack/currency-minor-unit-lint@0.1.3` | 317 | io.github.jmshinhwa/currency-minor-unit-lint |
| 103 | `npm:@readystack/gpsr-listing-lint@1.0.2` | 316 | io.github.jmshinhwa/gpsr-listing-lint |
| 104 | `npm:@readystack/npm-trusted-publish-lint@1.0.4` | 316 | io.github.jmshinhwa/npm-trusted-publish-lint |
| 105 | `npm:@readystack/ai-model-license-lint@1.0.2` | 315 | io.github.jmshinhwa/ai-model-license-lint |
| 106 | `npm:@readystack/en301549-lint@0.1.6` | 315 | io.github.jmshinhwa/en301549-lint |
| 107 | `npm:@readystack/hmrc-fraud-prevention-header-lint@0.1.2` | 315 | io.github.jmshinhwa/hmrc-fraud-prevention-header-lint |
| 108 | `npm:@readystack/optout-signal-lint@0.1.1` | 314 | io.github.jmshinhwa/optout-signal-lint |
| 109 | `npm:@cocaxcode/devflow-mcp@0.1.8` | 313 | io.github.cocaxcode/devflow-mcp |
| 110 | `npm:@readystack/image-host-transfer-lint@1.0.2` | 312 | io.github.jmshinhwa/image-host-transfer-lint |
| 111 | `npm:@readystack/svg-asset-compliance-lint@1.0.4` | 311 | io.github.jmshinhwa/svg-asset-compliance-lint |
| 112 | `npm:@readystack/ksef-fa3-invoice-lint@1.0.2` | 310 | io.github.jmshinhwa/ksef-fa3-invoice-lint |
| 113 | `npm:mcp-interactive-terminal@1.0.7` | 310 | io.github.amol21p/interactive-terminal |
| 114 | `npm:@readystack/cra-annex-ii-docs-lint@1.0.4` | 308 | io.github.jmshinhwa/cra-annex-ii-docs-lint |
| 115 | `npm:@mikusnuz/npm-mcp@1.4.0` | 307 | io.github.mikusnuz/npm |
| 116 | `npm:@readystack/ai-disclosure-lint-sb942@1.0.2` | 307 | io.github.jmshinhwa/ai-disclosure-lint-sb942 |
| 117 | `npm:@readystack/ai-model-retirement-lint@0.1.5` | 307 | io.github.jmshinhwa/ai-model-retirement-lint |
| 118 | `npm:@readystack/cloud-cost-landmine-lint@0.1.1` | 307 | io.github.jmshinhwa/cloud-cost-landmine-lint |
| 119 | `npm:@readystack/epub-a11y-metadata-lint@1.0.4` | 307 | io.github.jmshinhwa/epub-a11y-metadata-lint |
| 120 | `npm:@readystack/gitlab-ci-break-lint@1.0.1` | 307 | io.github.jmshinhwa/gitlab-ci-break-lint |
| 121 | `npm:@readystack/latex-submission-lint@1.0.5` | 307 | io.github.jmshinhwa/latex-submission-lint |
| 122 | `npm:@readystack/log-pii-telemetry-lint@1.0.1` | 307 | io.github.jmshinhwa/log-pii-telemetry-lint |
| 123 | `npm:@archrad/deterministic@0.4.1` | 306 | io.github.archradhq/deterministic |
| 124 | `npm:@readystack/bnpl-disclosure-lint-ccd2@1.0.2` | 306 | io.github.jmshinhwa/bnpl-disclosure-lint-ccd2 |
| 125 | `npm:@readystack/angular-removed-api-lint@1.0.2` | 305 | io.github.jmshinhwa/angular-removed-api-lint |
| 126 | `npm:@readystack/tdm-reservation-lint@1.0.5` | 305 | io.github.jmshinhwa/tdm-reservation-lint |
| 127 | `npm:@readystack/hospital-mrf-lint@1.0.4` | 304 | io.github.jmshinhwa/hospital-mrf-lint |
| 128 | `npm:qualien-mcp@0.6.2` | 304 | io.github.qualienai/qualien-mcp |
| 129 | `npm:@readystack/age-gate-lint@1.0.1` | 301 | io.github.jmshinhwa/age-gate-lint |
| 130 | `npm:@readystack/dora-register-lint@1.0.1` | 300 | io.github.jmshinhwa/dora-register-lint |
| 131 | `npm:@dockndevai/mcp-oci@0.1.4` | 299 | io.github.dockndevai/mcp-oci |
| 132 | `npm:@readystack/crypto-export-notice-lint@1.0.1` | 299 | io.github.jmshinhwa/crypto-export-notice-lint |
| 133 | `npm:@readystack/otel-collector-drift-lint@1.0.2` | 299 | io.github.jmshinhwa/otel-collector-drift-lint |
| 134 | `npm:@readystack/accessibility-statement-lint@1.0.2` | 297 | io.github.jmshinhwa/accessibility-statement-lint |
| 135 | `npm:@readystack/dora-ict-contract-clause-lint@1.0.1` | 297 | io.github.jmshinhwa/dora-ict-contract-clause-lint |
| 136 | `npm:@readystack/data-act-switching-lint@1.0.2` | 296 | io.github.jmshinhwa/data-act-switching-lint |
| 137 | `npm:@readystack/spf-dmarc-record-lint@1.1.2` | 295 | io.github.jmshinhwa/spf-dmarc-record-lint |
| 138 | `npm:@readystack/ai-companion-safety-lint@1.0.2` | 294 | io.github.jmshinhwa/ai-companion-safety-lint |
| 139 | `npm:@readystack/pg-migration-lock-lint@1.0.2` | 293 | io.github.jmshinhwa/pg-migration-lock-lint |
| 140 | `npm:@polygraphso/litmus@0.36.0` | 292 | io.github.polygraphso/litmus |
| 141 | `npm:@readystack/fedramp-oscal-ssp-lint@1.0.2` | 292 | io.github.jmshinhwa/fedramp-oscal-ssp-lint |
| 142 | `npm:@readystack/ingress-nginx-retirement-lint@1.0.4` | 292 | io.github.jmshinhwa/ingress-nginx-retirement-lint |
| 143 | `npm:@readystack/outlook-email-html-lint@0.1.1` | 292 | io.github.jmshinhwa/outlook-email-html-lint |
| 144 | `npm:@readystack/en18031-psti-lint@1.0.3` | 291 | io.github.jmshinhwa/en18031-psti-lint |
| 145 | `npm:@readystack/facturae-verifactu-lint@1.0.4` | 291 | io.github.jmshinhwa/facturae-verifactu-lint |
| 146 | `npm:@readystack/soup-list-lint@1.0.2` | 291 | io.github.jmshinhwa/soup-list-lint |
| 147 | `npm:@readystack/consent-proof-record-lint@1.0.1` | 290 | io.github.jmshinhwa/consent-proof-record-lint |
| 148 | `npm:@readystack/dsfinv-k-export-lint@1.0.1` | 289 | io.github.jmshinhwa/dsfinv-k-export-lint |
| 149 | `npm:@readystack/livewire3-upgrade-blocker-lint@1.0.3` | 289 | io.github.jmshinhwa/livewire3-upgrade-blocker-lint |
| 150 | `npm:mcp-dependency-doctor@0.1.2` | 289 | io.github.petrovicistefan/mcp-dependency-doctor |
| 151 | `npm:terraform-registry-mcp@1.0.0` | 289 | io.github.mrfentmen/terraform-registry-mcp |
| 152 | `npm:@readystack/config-dsl-lint-snippet-pack@0.1.4` | 288 | io.github.jmshinhwa/config-dsl-lint-snippet-pack |
| 153 | `npm:@readystack/action-runtime-sunset-lint@1.0.2` | 287 | io.github.jmshinhwa/action-runtime-sunset-lint |
| 154 | `npm:@readystack/i18n-fr-ca-bill96-lint@1.0.1` | 286 | io.github.jmshinhwa/i18n-fr-ca-bill96-lint |
| 155 | `npm:@readystack/kassenbeleg-tse-lint@1.0.1` | 286 | io.github.jmshinhwa/kassenbeleg-tse-lint |
| 156 | `npm:@readystack/arbeitsvertrag-nachwg-lint@1.0.1` | 282 | io.github.jmshinhwa/arbeitsvertrag-nachwg-lint |
| 157 | `npm:@readystack/eu-health-claim-lint@1.0.2` | 281 | io.github.jmshinhwa/eu-health-claim-lint |
| 158 | `npm:@readystack/nis2-incident-runbook-lint@1.0.3` | 280 | io.github.jmshinhwa/nis2-incident-runbook-lint |
| 159 | `npm:@readystack/tailwind-v4-upgrade-blocker-lint@1.0.1` | 278 | io.github.jmshinhwa/tailwind-v4-upgrade-blocker-lint |
| 160 | `npm:@readystack/spdx-license-field-lint@0.1.4` | 277 | io.github.jmshinhwa/spdx-license-field-lint |
| 161 | `npm:@readystack/streitbeilegung-hinweis-lint@1.0.1` | 277 | io.github.jmshinhwa/streitbeilegung-hinweis-lint |
| 162 | `npm:@readystack/bescheid-vorlage-lint-kag@1.0.1` | 276 | io.github.jmshinhwa/bescheid-vorlage-lint-kag |
| 163 | `npm:@readystack/romu-hozon-kikan-lint-jp@1.0.1` | 276 | io.github.jmshinhwa/romu-hozon-kikan-lint-jp |
| 164 | `npm:@florianbruniaux/dep-scope@0.4.2` | 273 | io.github.FlorianBruniaux/dep-scope |
| 165 | `npm:@readystack/saft-pt-atcud-lint@1.0.1` | 273 | io.github.jmshinhwa/saft-pt-atcud-lint |
| 166 | `npm:@readystack/weiterbildung-foerderquote-lint@1.0.1` | 273 | io.github.jmshinhwa/weiterbildung-foerderquote-lint |
| 167 | `npm:@readystack/bulk-sender-lint@1.0.1` | 272 | io.github.jmshinhwa/bulk-sender-lint |
| 168 | `npm:@readystack/sv-rechengroessen-lint-2026@1.0.1` | 272 | io.github.jmshinhwa/sv-rechengroessen-lint-2026 |
| 169 | `npm:@readystack/eudi-rp-request-lint@1.0.1` | 270 | io.github.jmshinhwa/eudi-rp-request-lint |
| 170 | `npm:@readystack/lectura-facil-lint-es@1.0.1` | 269 | io.github.jmshinhwa/lectura-facil-lint-es |
| 171 | `npm:@readystack/tax-year-constant-drift-lint@0.1.2` | 269 | io.github.jmshinhwa/tax-year-constant-drift-lint |
| 172 | `npm:agent-toolkit-mcp@0.4.0` | 269 | io.github.white-hat-lab/agent-toolkit |
| 173 | `npm:@readystack/datenschutz-auskunft-lint@1.0.1` | 267 | io.github.jmshinhwa/datenschutz-auskunft-lint |
| 174 | `npm:savesavesavesave@0.1.3` | 267 | io.github.stefantsezarov/savesavesavesave |
| 175 | `npm:@readystack/canal-de-denuncias-lint-es@1.0.1` | 266 | io.github.jmshinhwa/canal-de-denuncias-lint-es |
| 176 | `npm:@readystack/play-declaration-gap-lint@1.0.1` | 266 | io.github.jmshinhwa/play-declaration-gap-lint |
| 177 | `npm:@readystack/sfdx-retirement-lint@0.1.1` | 263 | io.github.jmshinhwa/sfdx-retirement-lint |
| 178 | `npm:@readystack/en16931-einvoice-lint@1.0.4` | 261 | io.github.jmshinhwa/en16931-einvoice-lint |
| 179 | `npm:go-tokenless@1.1.0` | 261 | io.github.Continuous-Actions/go-tokenless |
| 180 | `npm:npx-vibe@3.0.0` | 258 | io.github.Devrajsinh-Jhala/npx-vibe |
| 181 | `npm:@readystack/uscore-profile-gap-lint@1.0.1` | 256 | io.github.jmshinhwa/uscore-profile-gap-lint |
| 182 | `npm:@readystack/freelance-act-order-lint-jp@1.0.1` | 254 | io.github.jmshinhwa/freelance-act-order-lint-jp |
| 183 | `npm:npm-run-mcp-server@0.2.12` | 254 | io.github.fstubner/npm-run-mcp-server |
| 184 | `npm:@sandovalrr/project-context-mcp@0.4.0` | 251 | io.github.sandovalrr/project-context |
| 185 | `npm:@readystack/dienstanweisung-bewachung-lint@1.0.1` | 243 | io.github.jmshinhwa/dienstanweisung-bewachung-lint |
| 186 | `npm:@readystack/dividenden-quellensteuer-lint@1.0.1` | 243 | io.github.jmshinhwa/dividenden-quellensteuer-lint |
| 187 | `npm:@readystack/auftragsverarbeitung-avv-lint@1.0.1` | 240 | io.github.jmshinhwa/auftragsverarbeitung-avv-lint |
| 188 | `npm:pkgtruth@0.2.2` | 238 | io.github.hxckya/pkgtruth |
| 189 | `npm:@readystack/gerichtskosten-tabelle-lint@1.0.1` | 230 | io.github.jmshinhwa/gerichtskosten-tabelle-lint |
| 190 | `npm:webbersites-x402-mcp@0.3.0` | 228 | io.github.webberdesign/webbersites-x402-mcp |
| 191 | `npm:@scriptmasterlabs/scriptdocs-mcp-server@0.3.1` | 218 | io.github.Timwal78/scriptdocs-mcp-server |
| 192 | `npm:@wkalidev/multichain-mcp@1.2.1` | 218 | io.github.wkalidev/multichain-mcp |
| 193 | `npm:package-intel-mcp@1.1.1` | 216 | io.github.adam121393/package-intel |
| 194 | `npm:@rajsir/mcp-server-terraform@0.2.1` | 212 | io.github.RajeevSirohi/mcp-server-terraform |
| 195 | `npm:@vijay-npm/mcp-weather-server@1.0.2` | 207 | io.github.bellvijay/weather |
| 196 | `npm:x402-micro-tollgate@0.3.3` | 205 | io.github.kevin2003050666-coder/x402-micro-tollgate |
| 197 | `npm:@rog0x/mcp-docker-tools@1.0.1` | 202 | io.github.rog0x/docker |
| 198 | `npm:import-guardian-mcp@0.3.0` | 200 | io.github.Baneado98/import-guardian |
| 199 | `npm:@alisaitteke/npm-mcp@0.0.3` | 195 | io.github.alisaitteke/npm-mcp |
| 200 | `npm:@readystack/gdpr-privacy-notice-lint@1.0.2` | 195 | io.github.jmshinhwa/gdpr-privacy-notice-lint |
| 201 | `npm:@supernova123/jira-mcp-server@1.0.0` | 192 | io.github.friendlygeorge/jira-mcp-server |
| 202 | `npm:npm-search-mcp@1.0.0` | 192 | io.github.mrfentmen/npm-search-mcp |
| 203 | `npm:npm-advisor-mcp@0.1.3` | 191 | io.github.YashviGupta15/npm-advisor-mcp |
| 204 | `npm:@tharanabopearachchi/sql-server-mcp-macos@1.0.4` | 189 | io.github.TharanaBope/sql-server-mcp-macos |
| 205 | `npm:@stitchwand/mcp-server@0.1.1` | 187 | io.github.dilshaus/stitch-wand |
| 206 | `npm:@kubently/cli@2.3.1` | 186 | io.github.kubently/kubently |
| 207 | `npm:@samisouabni/exoscale-mcp@1.0.4` | 186 | io.github.samisouabni/exoscale-mcp |
| 208 | `npm:mcp-server-npm-plus@1.0.1` | 184 | io.github.ofershap/npm-plus |
| 209 | `npm:mcp-server-openshift@1.2.0` | 181 | io.github.sanjaypsachdev/mcp-server-openshift |
| 210 | `npm:@issuecapture/mcp-server@1.0.4` | 180 | io.github.issuecapture/mcp-server |
| 211 | `npm:dependency-fitness-mcp@0.1.1` | 178 | io.github.TweedBeetle/dependency-fitness-mcp |
| 212 | `npm:vdiff-mcp@0.1.2` | 176 | io.github.mcurmi05/vdiff-mcp |
| 213 | `npm:license-compliance-mcp@1.0.2` | 175 | io.github.bighippoman/license-compliance |
| 214 | `npm:safe-upgrade-mcp@0.2.0` | 175 | io.github.white-hat-lab/safe-upgrade |
| 215 | `npm:@readystack/gaibu-soshin-tag-lint-jp@1.0.1` | 172 | io.github.jmshinhwa/gaibu-soshin-tag-lint-jp |
| 216 | `npm:@perceptdot/sentry@0.1.5` | 170 | io.github.perceptdot/sentry |
| 217 | `npm:@patrizzos/envspeak@0.1.0` | 168 | io.github.Patrizzos/envspeak |
| 218 | `npm:willitsend@0.1.0` | 164 | io.github.abryfs/willitsend |
| 219 | `npm:evernode-mcp@0.6.0` | 161 | io.github.Hugegreencandle/evernode-mcp |
| 220 | `npm:@weiseer/package-meta-mcp@0.1.1` | 160 | io.github.weiseer/package-meta |
| 221 | `npm:@rog0x/mcp-markdown-tools@1.0.2` | 158 | io.github.rog0x/markdown |
| 222 | `npm:rtl-mcp@0.2.1` | 158 | io.github.kahlelhawary-art/rtl-mcp |
| 223 | `npm:standup-mcp@0.1.0` | 156 | io.github.sathvic-kollu/standup-mcp |
| 224 | `npm:@mostajs/orm-mcp@0.1.1` | 155 | io.github.apolocine/orm-mcp |
| 225 | `npm:retro-mcp@0.1.0` | 151 | io.github.sathvic-kollu/retro-mcp |
| 226 | `npm:@rog0x/mcp-lint-tools@1.0.2` | 142 | io.github.rog0x/lint |
| 227 | `npm:@rog0x/mcp-npm-tools@1.0.1` | 140 | io.github.rog0x/npm |
| 228 | `npm:mcp-server-npm-search@1.0.1` | 139 | io.github.ofershap/npm-search |
| 229 | `npm:k8s-port-forward-mcp@0.0.8` | 130 | io.github.oijusti/k8s-port-forward-mcp |
| 230 | `npm:cortex-rmcp@3.9.1` | 0 | ai.dinglebear/cortex-rmcp |
| 231 | `npm:synapse-rmcp@0.5.4` | 0 | ai.dinglebear/synapse-rmcp |
| 232 | `npm:scriptprobe-mcp@0.1.0` | -1 | tech.thecompound/scriptprobe |
| 233 | `pypi:a2atlassian@0.2.0` | pypi | io.github.agentic-eng/a2atlassian |
| 234 | `pypi:arch-diagram-mcp@1.2.0` | pypi | io.github.apatilgtn/architecture-diagrams |
| 235 | `pypi:backtest-auditor@0.7.0` | pypi | app.nothingbutalpha/backtest-auditor |
| 236 | `pypi:execkit-mcp@0.10.1` | pypi | io.github.blinkingbit-oss/execkit |
| 237 | `pypi:finops-mcp@0.8.176` | pypi | io.github.chaandannn/finops-mcp |
| 238 | `pypi:flyto-core@2.12.6` | pypi | io.github.flytohub/flyto-core |
| 239 | `pypi:global-executables@1.4.1` | pypi | io.github.asopitech-labs/global-executables |
| 240 | `pypi:homelab-infra-mcp@2.1.1` | pypi | io.github.seayniclabs/homelab-infra-mcp |
| 241 | `pypi:hotin@0.9.21` | pypi | io.github.abe238/hotin |
| 242 | `pypi:idea-reality-mcp@0.3.4` | pypi | io.github.mnemox-ai/idea-reality-mcp |
| 243 | `pypi:innoday@0.112.2-beta` | pypi | io.github.havilandsoftware/mcp-server-innoday |
| 244 | `pypi:janus-mcp-server@0.4.1` | pypi | io.github.tonylchang/janus-mcp |
| 245 | `pypi:k8s-lens-mcp@0.1.0` | pypi | io.github.firas-mcp-servers/k8s-lens-mcp |
| 246 | `pypi:kube-lint-mcp@0.8.9` | pypi | io.github.sophotechlabs/kube-lint-mcp |
| 247 | `pypi:lakelogic-mcp@0.1.4` | pypi | io.github.LakeLogic/lakelogic-mcp |
| 248 | `pypi:lastseen-mcp@0.1.2` | pypi | dev.lastseen/mortality |
| 249 | `pypi:latex-mcp@0.1.3` | pypi | io.github.SepineTam/latex-mcp |
| 250 | `pypi:letin@0.2.0` | pypi | io.github.S-CurveLabs/letin |
| 251 | `pypi:license-sentinel@0.1.0` | pypi | io.github.wgd5678/license-sentinel |
| 252 | `pypi:lumino-mcp-server@0.9.2` | pypi | io.github.geored/lumino |
| 253 | `pypi:mcp-atlassian-attachments@0.3.0` | pypi | io.github.alyiox/mcp-atlassian-attachments |
| 254 | `pypi:mcp-job-search-mp@0.2.0` | pypi | io.github.michalper/mcp-job-search |
| 255 | `pypi:mcp-sandbox-computer-vm-for-ai@0.2.3` | pypi | io.github.flujo-app/mcp-sandbox-computer-vm-for-ai |
| 256 | `pypi:mcp-virtual-computer@0.2.11` | pypi | io.github.flujo-app/mcp-virtual-computer |
| 257 | `pypi:mcparmory-atlassian-jira@1.0.3` | pypi | com.mcparmory/atlassian-jira |
| 258 | `pypi:mcparmory-sentry@1.0.2` | pypi | com.mcparmory/sentry |
| 259 | `pypi:n0s1-mcp@1.1.6` | pypi | io.github.spark1security/n0s1-mcp |
| 260 | `pypi:package-version-check-mcp@1.1.0` | pypi | io.github.MShekow/package-version-check-mcp |
| 261 | `pypi:pixlint@1.1.0` | pypi | io.github.amitsingh-24/pixlint |
| 262 | `pypi:pm-mcp-servers@0.3.0` | pypi | io.github.antnewman/pm-data |
| 263 | `pypi:primer-mcp@0.1.8` | pypi | io.github.ivanlai/primer-mcp |
| 264 | `pypi:sandbox-env-mcp@0.3.1` | pypi | io.github.hs3434/sandbox-env-mcp |
| 265 | `pypi:shortcut-forge@0.2.1` | pypi | io.github.Hyunki6040/shortcut-forge |
| 266 | `pypi:silica-eda@0.5.0` | pypi | io.github.simaanc/silica-eda |
| 267 | `pypi:skillkit-cli@1.0.2` | pypi | io.github.furkan708/skillkit |
| 268 | `pypi:sqlglass@0.1.0` | pypi | io.github.S-CurveLabs/sqlglass |
| 269 | `pypi:strimzi-kafka-cli@1.0.0b11` | pypi | io.github.SystemCraftsman/strimzi-kafka-cli |
| 270 | `pypi:terraback@0.6.0` | pypi | io.github.bmoldo/terraback |
| 271 | `pypi:terraform-ingest@0.1.27` | pypi | io.github.zloeber/terraform-ingest |
| 272 | `pypi:vmware-avi@1.8.8` | pypi | io.github.zw008/vmware-avi |
| 273 | `pypi:waitbus@0.2.0` | pypi | io.github.astrogilda/waitbus |
| 274 | `pypi:whitecapdata-dev@0.1.2` | pypi | io.github.Michael-WhiteCapData/WhiteCapData-Dev |
| 275 | `pypi:x402lint@0.5.2` | pypi | io.github.arden-instance/x402lint |
| 276 | `pypi:yaml-ai-mcp@1.0.9` | pypi | io.github.CSOAI-ORG/yaml-ai-mcp |

</details>
