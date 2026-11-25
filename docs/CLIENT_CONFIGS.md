# Verified MCP client config facts

> Every fact below was read from the linked official documentation on the access date shown.
> Nothing here is from memory or third-party blogs. Discovery readers (Phase 1) must cite the
> relevant row here; if a row is missing or stale, update this file first.
>
> **Access date for all rows: 2026-11-10.**

## 1. Claude Desktop

Source: <https://modelcontextprotocol.io/quickstart/user> (official MCP docs, demonstrates Claude Desktop).

| OS | Config path |
|---|---|
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Linux | `~/.config/Claude/claude_desktop_config.json` |

JSON shape (stdio):

```json
{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "C:\\Users\\username\\Desktop"],
      "env": { "BRAVE_API_KEY": "..." }
    }
  }
}
```

Notes: `env` holds raw secret values in the user's file — redaction at read time is mandatory.
MCP logs: Windows `%APPDATA%\Claude\logs`, macOS `~/Library/Logs/Claude`, Linux `~/.config/Claude/logs`.

## 2. Claude Code

Source: <https://code.claude.com/docs/en/mcp>.

| Scope | File | Shared |
|---|---|---|
| Local (per-project, private) | `~/.claude.json` under `projects["<project path>"].mcpServers` | no |
| Project | `.mcp.json` in project root | yes (git) |
| User (all projects) | `~/.claude.json` top-level `mcpServers` | no |

Precedence (highest first): local → project → user → plugin-provided → claude.ai connectors.
Official rule: "When the same server is defined in more than one place, Claude Code connects to
it once, using the definition from the highest-precedence source. The entire server entry from
that source is used; fields are not merged across scopes."

JSON shapes:

```json
{
  "mcpServers": {
    "stdio-example": {
      "command": "npx",
      "args": ["-y", "@example/mcp-server"],
      "env": { "API_KEY": "..." }
    },
    "http-example": {
      "type": "http",
      "url": "https://mcp.example.com/mcp",
      "headers": { "Authorization": "Bearer ..." }
    }
  }
}
```

Other documented fields: `type: "ws"` (WebSocket), `timeout` (ms per tool call), `headersHelper`,
`oauth`, `authServerMetadataUrl`, `envFile`-like helpers are NOT documented for Claude Code.

### Permission rule syntax (mitigation M3)

Source: <https://code.claude.com/docs/en/permissions>.

Rules live in `permissions.allow` / `permissions.ask` / `permissions.deny` arrays in:
`~/.claude/settings.json` (user), `.claude/settings.json` (project), `.claude/settings.local.json`
(local), and managed settings.

MCP tool rule syntax (quoted from the docs):

- `mcp__<server>` — any tool provided by that server (deny/ask; as an allow rule for servers whose
  name contains `__` this form is misread, see below)
- `mcp__<server>__*` — wildcard form, all tools from the server
- `mcp__<server>__<tool>` — one specific tool (e.g. `mcp__puppeteer__puppeteer_navigate`)
- `mcp__*` — valid only as a **deny** rule (unanchored allow globs are skipped)
- Allow globs are accepted only after a literal `mcp__<server>__` prefix (e.g. `mcp__github__get_*`)
- MCP rules with parentheses (parameter matching) in settings files are **skipped**; parameter
  matching for MCP tools works only via `--disallowedTools` on the CLI
- Server-name normalization: `.` and spaces in a configured server name become `_` in the rule
  (server `my.server` → `mcp__my_server__*`)

Example M3 patch content (ask before a sink tool runs):

```json
{
  "permissions": {
    "ask": ["mcp__gmail__send_email"]
  }
}
```

**Re-read 2026-11-26 (Phase 8, before the M3 renderer was built).** The page was fetched (HTTP
200) but read VERBATIM only in part (about 40k of 95k characters); the rest came as a
model-extracted summary. What each item rests on:
- Verbatim on 2026-11-26: "Ask rules prompt for confirmation when Claude tries to use the
  specified tool."; "Rules are evaluated in order: deny, then ask, then allow."; "a matching
  ask rule prompts even when a more specific allow rule also matches the same call."; "When
  Claude Code loads a settings file, it skips any `mcp__` rule that has parentheses."; and the
  local settings file `.claude/settings.local.json`.
- NOT re-confirmed verbatim on 2026-11-26 (summary only): the rule forms
  `mcp__<server>__*` and `mcp__<server>__<tool>`; the `.`/space -> `_` normalisation; the user
  and project settings paths. These rest on the 2026-11-10 read above. The summary also says the
  bare `mcp__<server>` form appears only as an example, not as a documented pattern, so the M3
  renderer does NOT emit it: a server-level flow gets `mcp__<server>__*`.
- No "ask" JSON example and no page date were found in the verbatim part.
- **Why `mcp__<server>__*` and not the bare `mcp__<server>`:** the 2026-11-26 summary says the
  bare form appears on the page only as an example, not as a documented pattern. The wildcard
  form is listed as a pattern in both the 2026-11-10 read and the 2026-11-26 summary.
- **OPEN, HIGH (docs/BACKLOG.md, Phase 8):** a full verbatim re-read of the MCP rule forms, by
  hand, before M3 is relied on. Until then every M3 patch starts with a FOR REVIEW header
  stating this.

### JSON Patch and JSON Pointer (mitigation M1, Phase 8)

Sources, read 2026-11-26: RFC 6901, "JavaScript Object Notation (JSON) Pointer", April 2013,
<https://www.rfc-editor.org/rfc/rfc6901>; RFC 6902, "JavaScript Object Notation (JSON) Patch",
April 2013, <https://www.rfc-editor.org/rfc/rfc6902>.

- Escaping (RFC 6901 section 3): "'~' needs to be encoded as '~0' and '/' needs to be encoded as
  '~1' when these characters appear in a reference token." Decoding (section 4) transforms '~1'
  first, then '~0'. proveflow escapes '~' before '/' (`fix.pointer.escape`), the inverse order.
- A patch document (RFC 6902 section 3): "A JSON Patch document is a JSON [RFC4627] document that
  represents an array of objects." "Each object represents a single operation to be applied to
  the target JSON document."
- "remove" (RFC 6902 section 4.2): "The "remove" operation removes the value at the target
  location." "The target location MUST exist for the operation to be successful." So an M1 patch
  for an entry that is already gone fails, which is the intended loud failure.

## 3. Cursor

Source: <https://cursor.com/docs/context/mcp>.

| Scope | File |
|---|---|
| Project | `.cursor/mcp.json` in project root |
| Global/user | `~/.cursor/mcp.json` |

The docs state no OS-specific path differences. JSON shapes:

```json
{
  "mcpServers": {
    "stdio-example": {
      "command": "python",
      "args": ["mcp-server.py"],
      "env": { "API_KEY": "value" },
      "envFile": ".env"
    },
    "remote-example": {
      "url": "http://localhost:3000/mcp",
      "headers": { "API_KEY": "value" }
    }
  }
}
```

`envFile` is stdio-only. Remote servers use shell/system env interpolation instead.
Cursor permission/deny syntax for individual MCP tools: **not found in the fetched page** —
marked [research]; re-check before implementing an M3 renderer for Cursor.

## 4. VS Code (Copilot MCP)

Source: <https://code.visualstudio.com/docs/copilot/chat/mcp-servers>.

| Scope | File |
|---|---|
| Workspace | `.vscode/mcp.json` |
| User profile | `mcp.json` in the VS Code user profile (open via **MCP: Open User Configuration**); lives in the VS Code user data dir, which varies per OS |
| Workspace root (experimental) | `.mcp.json` |

**Caution:** VS Code uses a top-level `"servers"` key — NOT `"mcpServers"`:

```json
{
  "servers": {
    "playwright": {
      "command": "npx",
      "args": ["-y", "@playwright/mcp@latest"],
      "env": {}
    },
    "context7": {
      "url": "https://mcp.context7.com/mcp",
      "headers": {}
    }
  }
}
```

VS Code supports input variables for secrets in workspace/user configs. The exact per-OS user
profile path was not spelled out on the fetched page — the Phase 1 reader should resolve the
user config via the VS Code user data directory convention and this is marked **[research]**
until verified against the VS Code docs page that lists user-data-dir paths.

## 5. Windsurf (now Devin; docs redirect to docs.devin.ai)

Source: <https://docs.devin.ai/windsurf/plugins/cascade/mcp> (redirect target of
docs.windsurf.com, 2026-11-10).

| Scope | File |
|---|---|
| New (Devin) config | Windows `%APPDATA%/devin/mcp_config.json`; macOS/Linux `~/.config/devin/mcp_config.json` (or `$XDG_CONFIG_HOME/devin/mcp_config.json`) |
| Legacy editor discovery file | `~/.codeium/windsurf/mcp_config.json` (stable), `~/.codeium/windsurf-next/mcp_config.json` (Next) |

JSON shapes:

```json
{
  "mcpServers": {
    "github": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": { "GITHUB_PERSONAL_ACCESS_TOKEN": "<token>" }
    },
    "remote-http-mcp": {
      "serverUrl": "https://example.com/mcp",
      "headers": { "API_KEY": "value" }
    }
  }
}
```

Remote servers use `serverUrl` (the docs mention `url` as an alternative). Env interpolation:
`${env:VARIABLE_NAME}`.

## Reader implications (Phase 1)

- Three distinct top-level keys exist in the wild: `mcpServers` (Claude Desktop/Code, Cursor,
  Windsurf), `servers` (VS Code), and Claude Code's nested `projects.<path>.mcpServers`.
- URL field names differ: `url` (Claude Code, Cursor, VS Code) vs `serverUrl` (Windsurf).
- Secrets appear in `env`, `headers`, and sometimes inside `args` — all three must be redacted.
- Open items marked [research] above: Cursor per-tool permission syntax; VS Code user-profile
  mcp.json exact per-OS path.

## Phase 1a research notes (2026-11-10)

- **VS Code** — <https://code.visualstudio.com/docs/copilot/reference/mcp-configuration>
  (accessed 2026-11-10): `servers` top-level key confirmed; `type` values `stdio`, `http`, `sse`
  ("first tries the HTTP Stream transport and falls back to SSE"); `envFile` "is supported in the
  VS Code format, not in portable `.mcp.json`"; `inputs` array for sensitive values. The page
  **does not say** whether comments (JSONC) are allowed, so the reader parses strict JSON and a
  file with comments is reported `parse_error`. It gives **no per-OS user-profile path**, so the
  user config stays [research] and is reported `unsupported`. The experimental workspace
  `.mcp.json` format is not verified either and is reported `unsupported`.
- **Claude Code `projects` keys** — the key format in `~/.claude.json` (slash direction, case on
  Windows) is not documented. proveflow normalizes it (slashes unified, trailing slash dropped,
  case-folded on Windows) before matching `--project`. [research: interpretation]
- **`~`** in all docs is read as `Path.home()` (USERPROFILE on Windows). [interpretation]
- **Precedence** is documented only for Claude Code. For Cursor (user vs project) and Windsurf
  (new vs legacy file) it is not, so proveflow keeps all entries (Cursor) or makes one profile
  per file (Windsurf) instead of guessing. [research]
- **Variables** (accessed 2026-11-11; code: `src/proveflow/discover/variables.py`). proveflow
  never expands them, and a server whose launch values reference any variable is **not
  launched** (`unresolved_variables`):
  - Claude Code (<https://code.claude.com/docs/en/mcp>): `${VAR}` and `${VAR:-default}` in
    `command`, `args`, `env`, `url`, `headers`. When unset without a default, "the config still
    loads ... and uses the unexpanded `${VAR}` text as-is".
  - Cursor (<https://cursor.com/docs/context/mcp>): `${env:NAME}`, `${userHome}`,
    `${workspaceFolder}`, `${workspaceFolderBasename}`, `${pathSeparator}`, `${/}` in `command`,
    `args`, `env`, `url`, `headers`.
  - VS Code (<https://code.visualstudio.com/docs/copilot/reference/mcp-configuration>):
    `${input:...}` (prompted on first start), `${env:...}`, predefined variables such as
    `${workspaceFolder}`/`${userHome}`, and `${NAME}` / `${NAME:-default}` in portable files.
    Unresolvable variables: not stated.
  - Windsurf (<https://docs.devin.ai/windsurf/plugins/cascade/mcp>): `${env:VAR}` in `command`,
    `args`, `env`, `serverUrl`, `url`, `headers`.
  - Claude Desktop (<https://modelcontextprotocol.io/quickstart/user>): no expansion is
    documented. Any `${...}` is reported as `<undocumented ${...} syntax>` and is not launched
    (fail safe), as for `--servers` files.
- **cwd for stdio servers**: only VS Code documents one (the workspace folder). See
  docs/PROCESS_KILL.md §4 for proveflow's choice (an empty temp dir) and the gap.
