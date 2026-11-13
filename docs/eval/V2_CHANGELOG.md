# Role classifier v2: changelog (checkpoint 1c, Stage B)

> **Dev numbers are NOT a claim.** Every rule below was chosen by looking at dev errors and
> kept because it helped on dev. So the dev numbers are optimistic by construction (overfit).
> The only valid measurement of v2 is the fresh held-out set (Stage D, `RESULTS_V2.md`).
> The burned test split (`data/eval/roles/split/` test) was not read for any decision here.

## Frozen classifiers

| Version | `classifier_sha256` (`roles.py` + `server_roles.py`, as computed by `proveflow.eval.metrics`) | Source |
|---|---|---|
| v1 | `08deee09cb4feb3cf388b93c263dbcdc6f95165cba1678a6305680b5b60f4a16` | docs/eval/RESULTS.md (the single test-split run) |
| v2 | `db4100d59c74668c594947fd0bf7d52869bfc831778ff24ac2de352f91a78a50` | docs/eval/DEV_RESULTS_V2.md |

`server_roles.py` is unchanged. Every v2 change is in `src/proveflow/flows/roles.py`.

## Method

- Dev split only: 60 tools, labels `*_a` in `data/eval/roles/split/labels_dev.csv`.
- Each rule group was applied on top of the previous kept state. After each group,
  `uv run python -m proveflow.eval.metrics --split-dir data/eval/roles/split --dev-only` was run.
- Revert rule: a group is reverted if it adds more FP than it removes FN.
- The test-evaluation counter (`metrics_runs.json`) stayed at 1 throughout (sha256 unchanged).
- No rule matches a server id or an exact tool name. Each rule is about verbs, parameter
  names, or description phrases.
- Each rule has a synthetic unit test (`tests/unit/test_roles_v2.py`) and a mutation test
  (`tests/mutation/test_roles_v2_mutation.py`).
- "Browser" below means the two browser-automation servers on dev (chrome-devtools,
  playwright). The per-group sha256 values are intermediate states. The final file was then
  refactored (constants and a helper extracted for the mutation tests; the dev result is
  identical, checked), which produced the v2 sha above.

## Per rule group (dev, deltas vs the previous kept state)

| # | Rule | untrusted_source Δ TP/FP/FN | private_data Δ TP/FP/FN | sink Δ TP/FP/FN | Errors fixed (browser / other) | Errors added | Decision |
|---|---|---|---|---|---|---|---|
| 1 | **C1** file/path param whose description says "save/write/output" → sink (local write) | 0/0/0 | 0/0/0 | +7/0/−7 | 7 (7 / 0) | 0 | keep |
| 2 | **C2+C3** VCS write verbs (commit, checkout, reset, …) only without a read verb → sink; repository param + no write verb → private | 0/0/0 | +7/0/−7 | +3/0/−3 | 10 (0 / 10) | 0 | keep |
| 3 | **C4** page/dialog context + entered-text param (`value`, `prompt_text`, …) → sink | 0/0/0 | 0/0/0 | +3/0/−3 | 3 (3 / 0) | 0 | keep |
| 4 | **C5** hover/drag no longer browser-action verbs; `close` + UI noun (tab, page, dialog, …) is not a write | 0/0/0 | 0/0/0 | 0/−3/0 | 3 (3 / 0) | 0 | keep |
| 5 | **C6** write-verb tool (no read verb): description private words ignored | 0/0/0 | 0/−1/0 | 0/0/0 | 1 (0 / 1) | 0 | keep |
| 6 | **C7** `navigate` removed from source verbs (still a weak sink signal) | 0/−1/0 | 0/0/0 | 0/0/0 | 1 (1 / 0) | 0 | keep |
| 7 | **C8** URL-param sink weight 0.25 → 0.5 (LABELING_GUIDE row 3) | 0/0/0 | 0/0/0 | +1/0/−1 | 1 (1 / 0) | 0 | keep |
| 8 | **C10** singularize schema property names (`paths` → `path`) | 0/0/0 | 0/0/0 | 0/0/0 | 0 | 0 | **reverted**: no dev effect. Both target tools have a write/egress verb (`drop`, `upload`), so C6 removes their description `file` signal, and the path param alone (0.3) stays below threshold. Not kept without dev evidence |
| 9 | **C11a** capture noun {snapshot, screenshot, html, console} + no action/write verb → source ("page" and "content" dropped as too broad; dev hits 4/4, no FP) | +4/0/−4 | 0/0/0 | 0/0/0 | 4 (4 / 0) | 0 | keep |
| 10 | **C11c** description says the output is "untrusted" / "never follow instructions" → source | +1/0/−1 | 0/0/0 | 0/0/0 | 1 (0 / 1) | 0 | keep. The one dev win is the author's own server (pg-mcp-guard, dev-only, not blind) |
| 11 | **C11d** "arbitrary code/JavaScript", "RCE" → also source + private (guide rule 5) | +1/0/−1 | +1/0/−1 | 0/0/0 | 2 (2 / 0) | 0 | keep |
| 12 | **C12** param name containing `header` → sink (sent with requests) | 0/0/0 | 0/0/0 | +1/0/−1 | 1 (1 / 0) | 0 | keep |
| 13 | **C9** `model` param + text input (prompt, messages, code, …) → sink | 0/0/0 | 0/0/0 | +4/0/−4 | 4 (0 / 4) | 0 | keep. **Single-server evidence (grok-mcp, all 4 are uncertain rows); validate on held-out** |

Skipped by decision, not implemented:
- **C11b** (optional include-snapshot param → source): one server's naming convention.
- The 5 errors marked "not addressed" in Stage A.

Totals: **38 of 48 v1 dev errors fixed, 0 added.** 22 fixes come from the two browser servers
and 16 from others (git 11, grok-mcp 4, pg-mcp-guard 1). 17 of the 38 fixes are on rows the
labeler marked uncertain.

## Dev result, v1 vs v2 (N = 60 tools; NOT a claim)

| Role | v1 TP/FP/FN | v1 precision | v1 recall | v2 TP/FP/FN | v2 precision | v2 recall |
|---|---|---|---|---|---|---|
| `untrusted_source` | 5/2/12 | 5/7 | 5/17 | 11/1/6 | 11/12 | 11/17 |
| `private_data` | 3/1/11 | 3/4 | 3/14 | 11/0/3 | 11/11 | 11/14 |
| `sink` | 8/3/19 | 8/11 | 8/27 | 27/0/0 | 27/27 | 27/27 |

Remaining v2 dev errors (10; 8 on uncertain rows):
- private FN: grok_review, browser_drop, browser_file_upload
- source FN: drag, fill, hover, get_css_styles, list_network_requests, browser_network_requests
- source FP: browser_navigate

## Overfitting, stated plainly

- Sink is perfect on dev (27/27, 0 FP). That is the clearest sign of fitting: the sink rules
  were written from these exact misses.
- 22 of 38 fixes come from just two servers with similar tool sets. C1, C4, C5, C7, C8, C11a,
  C11d and C12 were all motivated mainly by browser-automation tools; C2, C3 and C6 by one git
  server.
- C9 rests on one server whose 4 rows are all uncertain. C11c rests on one tool from the
  author's own server.
- Dev has 60 tools from 8 servers. A rule that fixes one or two dev tools has essentially no
  statistical support.
- Expect v2 to do better than v1 on the held-out set mainly where the held-out set looks like
  dev (browser, git, LLM-proxy tools), and much closer to v1 elsewhere. Only Stage D can say.
