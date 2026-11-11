# PF-UNPINNED: servers fetched at launch without an exact version [impl][tested]

> A stdio server started as `npx <pkg>`, `uvx <pkg>` or `pipx run <app>` is downloaded and
> resolved **at every launch**. Without an exact version, the code your agent runs can change
> with no change to your config. PF-UNPINNED is a **note** (SARIF level `note`), not a vulnerability.
> It is a static check of the config: no network, no registry lookup. Code:
> `src/proveflow/flows/pinning.py`. Tests: `tests/unit/test_pinning.py`,
> `tests/mutation/test_pinning_mutation.py`. All sources accessed 2026-11-11.

Only the forms in the tables below are parsed. Anything else is reported as **`unknown`** (with
the reason), never guessed. Only plain (unredacted) argument segments are inspected. A package
argument that contains a redacted segment is `unknown`.

## npx

| Form | Status | Source |
|---|---|---|
| `npx -- <pkg>[@<version>] [args...]`; the package is "the first positional argument" | parsed | <https://docs.npmjs.com/cli/v11/commands/npx> |
| `-p/--package <spec>` (repeatable) "prevent[s] npm from inferring the package from the first command argument" | every `-p` spec must be pinned | same |
| `-y/--yes`, `--no` | skipped | same |
| `<pkg>` with no version | **unpinned**: npm's `tag` config (default `latest`) applies: "If you ask npm to install a package and don't tell it a specific version, then it will install the specified tag." | <https://docs.npmjs.com/cli/v11/using-npm/config> |
| `<pkg>@<tag>` (e.g. `@latest`, `@next`) | **unpinned** | <https://docs.npmjs.com/cli/v11/using-npm/package-spec> |
| `<pkg>@<version range>` (e.g. `@^1.2.0`) | **unpinned** | same |
| `<pkg>@<version>`, an exact SemVer 2.0.0 version (rules 2, 9, 10: `X.Y.Z` without leading zeros, optional `-pre` and `+build`) | **pinned** | <https://semver.org/spec/v2.0.0.html> |
| alias `<alias>@npm:<name>`; folder (`./…`, `/…`); tarball file/URL; git: full URLs (`https://….git`, `git@github.com:…`, `git+ssh://…`), the `github:` shorthand, `<user>/<project>`, anything with `#ref` | **unknown** | package-spec page (Git URLs: "a full git url, git shorthand, or a username/package on GitHub … appending `#ref`") |
| a registry name that merely *starts* with `git` (e.g. `github-mcp`, `gitlab-mcp`) | parsed as a normal registry package | same |
| any other option before the package | **unknown** | n/a |

## uvx

| Form | Status | Source |
|---|---|---|
| `uvx <command>` (no version) | **unpinned** | <https://docs.astral.sh/uv/guides/tools/> |
| `uvx <command>@latest` | **unpinned** ("To run a tool at the latest version, use `command@latest`") | same |
| `uvx <command>@<version>` | **pinned** ("the `@` syntax cannot be used for anything other than an exact version") | same |
| `uvx --from '<pkg>==X' <command>` | **pinned** (PEP 440 `==` without `.*` is "exactly the same", `===` is arbitrary equality) | uv guide; <https://packaging.python.org/en/latest/specifications/version-specifiers/> |
| `uvx --from '<pkg>>X,<Y'`, `'<pkg>==1.*'` | **unpinned** (a range or prefix match) | same |
| `--with <req>` | value skipped | uv guide |
| VCS / URL / path requirement in `--from` or as the command (`git+https://…`, `pkg @ https://…`, `./dir`) | **unknown** | uv guide; PEP 440 does not cover them |
| any other option (e.g. `--python`) | **unknown** | n/a |

## pipx

| Form | Status | Source |
|---|---|---|
| `pipx run <app>` | **unpinned**: the docs say it can "Run the latest version of any app in a temporary environment", and "pipx caches each `pipx run` environment for 14 days … After the cache expires, the next run fetches the latest version." | <https://pipx.pypa.io/stable/>, <https://pipx.pypa.io/stable/tutorial/run-applications.html> |
| `pipx run --spec <pkg>==X <app>` | **pinned** (PEP 440, as above) | run-applications tutorial |
| `pipx run --spec <pkg> <app>` (no version) | **unpinned** | same |
| other pipx subcommands (`install`, …) | not checked | n/a |

## Launchers NOT checked

`docker run …`, `bunx`, `pnpm dlx`, `yarn dlx`, `uv tool run` (the long form of `uvx`), `npm exec`, and anything else produce no PF-UNPINNED finding at all. That means "not checked", not "pinned".

## Limits (stated)

- A pin is a name plus an exact version, not an integrity hash. Registry-side compromise of a
  pinned version is out of scope.
- The config is all that is checked. A lockfile or a global install that the launcher might
  resolve to locally is not inspected. The npx docs say a package without a specifier "will be
  matched with whatever version exists in the local project" when there is one.
