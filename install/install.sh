#!/bin/sh
# proveflow installer (POSIX sh). Phase 9; docs/INSTALL.md cites every fact used here.
#
#   sh install.sh                      install proveflow v$PROVEFLOW_VERSION from its git tag,
#                                      dependencies from PyPI (the default route)
#   sh install.sh --wheelhouse DIR     install ONLY from DIR (a directory holding proveflow's
#                                      wheel AND every dependency wheel): --find-links DIR
#                                      --no-index, no package index at all (the CI evidence)
#
# If uv is not on PATH, it is installed first with uv's official installer at a PINNED version,
# into $HOME/.local/bin (UV_INSTALL_DIR), without editing shell profiles (UV_NO_MODIFY_PATH=1).
# Afterwards the script checks that `proveflow` is on PATH and prints its version; any failure
# exits non-zero with a readable message. Never sudo; user-local only.
set -eu

PROVEFLOW_VERSION="0.1.0a1"                 # == [project].version (CI checks the tag matches)
UV_VERSION="0.13.10"                        # pinned uv installer version
REPO_URL="https://github.com/M-Haris346/proveflow"

fail() { printf 'proveflow installer: ERROR: %s\n' "$1" >&2; exit 1; }
say() { printf 'proveflow installer: %s\n' "$1"; }

WHEELHOUSE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --wheelhouse)
      [ $# -ge 2 ] || fail "--wheelhouse needs a directory"
      WHEELHOUSE=$2; shift 2 ;;
    -h|--help)
      sed -n '2,14p' "$0"; exit 0 ;;
    *) fail "unknown argument: $1 (see --help)" ;;
  esac
done
if [ -n "$WHEELHOUSE" ] && [ ! -d "$WHEELHOUSE" ]; then
  fail "--wheelhouse $WHEELHOUSE is not a directory"
fi

if command -v uv >/dev/null 2>&1; then
  say "uv found: $(command -v uv)"
else
  say "uv not found: installing uv $UV_VERSION (official installer, pinned) into \$HOME/.local/bin"
  command -v curl >/dev/null 2>&1 || fail "curl is needed to install uv; install curl, or install uv yourself"
  curl -LsSf "https://astral.sh/uv/$UV_VERSION/install.sh" \
    | env UV_INSTALL_DIR="$HOME/.local/bin" UV_NO_MODIFY_PATH=1 sh \
    || fail "the uv installer failed"
  PATH="$HOME/.local/bin:$PATH"; export PATH
  command -v uv >/dev/null 2>&1 || fail "uv was installed but is not on PATH"
fi

if [ -n "$WHEELHOUSE" ]; then
  say "installing proveflow==$PROVEFLOW_VERSION from $WHEELHOUSE ONLY (--no-index)"
  uv tool install "proveflow==$PROVEFLOW_VERSION" --find-links "$WHEELHOUSE" --no-index \
    || fail "uv tool install from the wheelhouse failed"
else
  say "installing proveflow from git tag v$PROVEFLOW_VERSION (dependencies from PyPI)"
  uv tool install "git+$REPO_URL@v$PROVEFLOW_VERSION" \
    || fail "uv tool install from the git tag failed"
fi

if ! command -v proveflow >/dev/null 2>&1; then
  fail "proveflow was installed but is not on PATH: add the directory printed by \`uv tool dir --bin\` to PATH (or run \`uv tool update-shell\`), then open a new shell"
fi
got=$(proveflow --version) || fail "\`proveflow --version\` failed"
case "$got" in
  "proveflow $PROVEFLOW_VERSION") say "installed: $got ($(command -v proveflow))" ;;
  *) fail "installed version is '$got', expected 'proveflow $PROVEFLOW_VERSION'" ;;
esac
