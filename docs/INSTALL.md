# Installing proveflow (Phase 9)

There are two install routes. Neither is a PyPI release: proveflow is not on PyPI (by ruling,
2026-11-26).

## Route 1: the default (what a user gets)

```sh
sh install/install.sh                                            # Linux / macOS
powershell -ExecutionPolicy ByPass -File install\install.ps1     # Windows
```

- Installs proveflow **from its git tag** `v0.1.0a1`:
  `uv tool install "git+https://github.com/M-Haris346/proveflow@v0.1.0a1"`.
- Dependencies come **from PyPI**, resolved normally.
- proveflow itself comes from git and never from an index, so no other package named
  "proveflow" can be picked up on this route.
- If `uv` is absent, the installer first runs uv's official installer at a PINNED version
  (`0.13.10`), into `~/.local/bin` (`UV_INSTALL_DIR`), without editing shell profiles
  (`UV_NO_MODIFY_PATH=1`).
- Afterwards it checks that `proveflow` is on PATH and prints the installed version. Any
  failure exits non-zero with a readable message.
- **Measured once, 2026-11-27, LOCAL:** on Haris's own Windows machine, which is not in CI and
  not a clean machine, `uv tool install git+https://github.com/M-Haris346/proveflow@v0.1.0a1`
  (the command the installers wrap, run directly, not through `install.ps1`):
  - resolved 38 packages;
  - built proveflow from the tag at `4740df3`;
  - reported `proveflow 0.1.0a1`;
  - uninstalled cleanly.
  - It succeeded BEFORE main was pushed to `4740df3`. A tag carries its own objects, so this
    route depends on the TAG existing, not on main pointing at the commit.
- **What this route does NOT prove:**
  - it has NOT been run by CI, and the installer scripts themselves have not been run on this
    route; the one run above is the bare `uv tool install` command, on one local machine;
  - it needs network access to PyPI and GitHub, and its dependency versions are whatever PyPI
    resolves at install time (not the repo's `uv.lock`);
  - whether uv needs the `git` executable for a git source is not stated in the uv pages read.

## Route 2: the wheelhouse (the CI evidence)

```sh
sh install/install.sh --wheelhouse DIR
powershell -ExecutionPolicy ByPass -File install\install.ps1 -Wheelhouse DIR
```

- `DIR` holds proveflow's wheel AND every runtime dependency wheel.
- The installer runs `uv tool install "proveflow==0.1.0a1" --find-links DIR --no-index`: **no
  package index at all**.
- `.github/workflows/install.yml` builds the wheelhouse per OS:
  - `uv build --wheel`;
  - `uv export --locked --no-dev --no-emit-project`, with hashes;
  - `pip download -r requirements.txt --only-binary :all: -d wheelhouse`. Hash checking is
    implied because the requirements carry hashes.
- It then runs the real installer with the wheelhouse, and asserts the version and that
  `proveflow scan --help` exits 0:
  - **linux**: a bare `ubuntu:24.04` container, with no Python and no uv. Only `curl` and
    `ca-certificates` are added, and the log records it;
  - **windows**: the `windows-2025` hosted runner. It is **NOT a clean machine** (it ships
    Python and other tools), and the log records whether uv was preinstalled.
- **What this route proves:** the package and all its dependencies resolve and install from
  the wheelhouse alone, with no package index, on both OSes.
- **What it does NOT prove:**
  - the default route (Route 1);
  - a clean Windows machine;
  - that the job was offline: it downloads uv and a Python interpreter from the network.
    `--no-index` covers packages only;
  - the job pins `UV_PYTHON=3.12` because the wheelhouse holds cp312 wheels. That setting is
    verified by the job's own run, not cited.
- Measured locally once, 2026-11-26, Windows: the same three build commands produced 38 wheels,
  and `install.sh --wheelhouse` installed `proveflow 0.1.0a1` with `scan --help` exit 0.
- **The CI run that is the evidence is cited in the README once it has run.**

A correction, recorded as Haris's error (2026-11-26): an earlier ruling asked for `--find-links
<one wheel's directory> --no-index`. `--no-index` ignores the registry for EVERY package, so
with only proveflow's wheel the dependencies cannot resolve. The full wheelhouse above is the
form that installs.

## Exit codes (`proveflow scan`)

| code | meaning |
|---|---|
| 0 | clean: no flow matched `--fail-on` (or no `--fail-on` given) |
| 1 | proveflow's own usage or config error. Under `--fail-on` this includes ANY config it could not read (parse error, unreadable, invalid entries): never a pass, never a finding |
| 2 | Click's own usage error (e.g. a missing `--servers` path). Pre-existing and overloaded: the not-implemented stub commands also exit 2 |
| 3 | findings: a flow matched `--fail-on` |

Without `--fail-on`, the exit code does not change, but the terminal names every config the
scan could not read, on stderr. The JSON report does not carry config statuses yet (docs/BACKLOG.md,
HIGH).

## Version

`[project].version` is STATIC, `0.1.0a1`. It is a **package version, never a commit
identifier**, and it was never meant to be one. `proveflow_version` in cassettes, scan reports
and trial records means exactly that. A release tag must equal it: `.github/workflows/tag.yml`
runs `scripts/check_tag_version.py`. The commit behind a published result is recorded by hand in
its provenance block in `docs/results/`.

## Sources (read 2026-11-26)

- **uv installer** (<https://docs.astral.sh/uv/getting-started/installation/>,
  <https://docs.astral.sh/uv/reference/installer/>):
  - "Request a specific version by including it in the URL:" `curl -LsSf
    https://astral.sh/uv/0.13.10/install.sh | sh`;
  - "To change the installation path, use `UV_INSTALL_DIR`";
  - "To disable this behavior, use `UV_NO_MODIFY_PATH`".
- **uv tools** (<https://docs.astral.sh/uv/concepts/tools/>, <https://docs.astral.sh/uv/reference/storage/>):
  - "Tool executables are symlinked into the executable directory on Unix and copied on
    Windows";
  - "Use `uv tool dir --bin` to show the tool executable directory".
- **uv git references** (<https://docs.astral.sh/uv/pip/packages/>): "To install a package from
  GitHub at a specific reference:", with examples `git+https://github.com/astral-sh/ruff@main`
  and `@<commit>`.
- **uv tool install** (<https://docs.astral.sh/uv/reference/cli/#uv-tool-install>):
  - `--find-links`: "Locations to search for candidate distributions, in addition to those found
    in the registry indexes." "If a path, the target must be a directory that contains packages
    as wheel files (`.whl`) or source distributions";
  - `--no-index`: "Ignore the registry index (e.g., PyPI), instead relying on direct URL
    dependencies and those provided via `--find-links`".
  - The page does NOT state that the PACKAGE argument accepts a path to a single `.whl`, so the
    installers never pass one.
- **uv export** (<https://docs.astral.sh/uv/reference/cli/#uv-export>):
  - "Export the project's lockfile to an alternate format.";
  - `--format` "Otherwise, defaults to `requirements.txt`";
  - `--no-emit-project`: "Do not emit the current project."
- **pip download** (<https://pip.pypa.io/en/stable/cli/pip_download/>):
  - "`pip download` does the same resolution and downloading as `pip install`";
  - `--only-binary`: "Do not use source packages.";
  - `--require-hashes`: "This option is implied when any package in a requirements file has a
    --hash option."
- **GitHub Actions** (docs.github.com, workflow syntax):
  - container jobs: "If you are using GitHub-hosted runners, you must use an Ubuntu runner";
  - `continue-on-error`: "Prevents a job from failing when a step fails";
  - `steps.<id>.outcome`: "The result of a completed step before continue-on-error is applied".
