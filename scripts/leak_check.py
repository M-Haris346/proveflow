"""Dev-only leak check for a REAL machine, run before any discover/scan output is shown.

Two modes. Both print ONLY counts and locations, never a value; exit 1 on any hit.

  render <out_dir> [--project DIR]
      Runs discover + scan --no-launch IN-PROCESS on the real host, renders every format
      (terminal tables, JSON, SARIF, DEBUG logs) into memory, and writes them to <out_dir>
      only if no raw value is found.

  files --outputs DIR [--cache-dir DIR] [--project DIR]
      Checks files the real CLI already wrote (e.g. `scan --json > DIR/scan.json`,
      `--sarif DIR/scan.sarif`) PLUS every file in the per-user tool cache (default: the
      same per-user cache dir proveflow uses). It also lists, by location only, long
      letter+digit tokens left visible in introspected tool metadata (names, descriptions,
      schemas) in any scan JSON, for human review.

Raw values come from re-reading the MCP sections of every found config file: all env/header
values, and every arg/url/command/envFile segment the redaction rules match. Values shorter
than MIN_CHECK_LEN are counted but not searched.
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import re
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from rich.console import Console

from proveflow import __version__, logging_setup
from proveflow.config import ProveflowConfig
from proveflow.core.client import ConfigStatus
from proveflow.discover import HostEnv, run_discovery
from proveflow.discover.redact_rules import raw_secret_segments
from proveflow.introspect.cache import default_cache_dir
from proveflow.logging_setup import JsonFormatter
from proveflow.report.json_out import to_json
from proveflow.report.models import DiscoverReport
from proveflow.report.sarif import build_sarif
from proveflow.report.terminal import render_discover, render_scan
from proveflow.scan import build_scan

MIN_CHECK_LEN = 6  # shorter values ("1", "true") cannot be meaningfully searched for
SUSPICIOUS_LEN = 16
_TOKEN = re.compile(rf"[A-Za-z0-9_+/=-]{{{SUSPICIOUS_LEN},}}")
MAX_FILE = 64 * 1024 * 1024


# --- raw values (kept in memory only) -----------------------------------------------


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
    """(location, raw value) pairs from one config file."""
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


def collect_raw_values(host: HostEnv, project: Path) -> tuple[list[Path], list[tuple[str, str]]]:
    configs = run_discovery(host, project)
    files = sorted(
        {c.path for c in configs if c.status is ConfigStatus.FOUND and c.path is not None}
    )
    raw: list[tuple[str, str]] = []
    for i, path in enumerate(files):
        raw.extend(_collect(path, i))
    return files, raw


def find_hits(values: list[tuple[str, str]], texts: dict[str, str]) -> list[str]:
    """Locations '<value location> -> <output name>'; whitespace-squeezed match too."""
    squeezed = {name: "".join(t.split()) for name, t in texts.items()}
    hits: list[str] = []
    for loc, value in values:
        if len(value) < MIN_CHECK_LEN:
            continue
        v_sq = "".join(value.split())
        for name, text in texts.items():
            if value in text or (v_sq and v_sq in squeezed[name]):
                hits.append(f"{loc} -> {name}")
    return hits


# --- suspicious tokens (locations only) ---------------------------------------------


def _token_hits(text: str) -> list[int]:
    return [
        len(t)
        for t in _TOKEN.findall(text)
        if any(c.isdigit() for c in t) and any(c.isalpha() for c in t)
    ]


def suspicious_config_tokens(report: Any) -> list[str]:
    """Long letter+digit tokens still visible in args/urls of the scan report."""
    out: list[str] = []
    for prof in report.profiles:
        for srv in prof.servers:
            texts = [("url", srv.spec.url)] if srv.spec.url is not None else []
            texts += [(f"args[{i}]", a) for i, a in enumerate(srv.spec.args)]
            for where, text in texts:
                for seg in text.plain_segments():
                    out += [f"{prof.id} / {srv.key} / {where} (len {n})" for n in _token_hits(seg)]
    return sorted(set(out))


def suspicious_tool_tokens(scan_json: dict[str, Any], source: str) -> list[str]:
    """Same check over introspected tool metadata (name, description, schema strings)."""

    def strings(value: Any) -> Iterable[str]:
        if isinstance(value, str):
            yield value
        elif isinstance(value, list):
            for v in value:
                yield from strings(v)
        elif isinstance(value, dict):
            for k, v in value.items():
                yield str(k)
                yield from strings(v)

    out: list[str] = []
    for prof in scan_json.get("profiles", []):
        for srv in prof.get("servers", []):
            for tool in srv.get("tools", []):
                if tool.get("name") == "*":
                    continue
                parts = {"name": tool.get("name", ""), "description": tool.get("description", "")}
                parts["schema"] = "\n".join(strings(tool.get("input_schema", {})))
                for field, text in parts.items():
                    for n in _token_hits(str(text)):
                        out.append(
                            f"{source}: {prof.get('id')} / {srv.get('key')} / "
                            f"{tool.get('name')} / {field} (len {n})"
                        )
    return sorted(set(out))


# --- files mode -------------------------------------------------------------------


def read_texts(dirs: Iterable[Path]) -> dict[str, str]:
    texts: dict[str, str] = {}
    for d in dirs:
        if not d.exists():
            continue
        for p in sorted(x for x in d.rglob("*") if x.is_file()):
            if p.stat().st_size > MAX_FILE:
                texts[str(p)] = ""
                continue
            texts[str(p)] = decode(p.read_bytes())
    return texts


def decode(data: bytes) -> str:
    """BOM-aware: Windows PowerShell 5.1 `>` writes UTF-16LE, which a UTF-8 read would turn
    into text no raw value matches (a silent false negative)."""
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", errors="replace")
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8", errors="replace")
    return data.decode("utf-8", errors="replace")


def check_files(
    host: HostEnv, project: Path, outputs: Path, cache_dir: Path | None
) -> dict[str, Any]:
    """Pure core of `files` mode (also used by the self-test)."""
    config_files, raw = collect_raw_values(host, project)
    dirs = [outputs] + ([cache_dir] if cache_dir is not None else [])
    texts = read_texts(dirs)
    hits = find_hits(raw, texts)
    suspicious: list[str] = []
    for name, text in texts.items():
        if name.endswith(".json") and '"profiles"' in text:
            try:
                suspicious += suspicious_tool_tokens(json.loads(text), Path(name).name)
            except ValueError:
                continue
    return {
        "config_files": config_files,
        "values_collected": len(raw),
        "values_checked": sum(1 for _, v in raw if len(v) >= MIN_CHECK_LEN),
        "files_scanned": len(texts),
        "cache_files": sum(1 for n in texts if cache_dir and n.startswith(str(cache_dir))),
        "hits": hits,
        "suspicious_tool_tokens": suspicious,
    }


def run_files(ns: argparse.Namespace) -> int:
    host = HostEnv.current()
    project = ns.project.resolve()
    cache_dir = ns.cache_dir if ns.cache_dir is not None else default_cache_dir(host)
    result = check_files(host, project, ns.outputs, cache_dir)
    print(f"config files found: {len(result['config_files'])}")
    for i, path in enumerate(result["config_files"]):
        print(f"  file#{i}: {path}")
    print(f"raw values collected: {result['values_collected']}")
    print(f"raw values checked (>= {MIN_CHECK_LEN} chars): {result['values_checked']}")
    print(f"files scanned: {result['files_scanned']} (cache dir: {cache_dir}, "
          f"{result['cache_files']} files)")  # fmt: skip
    print(f"suspicious tokens in tool metadata: {len(result['suspicious_tool_tokens'])}")
    for where in result["suspicious_tool_tokens"]:
        print(f"  review: {where}")
    print(f"raw values found in outputs/cache: {len(result['hits'])}")
    for h in result["hits"]:
        print(f"  LEAK at {h}")
    return 1 if result["hits"] else 0


# --- render mode (unchanged behaviour) ------------------------------------------------


def run_render(ns: argparse.Namespace) -> int:
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

    config_files, raw = collect_raw_values(host, project)
    hits = find_hits(raw, rendered)
    print(f"config files found: {len(config_files)}")
    for i, path in enumerate(config_files):
        print(f"  file#{i}: {path}")
    suspicious = suspicious_config_tokens(scan_report)
    print(f"raw values collected: {len(raw)}")
    print(f"suspicious unredacted tokens (>= {SUSPICIOUS_LEN} chars, letters+digits): "
          f"{len(suspicious)}")  # fmt: skip
    for where in suspicious:
        print(f"  review: {where}")
    checked = sum(1 for _, v in raw if len(v) >= MIN_CHECK_LEN)
    print(f"raw values checked (>= {MIN_CHECK_LEN} chars): {checked}")
    print(f"short values not checked (< {MIN_CHECK_LEN} chars): {len(raw) - checked}")
    print(f"raw values found in outputs: {len(hits)}")
    if hits:
        for h in hits:
            print(f"  LEAK at {h}")
        print("outputs NOT written.")
        return 1
    ns.out_dir.mkdir(parents=True, exist_ok=True)
    for name, text in rendered.items():
        (ns.out_dir / name).write_text(text, encoding="utf-8", newline="\n")
    print(f"outputs written to {ns.out_dir}: {', '.join(sorted(rendered))}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="leak_check")
    sub = parser.add_subparsers(dest="mode", required=True)
    r = sub.add_parser("render", help="render discover/scan --no-launch in-process and check")
    r.add_argument("out_dir", type=Path)
    r.add_argument("--project", type=Path, default=Path.cwd())
    f = sub.add_parser("files", help="check files the CLI wrote, plus the tool cache")
    f.add_argument("--outputs", type=Path, required=True)
    f.add_argument("--cache-dir", type=Path, default=None)
    f.add_argument("--project", type=Path, default=Path.cwd())
    ns = parser.parse_args(argv)
    return run_render(ns) if ns.mode == "render" else run_files(ns)


if __name__ == "__main__":
    sys.exit(main())
