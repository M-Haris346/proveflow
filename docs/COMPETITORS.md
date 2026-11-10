# Competitor / adjacent-tool comparison

> Honest table. Summaries derive from the 2026-11 research pass recorded in ARCHITECTURE §2 and
> each project's own repository/README (links below). Rows marked [research] were not re-fetched
> on 2026-11-10; re-verify a row before citing it in any published comparison.
> "What they do better" is filled in deliberately — pretending competitors are weak is lying.

| Tool | What it does | What proveflow does differently | What they do better |
|---|---|---|---|
| Snyk agent-scan (ex-Invariant mcp-scan) — <https://github.com/snyk/agent-scan> [research] | Discovers installed MCP configs, static toxic-flow analysis, vendor-backed | Adds dynamic proof on a schema twin of *your* setup, fix patches, measured re-verification | Vendor resources, polish, breadth of static checks, enterprise distribution |
| SrihaasaK/mcp-red-team — <https://github.com/SrihaasaK/mcp-red-team> [research] | Dynamic injection harness: proxy, deterministic oracle, confidence intervals — on its own mock servers | Attacks flows discovered from the user's real installed setup, twins generated from real schemas; fix + verify loop | Earlier mover on the deterministic-oracle + CI methodology |
| rishii-hub/mcp-tripwire — <https://github.com/rishii-hub/mcp-tripwire> [research] | Proxy + CI gate for injection attempts | Full find→prove→fix→verify pipeline rather than a gate; stats + paired verification | Simpler to drop into a CI pipeline today |
| Nikita3005/taintgate, rudratoshs/taintgate [research] | Provenance/taint gates blocking tainted sink calls (defense) | proveflow *measures* whether such defenses work (M4 is this class of mitigation, verified in twin) | They are a runtime defense; proveflow deliberately is not |
| antgroup/Agent3Sigma-Canary [research] | Research framework for agent attack evaluation, LLM judge | Deterministic oracle (no LLM judge for primary verdicts), targets user's real tool surface | Research depth, scale of experiments |
| agentprobe / mcpsafe [research] | Agent/MCP probing utilities | End-to-end measured pipeline with stored, reproducible runs | — (to be assessed honestly when re-fetched) |
| spikee — <https://github.com/WithSecureLabs/spikee> [research] | General prompt-injection test kit (payload generation) | MCP-setup-specific flows, twins, paired stats; spikee could be a payload source later | Mature payload/encoding generation breadth |
| Promptfoo (OpenAI-owned since 2026-03) — <https://www.promptfoo.dev> [research] | LLM eval + red-team platform, huge ecosystem | Setup-specific toxic-flow proof, not generic prompt evals; local-first, no account | Ecosystem, UI, team features, scale |
| Claude Code built-ins — <https://code.claude.com/docs/en/permissions> (verified 2026-11-10) | Permission rules (allow/ask/deny incl. `mcp__server__tool`), auto-mode classifier, bash sandbox, `/security-review`, managed MCP allowlists. Anthropic docs state they do not security-audit MCP servers. | proveflow *tests* a setup before approval and renders M3 patches in exactly this permission syntax | Enforcement lives in the client itself — the right place for runtime control |

## Position (one sentence)

No tool we found closes the bridge *static finding on your real setup → safe dynamic proof →
fix → measured re-verification*; each neighbor does one segment.
