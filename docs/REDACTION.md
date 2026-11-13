# Redaction rules [impl][tested]

> Security-critical. proveflow reads MCP client configs, and those files contain secrets.
> Redaction happens **at read time**: raw values never reach a serializable model, log,
> report, SARIF file, or (later) cassette or LLM prompt. Code: `src/proveflow/discover/redact_rules.py`
> and `src/proveflow/discover/_common.py`. Tests: `tests/unit/test_redact_rules.py`,
> `tests/mutation/test_redaction_mutation.py`, `tests/property/test_no_secret_in_outputs.py`.

## 1. What is always fully redacted

| Field | Rule |
|---|---|
| every `env` value | replaced by `RedactedValue` (sha256 prefix of 12 hex + length), whatever the key |
| every `headers` value | same |

Keys (env var names, header names) are kept, because they say what kind of credential is
present without revealing it.

A redacted value renders as `<redacted:sha256-xxxxxxxxxxxx>`. The prefix makes two equal
values recognizable as equal (e.g. the same token used in two configs), and it is how
checkpoint 1b detects that a config changed between `discover` and launch. Only 48 bits of
the hash are kept, so the prefix cannot be reversed into the value. A short, guessable secret
could in principle be confirmed by brute force against the prefix; that is an accepted
residual risk, and it only applies to someone who already has the output.

## 2. Pattern rules for free text (args, url, command, envFile path)

Free text is mostly harmless (`npx -y @modelcontextprotocol/server-github`), so only
matching segments are replaced. The result is a `RedactedText`: a sequence of plain strings
and `RedactedValue`s.

"Secret word" below means a name containing one of: `api_key`/`api-key`/`apikey`,
`access_key`, `private_key`, `key`, `token`, `secret`, `password`, `passwd`, `pwd`,
`passphrase`, `auth`, `credential`, `bearer`, `session`, `cookie`, `signature`, `sig`
(case-insensitive). Matching is by substring, so over-redaction happens (e.g. `--keyboard=x`
is redacted). That is deliberate: hiding a harmless value costs nothing.

| ID | Matches | Redacted part | Positive example | Negative example |
|---|---|---|---|---|
| `R-ARG-EQ` | `--<name>=<value>`, name has a secret word | value | `--api-key=S` | `--port=8080` |
| `R-ARG-NEXT` | a secret flag as its own arg (`--token`) | the **next** arg, unless it starts with `-` | `--token S` | `--port 8080`, `--token --verbose` |
| `R-ARG-ENVSTYLE` | `NAME=value` arg, NAME has a secret word | value | `-e GITHUB_TOKEN=S` | `-e LOG_LEVEL=debug` |
| `R-ARG-HEADER` | `<Name>: <value>` arg, Name has a secret word | value | `--header "X-Api-Key: S"` | `Accept: application/json` |
| `R-URL-USERINFO` | `scheme://user:pass@host` | `user:pass` | `https://admin:S@db.example.com` | `https://example.com/path` |
| `R-URL-QUERY` | query parameter whose name has a secret word | value | `?api_key=S` | `?region=eu&page=2` |
| `R-BEARER` | `Bearer` / `Basic` / `Token` followed by a token | the token | `Bearer S` | `bearer` alone |
| `R-ENTROPY` | standalone token ≥ 32 chars of `[A-Za-z0-9_-+/=]`, containing letters **and** digits, Shannon entropy ≥ 3.5 bits/char | whole token | 36-char random key as a positional arg | `@modelcontextprotocol/server-filesystem`, `C:\Users\example\Desktop`, `mcp-server-fetch==2026.1.14` |

Overlapping matches are merged. Every rule's positive and negative examples are in the code
and are tested. The mutation test removes each rule in turn and asserts that its positive
example then **leaks**, both through `redact_args` and through the real config normalizer.
This proves that no rule is redundant and that the leak check really detects a disabled rule.

`R-ENTROPY` also redacts long hex digests and UUID-like tokens. That is an accepted trade-off.

### Vendor-prefix rules

None in Phase 1. Token prefix formats (e.g. for GitHub or Slack) are external facts, and the
project rule is that those must come from cited vendor documentation. No such rule was added
without a citation. `R-ENTROPY` covers long random tokens regardless of their prefix.

## 3. Known limitations (stated, tested)

- **A short, low-entropy, unflagged positional secret is NOT caught**, e.g.
  `myapp hunter2pass`. `tests/unit/test_redact_rules.py::test_known_limitation_short_unflagged_positional_not_caught`
  pins this behaviour so nobody mistakes it for coverage. Put secrets in `env`, not in `args`.
- Server **names** and env/header **keys** are shown as written. They are treated as
  non-secret.
- The redacted output still contains file paths, including your home directory and user name.

## 4. Error paths

- JSON parse errors report only the parser message plus line and column, never file content.
- Malformed server entries report the field name, never the value.
- `proveflow.toml` validation errors use pydantic's `errors(include_input=False)`, so input
  values are never echoed.
- Typer tracebacks never render local variables (`pretty_exceptions_show_locals=False`, set
  explicitly; Typer docs say that has been the default since 0.23.0:
  <https://typer.tiangolo.com/tutorial/exceptions/>, accessed 2026-11-10).

## 5. leak_check review hints

`scripts/leak_check.py` lists "suspicious tokens" for human review: letter+digit runs of 16 or
more characters that are still visible in the output. It prints locations only, never the
token. These are hints, not findings. The redaction rules above do not change because of them.

**Known benign shape, not reported:** a string that is *exactly* a JSON-Schema meta-schema
URI. Many servers put one in each tool's `inputSchema.$schema`, and its path part (e.g.
`org/draft-07/schema`, 19 characters) looks like a token. The forms come from the official
meta-schema files, accessed 2026-11-13:
- draft-04: `"$schema": "http://json-schema.org/draft-04/schema#"`
  (<https://json-schema.org/draft-04/schema>)
- draft-07: `"$schema": "http://json-schema.org/draft-07/schema#"`
  (<https://json-schema.org/draft-07/schema>)
- 2019-09: `"$schema": "https://json-schema.org/draft/2019-09/schema"`
  (<https://json-schema.org/draft/2019-09/schema>)
- 2020-12: `"$schema": "https://json-schema.org/draft/2020-12/schema"`
  (<https://json-schema.org/draft/2020-12/schema>)

Either scheme and an optional trailing `#` are accepted. A string with anything else in it,
in `$schema` or elsewhere, is still reported. draft-03 and draft-06 were not checked, so they
are not in the list.
