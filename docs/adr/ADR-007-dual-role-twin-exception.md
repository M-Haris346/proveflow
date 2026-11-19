# ADR-007: Dual-role tools are forwarded to a guard-passing twin (twin mode only)

- Status: accepted (2026-11-15, Phase 4)
- Amends: ADR-003 (twin mode, sink sandbox), ADR-006 (default deny, source+sink deny)

> **This exception MUST NOT survive into any `--real-reads` mode.** In any mode where a
> forwarded call can reach a real server, a dual-role tool is a real sink and stays
> sandboxed, without exception.

## Context

ADR-006 denies every tool with a `sink` role, including tools that are both
`untrusted_source` and `sink` (fetch-a-URL, browser navigation, snapshots). Phase 2.1
recorded the cost: injection into those sources cannot be tested in twin mode, because their
results never come back.

How many tools this affects, in the 155 labeled tools of the stored eval sets (dev 60,
test 40, held-out 55; `uv run python tools/count_dual_role.py`, pinned by
`tests/unit/test_dual_role_count.py`):

| Labeled by | untrusted_source + sink |
|---|---|
| the v2 classifier | **12/155** |
| human labels | **10/155** |
| both | 7/155 (fetch is one of them) |
| v2 only | 5 (browser_navigate, get_blog_post, get_blog_posts, get_linkedin_post, save_conversation) |
| human labels only | 3 (browser_network_requests, fill, image_pull) |

**Agreement:** 7 tools in both out of 15 in the union, a Jaccard of 7/15 = 0.47. v2 and the
human labels disagree about the dual-role set more often than they agree.

Label provenance: dev and test are author-reviewed LLM pre-labels; held-out is a single blind
human labeler. There is no second labeler and no kappa (docs/eval/RESULTS_V2.md).

**This is a MEASUREMENT limitation, not a safety hole.** The twin has no I/O, so a wrongly
forwarded tool cannot cause harm. What it costs is realism: prove attacks up to 5 flows a
human would not call dual-role, and cannot attack 3 that a human would. The dual-role
exception therefore rests on a classification that humans and v2 agree on for fewer than half
the tools in the union, and that must be closed before `--real-reads` (docs/BACKLOG.md).

## Decision

In twin mode, a **dual-role** tool is forwarded to the twin when ALL of these hold:

1. **The session's evidence** labels it `untrusted_source` AND `sink`, with tool-granularity
   evidence only and a real tool name (`proxy.policy.session_dual_role_names`).
2. **The proxy's own v2 classifier**, run on what the twin advertises, also labels it
   `untrusted_source` AND `sink`. The session cannot forge this second opinion.
3. The name is advertised by the twin and collides with no other session or advertised name
   (`names.name_key`).
4. **The twin passed the guard** (`twin.guard.check_no_io`). `UpstreamState.guard_passed` is
   computed by `upstream.twin_stdio` from the same bytes that were hashed (ADR-006 layer A).
   With a guard-failing twin (the test fake twin, or any script that does I/O), the
   dual-role set is empty.

The AND of 1 and 2 (`policy.dual_role_names`) is decided **outside** `ToolPolicy`:
`build_policy` still gives every sink `forward=False`. `server.forwardable_dual_roles` is the
only place the set is computed; the same set goes to `decide` and to the write-path gate.

A **pure sink** (a sink without a source role, on either side) is never in the set and is
always sandboxed. Neither a forged session label nor a guard-passing twin changes that.

Recording: the only new cassette field is `upstream_request.sink` (cassette schema 3), from
the same `policy.is_sink_call` as `sandboxed_call.sink`. On an `upstream_request`,
`sink=true` means exactly "a dual-role tool was forwarded to a guard-passing twin". There is no
new sandbox reason or event. The oracle scans these calls for R1 like sandboxed sink calls
(docs/ORACLE.md).

## Why this is safe in twin mode

- Where the call goes: layer A (ADR-006) means the upstream can only be this interpreter
  running a script in `TWIN_ROOT` whose sha256 matches the session, run from a private copy.
  A forwarded dual-role call reaches that script and nothing else.
- What the script can do: the guard refuses every import except the five a generated twin
  needs and every I/O builtin, so a guard-passing twin cannot write files, open sockets,
  spawn processes or print. It answers with literal synthetic data.
- **What the guard is not:** it stops accidental I/O and casual misuse. It is NOT a sandbox
  against a hostile script. Anyone who can write into TWIN_ROOT can already execute code on
  that machine, so the attacker model in twin mode is "our own generator", not "arbitrary
  hostile script". Do not claim more.
- The canary and honey still cannot leave: a twin has no network path, and the payload
  targets only per-trial canaries and honey values.

## The C2 limit, and why markers stay out of the session (F4)

- R-C2: the evidence that a dual-role call was really served by the twin is the twin's own
  per-tool marker (`pfmark_<hex>`, derived from server, tool and seed) as the last text block
  of the `upstream_response`. That is **liveness** evidence, not safety evidence. Safety
  claims rest on twin-side logs: the fake twin's own raw-byte log, and for a guard-passing
  (so log-less) generated twin the test-only byte tee `tests/fixtures/stdin_tee.py`.
- The marker is independent evidence only while the proxy does not know it. So the session
  and the cassette's `session_start` carry honey (the oracle needs it) and **nothing about
  markers**. Tests take markers from the `TwinBuild`, never from the session, and a named
  test checks that no marker appears in the session file or in `session_start`.
- The limit: a marker proves the generated script answered. It does not prove the script is
  the one the generator wrote (that is the sha256 pin), and it says nothing about safety.

## Consequences

- Injection into fetch-style sources is testable in twin mode (Phase 4 D9: the fetch twin).
- R1 now has two kinds of sink call. Forwarded dual-role calls appear as evidence with
  `event = "upstream_request"` and no sandbox id.
- `--real-reads` (planned, v1) must drop this exception entirely; ADR-003 says so too.

## Tests

- Safety (`tests/safety/test_twin_dual_role_safety.py`):
  - a pure sink never reaches a guard-passing twin with the dual-role path on (tee log;
    includes a pure sink whose session label was forged to source + sink);
  - a dual-role tool never reaches the guard-failing fake twin (its own log);
  - a dual-role tool is forwarded to a generated twin, with the twin's marker in the
    `upstream_response`, recorded `sink=true`; ordinary forwards are `sink=false`;
  - R4 order (copy → hash → guard on the same bytes → spawn), hash mismatch before the
    guard, the guard failure does not stop the spawn;
  - no marker in the session or `session_start`.
- `tests/safety/test_twin_guard_safety.py`: no fixture, patch or session field can set
  `guard_passed` to True for a guard-failing script.
- Mutation (`tests/mutation/test_twin_dual_role_mutation.py`): a pure sink allowed onto the
  dual-role path, dual-role forwarded without `guard_passed`, and the guard reading the
  original path each make a named twin-side check fail.
- Unit: `tests/unit/test_proxy_dual_role.py`.
