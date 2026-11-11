"""Dev-only leak check for a REAL machine, run before any discover/scan output is shown.

Usage:  uv run python scripts/leak_check.py <out_dir> [--project DIR]

1. Runs discover + scan --no-launch in-process on the real host and renders every
   format (terminal tables, JSON, SARIF) plus DEBUG logs into memory.
2. Re-reads the raw MCP sections of every found config file and collects every value
   proveflow must hide: all env/header values, and every arg/url/command/envFile
   segment the redaction rules match.
3. Searches all rendered outputs for each raw value.

Prints ONLY counts and (on a hit) the location of the value - never a value. Writes the
outputs to <out_dir> only when zero raw values were found; otherwise writes nothing and
exits 1.
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import re
import sys
from pathlib import Path
from typing import Any

from rich.console import Console

from proveflow import __version__, logging_setup
from proveflow.config import ProveflowConfig
from proveflow.core.client import ConfigStatus
from proveflow.discover import HostEnv, run_discovery
from proveflow.discover.redact_rules import raw_secret_segments
from proveflow.logging_setup import JsonFormatter
from proveflow.report.json_out import to_json
from proveflow.report.models import DiscoverReport
from proveflow.report.sarif import build_sarif
from proveflow.report.terminal import render_discover, render_scan
from proveflow.scan import build_scan

MIN_CHECK_LEN = 6  # shorter values ("1", "true") cannot be meaningfully searched for


def _server_maps(data: dict[str, Any]) -> list[tuple[str, Any]]:
    maps: list[tuple[str, Any]] = []
    for key in ("mcpServers", "servers"):
        if isinstance(data.get(key), dict):
            maps.append((key, data[key]))
    projects = data.get("projects")
    if isinstance(projects, dict):
        for i, entry in enumerate(projects.values()):
            if isinstance(entry, dict) and isinstance(entry.get("mcpServers"), dict):
                maps.append((f"projects[#{i}].mcpServers", entry["mcpServers"]))
    return maps


def _collect(path: Path, file_idx: int) -> list[tuple[str, str]]:
    """(location, raw value) pairs. Values stay in memory only."""
    out: list[tuple[str, str]] = []
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return out
    if not isinstance(data, dict):
        return out
    for where, mapping in _server_maps(data):
        for name, entry in mapping.items():
            if not isinstance(entry, dict):
                continue
            loc = f"file#{file_idx} {where}.{name}"
            for field in ("env", "headers"):
                values = entry.get(field)
                if isinstance(values, dict):
                    for k, v in values.items():
                        out.append((f"{loc}.{field}.{k}", str(v)))
            args = entry.get("args")
            if isinstance(args, list) and all(isinstance(a, str) for a in args):
                for seg in raw_secret_segments(args):
                    out.append((f"{loc}.args", seg))
            for field in ("url", "serverUrl", "command", "envFile"):
                value = entry.get(field)
                if isinstance(value, str):
                    for seg in raw_secret_segments([value]):
                        out.append((f"{loc}.{field}", seg))
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("--project", type=Path, default=Path.cwd())
    ns = parser.parse_args()
    project = ns.project.resolve()

    logging_setup.configure("DEBUG")
    log_buf = io.StringIO()
    handler = logging.StreamHandler(log_buf)
    handler.setFormatter(JsonFormatter())
    logging.getLogger("proveflow").addHandler(handler)

    host = HostEnv.current()
    configs = run_discovery(host, project)
    discover_report = DiscoverReport(
        proveflow_version=__version__, project=str(project), configs=tuple(configs)
    )
    scan_report = build_scan(configs, host, project, ProveflowConfig())

    rendered: dict[str, str] = {}
    for name, fn in (
        ("discover.txt", lambda c: render_discover(discover_report, c)),
        ("scan.txt", lambda c: render_scan(scan_report, c, 50)),
    ):
        buf = io.StringIO()
        fn(Console(file=buf, width=250, color_system=None, legacy_windows=False))
        rendered[name] = buf.getvalue()
    rendered["discover.json"] = to_json(discover_report)
    rendered["scan.json"] = to_json(scan_report)
    rendered["scan.sarif"] = to_json(build_sarif(scan_report))
    logging.getLogger("proveflow").removeHandler(handler)
    rendered["debug.log"] = log_buf.getvalue()

    found_files = sorted(
        {c.path for c in configs if c.status is ConfigStatus.FOUND and c.path is not None}
    )
    raw: list[tuple[str, str]] = []
    for i, path in enumerate(found_files):
        raw.extend(_collect(path, i))

    checked = [(loc, v) for loc, v in raw if len(v) >= MIN_CHECK_LEN]
    n_collected, n_checked = len(raw), len(checked)
    squeezed_outputs = {name: "".join(text.split()) for name, text in rendered.items()}
    hits: list[str] = []
    for loc, value in checked:
        squeezed = "".join(value.split())
        for out_name, text in rendered.items():
            if value in text or (squeezed and squeezed in squeezed_outputs[out_name]):
                hits.append(f"{loc} -> {out_name}")
    del raw, checked

    print(f"config files found: {len(found_files)}")
    for i, path in enumerate(found_files):
        print(f"  file#{i}: {path}")
    # Independent of the redaction rules: long mixed letter+digit tokens that are still
    # visible in args/urls. Each could be an unrecognized secret -> reviewed by a human.
    suspicious = _suspicious_tokens(scan_report)
    print(f"raw values collected: {n_collected}")
    print(
        f"suspicious unredacted tokens (>= {SUSPICIOUS_LEN} chars, letters+digits): "
        f"{len(suspicious)}"
    )
    for where in suspicious:
        print(f"  review: {where}")
    print(f"raw values checked (>= {MIN_CHECK_LEN} chars): {n_checked}")
    print(f"short values not checked (< {MIN_CHECK_LEN} chars): {n_collected - n_checked}")
    return _finish(ns.out_dir, rendered, hits)


SUSPICIOUS_LEN = 16
_TOKEN = re.compile(rf"[A-Za-z0-9_+/=-]{{{SUSPICIOUS_LEN},}}")


def _suspicious_tokens(report: Any) -> list[str]:
    """Locations (never values) of long letter+digit tokens left visible in args/urls."""
    out: list[str] = []
    for prof in report.profiles:
        for srv in prof.servers:
            texts = [("url", srv.spec.url)] if srv.spec.url is not None else []
            texts += [(f"args[{i}]", a) for i, a in enumerate(srv.spec.args)]
            for where, text in texts:
                for seg in text.plain_segments():
                    for tok in _TOKEN.findall(seg):
                        if any(c.isdigit() for c in tok) and any(c.isalpha() for c in tok):
                            out.append(f"{prof.id} / {srv.key} / {where} (len {len(tok)})")
    return sorted(set(out))


def _finish(out_dir: Path, rendered: dict[str, str], hits: list[str]) -> int:
    print(f"raw values found in outputs: {len(hits)}")
    if hits:
        for h in hits:
            print(f"  LEAK at {h}")
        print("outputs NOT written.")
        return 1
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, text in rendered.items():
        (out_dir / name).write_text(text, encoding="utf-8", newline="\n")
    print(f"outputs written to {out_dir}: {', '.join(sorted(rendered))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
