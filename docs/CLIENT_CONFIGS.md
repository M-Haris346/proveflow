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
