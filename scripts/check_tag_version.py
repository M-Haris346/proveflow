"""A release tag must equal the package version (Phase 9, Haris's ruling, 2026-11-26).

    python scripts/check_tag_version.py --tag v0.1.0a1 [--pyproject pyproject.toml]

Exit 0 when the tag is exactly ``v`` + ``[project].version`` of the pyproject; exit 1 otherwise,
naming both values. Stdlib only (``tomllib``), no git: CI passes the pushed tag's name
(``github.ref_name``) through an environment variable. The version is STATIC, a package
version and never a commit identifier (hatch-vcs was rejected as MEASURED: docs/BACKLOG.md).
"""

from __future__ import annotations

import argparse
import sys
import tomllib
from collections.abc import Sequence
from pathlib import Path


def expected_tag(pyproject: Path) -> str:
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    return "v" + str(data["project"]["version"])


def check(tag: str, pyproject: Path) -> tuple[bool, str]:
    want = expected_tag(pyproject)
    if tag != want:
        return False, f"tag {tag!r} does not match the package version: want {want!r}"
    return True, f"tag {tag!r} matches the package version"


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python scripts/check_tag_version.py")
    p.add_argument("--tag", required=True)
    p.add_argument("--pyproject", type=Path, default=Path("pyproject.toml"))
    args = p.parse_args(argv)
    ok, message = check(args.tag, args.pyproject)
    print(message, file=sys.stdout if ok else sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
