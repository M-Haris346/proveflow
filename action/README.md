# proveflow scan gate (GitHub Action)

A **static** CI check that **fails the job when an MCP servers config holds a toxic flow** of
the class you choose. It runs `proveflow scan --no-launch --fail-on <class>` on one servers file
and never launches a server.

```yaml
- uses: actions/checkout@<pinned sha>
- uses: M-Haris346/proveflow/action@<pinned sha>
  with:
    servers: .mcp.json        # an MCP servers JSON file (mcpServers or servers shape)
    fail-on: exfil            # exfil | action | leak | any   (default: exfil)
    sarif: proveflow.sarif    # optional: also write SARIF 2.1.0
```

Outputs: `exit-code` (see below) and `flows` (the number of flows in the report).

## What it classifies from: the config only

The Action passes `--no-launch`, so **no server is started and no tool list is read**. The role
classifier sees only what the config carries:
- the server's **name** (its key in the file);
- its **command line**: `command`, `args` and, for remote servers, the URL. Only the plain
  parts count: secret-shaped values are redacted when the file is read, and never classified
  (`flows/server_roles.py` `server_tokens`).

It also reads the scanned workspace's own client config files, `.mcp.json`, `.cursor/mcp.json`
and `.vscode/mcp.json`, if present, and the runner's own home client configs (normally none). It never reads a tool's name, description or input schema,
because it never asks a server for them.

`--no-launch` is the ONLY mode, on purpose. A gate that launched the scanned repository's
servers on `pull_request` would run untrusted pull-request code in CI.

## What it reports: THEORETICAL flows, and only those

Every flow this Action reports is **THEORETICAL**: a static pairing of server roles guessed
from names and command lines. It is never introspected, and never proven by an attack. A flow
here means "these servers together could form a toxic flow", not "this flow is exploitable".

## What it misses: measured, and expected

**It WILL MISS flows that an introspected scan finds. That is expected, not a bug.** Measured
on the committed fixtures, by `tests/integration/test_action_blind_spot.py`
(`shipchecks.assert_the_action_is_blind_where_measured`), which scans each fixture both ways:

| fixture (`tests/fixtures/action/`) | flows with `--no-launch` (what the Action sees) | flows introspected (the servers' real tool lists) |
|---|---|---|
| `clean.servers.json` | 0 | 0 |
| `blind_spot.servers.json` | **0** | **3** (tool-level) |
| `toxic.servers.json` | **3** (server-level) | **16** (tool-level) |

- On the toxic fixture the Action sees 3 of the 16 flows an introspected scan finds: **it
  misses 13 of 16**. Its 3 are server-level guesses; the 16 are tool-level.
- On the blind-spot fixture it reports **0** on a config that an introspected scan finds **3**
  flows in. A green Action run is NOT evidence that a config is safe.
- The introspected numbers come from the repo's own fake MCP server (its `tools/list`), not
  from any real server.

## What it is for

Catching a **config change that introduces a dangerous server pairing**: for example, a pull
request that adds a server which can send data out to a config that already holds one that reads
private data. It is a tripwire on the config. It does not prove a flow, does not find flows
hidden in tool lists, and does not judge whether a server is safe. For those, run `proveflow
scan` with introspection on a machine you trust (`proveflow scan --help`).

## Exit codes (`exit-code` output)

| code | meaning |
|---|---|
| 0 | clean: no flow of the chosen class |
| 1 | proveflow's own usage or config error, **including any config it could not read**. An unreadable or malformed file is NEVER a pass and NEVER a finding |
| 2 | Click's own usage error (e.g. a missing file path). Pre-existing: the not-implemented stub commands also exit 2 |
| 3 | findings: at least one flow of the chosen class |

The self-test, `.github/workflows/action.yml`, runs this Action on the three fixtures on
ubuntu-24.04 and windows-2025:
- clean and blind-spot must pass;
- toxic must fail with exit 3, 3 flows and at least one SARIF result.

All actions it uses are pinned by full commit SHA.
