"""Test-only byte tee between the proxy and a GENERATED twin (Phase 4, step 7).

Usage: python stdin_tee.py LOG CHILD_ARGV...

A generated twin passes the twin guard, so it cannot write an evidence log itself. This tee
is the independent evidence for it, like ``fake_twin.py``'s own log: every line the proxy
writes is appended to LOG as RAW BYTES and flushed BEFORE it is passed on to the child's
stdin. The child's stdout and stderr are inherited, so the proxy reads the twin directly and
nothing the twin says passes through this process. Never used outside tests.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> int:
    log = Path(sys.argv[1])
    child = subprocess.Popen(sys.argv[2:], stdin=subprocess.PIPE)
    pipe = child.stdin
    if pipe is None:
        return 2
    try:
        for raw in iter(sys.stdin.buffer.readline, b""):
            with log.open("ab") as fh:
                fh.write(raw if raw.endswith(b"\n") else raw + b"\n")
                fh.flush()
            try:
                pipe.write(raw)
                pipe.flush()
            except OSError:
                break
    finally:
        try:
            pipe.close()
        except OSError:
            pass
    return child.wait()


if __name__ == "__main__":
    sys.exit(main())
