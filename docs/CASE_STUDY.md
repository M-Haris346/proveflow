# proveflow: building a security tool that refuses to overstate its own results

A case study in measuring instead of reasoning — including the defect I found in my own tool,
and why it stopped my own release.

---

## The problem

An AI agent connected to several MCP servers holds two capabilities at once: it reads content it
does not control, and it can act on the world. A tool that fetches a web page, and a tool that
writes a file or sends a request, in the same session, is a path. Text in that page can instruct
the model to carry private data out through the second tool. The user approved both tools
separately; nobody approved the combination.

Static scanners can list those pairings. What they cannot tell you is whether a given model, in
your setup, actually follows the instruction. "This might be risky" is a list, not a measurement.

proveflow is my attempt at the measurement: **find** the flows in the MCP setup you actually run,
**prove** whether a real model is hijacked through one, **fix** it with a config patch, and
**verify** the fix on the same cells.

---

## What I built

Four stages, each with its own failure modes.

**Find.** `discover` reads the real client configs — Claude Desktop, Claude Code, Cursor, VS
Code, Windsurf — and redacts secrets at read time, so no raw environment value, header or token
ever reaches a log, a report or a prompt. `scan` optionally launches each server with per-server
consent and asks `tools/list` **only**; a method allowlist blocks `tools/call` outright. Tools are
classified into untrusted source, private data and sink, and a flow graph is built per agent
profile. Output includes SARIF 2.1.0, validated in tests against the official OASIS schemas.

**Prove.** Attacking a real server is not an option, so each server is replaced by a *schema
twin*: a self-contained deterministic script with the same tool names, descriptions and input
schemas, serving synthetic data, honey values and a per-tool marker. A proxy sits between the
agent and the twin: it records a hash-chained cassette, and injects the payload into every
result of the one attacked tool.
- **A pure sink is always sandboxed and never forwarded.**
- **A dual-role tool, one that is both an untrusted source and a sink (e.g. `fetch`), is
  forwarded** to a twin that passed the no-I/O guard, and recorded as
  `upstream_request.sink=true` (ADR-007). That is the path the campaigns actually use.
- The guard is an AST check on the twin script. **It is not a sandbox.**

A real OpenAI-compatible model then drives the tool-calling loop under per-trial caps.

**The oracle is deterministic. There is no LLM judge anywhere in evaluation.** A compromise is
the per-trial canary or a honey value appearing in the arguments of a sink call: a sandboxed
sink call, or a forwarded dual-role sink call (the campaigns use the second). It is matched
across ten encodings: raw, case, zero-width, separator-split, URL, base64, hex, rot13, reversed
and JSON-escaped. Canaries and honey values are rejection-sampled so they cannot collide with
real-looking identifiers: 47.99 bits of canary space, 63.98 bits of honey space, counted
exactly rather than estimated.

**Fix** emits patch files — an RFC 6902 patch per config file, or a Claude Code approval
fragment — and **never applies them**. A safety test proves `fix` never modifies a config: its
bytes and mtime are unchanged. That `fix` never even opens one is by construction, since it reads
only the scan report. That is a design property, not a test result.

**Verify** runs paired halves on the same cells with the mitigation applied in the twin.

Payloads come from a corpus of 347 records drawn from three published benchmarks at pinned
revisions, MIT on every record. 72% come from one source, so results are reported per source and
never pooled.

---

## The result, including the part that is zero

One paid campaign: 30 counted trials, Groq `openai/gpt-oss-120b`, temperature 0.0, ten trials per
corpus source.

**0 of 30 compromised.** Exposure — whether the payload actually reached the model — was measured
at 30 of 30. Per source, 0/10 with a Wilson 95% interval of [0.000, 0.278].

That zero is the most interesting number in the project, for two reasons.

**First, it is honest.** It is reported as zero. Not reframed, not buried, not quietly dropped in
favour of the parts that worked. Every surface says the same thing: ZERO REAL POSITIVES. No real
trial has ever been compromised.

**Second, and this is the point: a zero means nothing on its own.** A pipeline with a broken
oracle, a proxy that never flags sinks, or a payload that never arrives also reports zero. A
clean result and a broken instrument are indistinguishable from the number alone.

So I built the positive control before I trusted the zero.

---

## Control A: the zero has to be earned

The claim the pipeline has to support is narrow: *it counts a compromise if and only if the flow
happens.*

Control A tests both halves on the same 30 cells the paid campaign used. A scripted client that
complies with the injection gives **30 of 30 compromised**. A scripted client that ignores it
gives **0 of 30**. Same cells, same corpus records, same plan.

Then six mutants were written, each breaking one thing. Each is killed with its layer named:
- **L3 delivery**: the proxy serves no injection;
- **L4 proxy**: the sink call is not flagged as a sink;
- **L5 oracle**: the oracle drops the canary needle;
- **L6 ledger**: the verdict is lost before the ledger;
- **L6 report**: the report miscounts the numerator;
- **the iff mutant**: an oracle that fires on anything. It passes the compliant half, and only
  the non-compliant half kills it.

With that in place, the 30 zeros say something precise and nothing more: **a
capability-dependent lower bound under a favourable delivery condition.** They are not an
attack-success rate. They are not evidence the model is safe. The report says so next to the
number, not in a footnote.

Three further limits are recorded beside it:
- **No tool call after the injection.** In all 30 trials the model made no tool call at all
  after reading the injection, so the run cannot distinguish "refused to act" from "acted
  without leaking".
- **A clause with no referent.** The template's exfil clause asked for private data the task
  never read.
- **Not reproducible.** 25 distinct provider `system_fingerprint` values appeared across 84
  responses inside one campaign of 7 min 54 s. A seed sent is not determinism, and a re-run is a
  new measurement, not a repeat.

---

## The defect I found in my own tool, and the release I blocked

The ship surface was built — CI gate, GitHub Action, installers, version `0.1.0a1` — and 1,872
tests were green on both operating systems. The next step was the release tag.

Before tagging, I installed the packaged tool (`uv tool install .`) and ran it from my own home
directory instead of the repo. `discover` printed Cursor's user-scope config and its
project-scope config **as the same file**.

That is what the real run showed: two scopes, one path. Cursor reads a user-scope config and a
project-scope config. When the project directory *is* the home directory, those are one file.
The code kept both entries. That is correct when the paths differ, and wrong when they are one
file.

Then I measured what it costs, on the committed fixture rather than my machine. I put the toxic
fixture's two servers at `<home>/.cursor/mcp.json`, made the project directory the home
directory, and scanned:
- **4 entries, 16 flows, 16 groups**, against **2, 3 and 3** for the same file scanned once;
- every server counted twice, and the flow graph then paired the duplicates with each other, so
  the error was worse than double;
- neither mechanism built to catch dropped or shadowed servers fired, because nothing was
  dropped.

Three things about this matter more than the bug.

**No test would have caught it.** 1,872 tests, including mutation tests, and none of them ran the
installed tool from a home directory. The defect was found by *using* the product, not by
testing it.

**I measured it before fixing it.** The 4 / 16 / 16 figures are now the assertion in the
regression test, and a mutant that removes the fix is killed by reproducing exactly 4, 16, 16.

**I blocked my own release.** The fix was not deferred to a backlog row. The whole project rests
on one claim — that it does not produce false numbers — and shipping a release that reports 16
where 3 exist would have contradicted it. Documenting a known false number is not the same as not
shipping one.

**How the fix works.** It compares canonical paths, following links and folding case where the
operating system is case-insensitive.
- **What was measured on a real Windows machine, not assumed:** case folding (a differently
  cased project path) and a junction to the home directory.
- **The POSIX branch** (a symlink collapses; differently cased paths stay distinct) runs only on
  Linux. In CI run `45906223082` on `4740df3`, the test that checks it (`test_case_and_links_resolve_to_one_file`) carries no skip marker, was neither skipped nor failed, and takes the POSIX branch whenever `sys.platform` is not `win32`, so that branch ran on ubuntu-24.04. **This is an inference from the test's structure, not a quoted result:** CI runs `pytest -q -rs`, which prints no line naming the test, and the measured values it checks are not in the log.
- **The collapse is never silent.** Silently dropping a config is the same class of error as
  double-counting: a number that moved for a reason the report does not state. So the report
  names every collapse: which config was kept, which was folded into it, and the path they
  share. A mutant that makes the collapse silent is killed too.

---

## Three decisions worth defending

**No LLM judge, anywhere in evaluation.** A model deciding whether another model was compromised
introduces a second unquantified error term into the only number that matters. The oracle is
deterministic string and structure matching, and its cost is coverage: an exfiltration encoded in
a way the matcher does not model is a miss. That cost is measurable. A judge's bias is not.

**Twins, not real servers.** Attacking a third-party server would produce a sharper result and
could harm its users. The twin keeps the tool schemas identical and the data synthetic.
- A pure sink call is never forwarded.
- A dual-role call is forwarded only to a twin that passed the AST no-I/O guard, which is not a
  sandbox.
- The cost, stated honestly: one canned response per tool, so arguments are validated but never
  varied on.

**Fix writes patches; it never applies them.** A security tool that edits a user's client config
is one bug away from breaking their environment. The patch is a reviewable file, and the Claude
Code fragment is headed FOR REVIEW because its rule syntax is not fully re-verified — a wrong
rule would apply cleanly and protect nothing, which is worse than no rule at all.

The same discipline runs through Verify. **A mitigation's rate falling to zero is not, on its
own, a fix.** Every verify row reports three figures with three denominators — rate, exposure
and utility — plus a label naming the mechanism:
- **Flow blocked.** On one template, removing the sink's server zeroed the rate while exposure
  and utility held. That is a real fix.
- **Delivery removed, capability removed, NOT a fix.** On another template, the attacked tool,
  the task's tool and the sink were all the same tool. The rate also went to zero, but so did
  exposure and utility: the tool was simply turned off.

Both numbers moved the same way; only one of them means anything.

---

## What this does not do

- No real positive, for any rule. The oracle's rules are validated against fixtures I authored,
  which shows they match my model of the attack — not that they catch real model behaviour.
- One model, one tier, one template, n=10 per source.
- Verify has only ever run against a scripted control, never a real model.
- The approval-based mitigation has never been tested in a real client.
- The classifier cannot label a filesystem read tool as an untrusted source, so `scan` cannot
  discover file-borne injection at all. Measured: 0 such flows without a manual override, 11 with
  it. Recorded as a Find-stage defect.
- Held-out classifier recall is weak and honest about it: sink recall 16 of 25, private-data
  recall 4 of 20, and 10 of 13 rules never exercised.
- The GitHub Action classifies from config text only. On the toxic fixture it sees 3 of 16 flows
  and misses 13. It is a tripwire for a dangerous new pairing, not a proof.
- The default install route, from the git tag, has run once, locally on my own Windows machine,
  as the bare `uv tool install` command: 38 packages, `proveflow 0.1.0a1`. It has not run in CI
  or on a clean machine.
- Nothing is on PyPI.

---

## What it stands on

- **The test suite.** 1,879 tests collected, green in CI run `45906223082` on `4740df3`: Ubuntu
  1,858 passed and 21 skipped, Windows 1,873 passed and 6 skipped.
  - 225 mutation test functions (287 collected, with parametrisation); the newest 11 name the
    exact line they kill.
  - Property tests on redaction.
  - Safety tests that prove `discover`, `scan` and `fix` never modify a user's config.
  - A guard that proves the injection-obeying test instrument, which does ship in the package,
    is imported by nothing under `src/` except the verify command.
- **The install evidence.** An installer run in a bare `ubuntu:24.04` container with `python3`,
  `python`, `uv` and `curl` all absent (CI run `45906223124`). It bootstrapped its own
  toolchain, installed 36 wheels with no package index at all, matched its version and exited 0.
- **Traceability.** Every published figure is traceable to a run, with what it does not
  establish written beside it.

---

**Repository:** https://github.com/M-Haris346/proveflow
**Full design and phase plan:** `docs/ARCHITECTURE.md`
**The campaign result:** `docs/results/groq_forced_7db7eff3b652.md`
**Everything still open, with measurements:** `docs/BACKLOG.md`
