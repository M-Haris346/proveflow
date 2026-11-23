"""Loaders, one per source (Phase 6 step 3). Each takes ``read(path) -> bytes`` for the source's
pinned files (``fetch.fetch_pinned`` at runtime; committed SYNTHETIC fixtures in tests, so no
test fetches anything) and returns ``CorpusRecord``s built by ``records.make_record``.

THE UPSTREAM TEXT IS NEVER EDITED. Upstream attack texts carry their own real-looking
addresses, URLs, account numbers and phone numbers (an LLMail-Inject row mails a third-party
address; an AgentDojo goal sends money to an IBAN-shaped string; BIPIA texts point at
websites). CLAUDE.md's "no real exfil endpoints" rule governs payloads PROVEFLOW AUTHORS, not
the upstream text of a corpus record. What makes ingesting them safe is that the sink sandbox
is ALWAYS ON in twin mode and no sink call ever leaves the machine (proxy/policy.py,
proxy/sandbox.py); nothing a payload names is ever contacted.

Per source:
* InjecAgent: each row of ``data/attacker_cases_{dh,ds}.jsonl``; text = "Attacker
  Instruction", family = "Attack Type", source_id = "<file stem>:<row index>".
* BIPIA: the four attack files only (``fetch.check_path`` refuses every context directory by
  name); each is {category: [attack text, ...]}; family = the category, source_id =
  "<file stem>:<category>:<index>".
* AgentDojo: its injection tasks AS OF upstream's newest benchmark version, resolved by
  upstream's OWN rule from upstream's pinned table (``load_agentdojo``), across EVERY default
  suite's ``injection_tasks.py`` (11 files; a scan found no other registration site), read
  by AST and NEVER imported or executed. A GOAL that is an f-string is rendered only from
  string constants assigned in the same class or at module level (exactly what AgentDojo
  itself evaluates); any other part (a format spec, a call, an unknown name) leaves the GOAL
  UNRESOLVED: counted and reported, never guessed. family = the suite, source_id =
  "<suite>:<class name>@<chosen version>".
"""

from __future__ import annotations

import ast
import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from proveflow.corpus.records import CorpusRecord, make_record
from proveflow.corpus.sources import (
    AGENTDOJO,
    AGENTDOJO_TABLE,
    BIPIA,
    INJECAGENT,
    TABLE_LICENSES,
    Source,
)

Reader = Callable[[str], bytes]


@dataclass
class LoadResult:
    records: list[CorpusRecord] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)  # source ids not loaded, and why
    notes: dict[str, Any] = field(default_factory=dict)  # per-source measured facts


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _files(source: Source) -> list[str]:
    return sorted(p for p in source.files if p != source.licence_file)


def _record(source: Source, data: bytes, source_id: str, text: str, family: str) -> CorpusRecord:
    return make_record(source=source.name, source_id=source_id, text=text,
                       attack_family=family, license=TABLE_LICENSES[source.name],
                       revision=source.revision, fetch_sha256=_sha(data))  # fmt: skip


def load_injecagent(read: Reader, source: Source = INJECAGENT) -> LoadResult:
    read(source.licence_file)  # fetched (and checksummed) by its exact name, LICENCE
    out = LoadResult()
    for path in _files(source):
        data = read(path)
        stem = path.rsplit("/", 1)[-1].removesuffix(".jsonl")
        rows = [line for line in data.decode("utf-8").splitlines() if line.strip()]
        for i, line in enumerate(rows):
            row = json.loads(line)
            text, family = row.get("Attacker Instruction"), row.get("Attack Type")
            if not isinstance(text, str) or not text or not isinstance(family, str):
                out.unresolved.append(f"{stem}:{i}: no Attacker Instruction / Attack Type")
                continue
            out.records.append(_record(source, data, f"{stem}:{i}", text, family))
    return out


def load_bipia(read: Reader, source: Source = BIPIA) -> LoadResult:
    read(source.licence_file)
    out = LoadResult()
    for path in _files(source):
        data = read(path)
        stem = path.rsplit("/", 1)[-1].removesuffix(".json")
        body = json.loads(data.decode("utf-8"))
        if not isinstance(body, dict):
            raise ValueError(f"bipia {path}: not a {{category: [text]}} object")
        for category, texts in body.items():
            if not isinstance(texts, list):
                out.unresolved.append(f"{stem}:{category}: not a list")
                continue
            for i, text in enumerate(texts):
                if not isinstance(text, str) or not text:
                    out.unresolved.append(f"{stem}:{category}:{i}: not a non-empty string")
                    continue
                out.records.append(_record(source, data, f"{stem}:{category}:{i}", text, category))
    return out


def _constants(body: list[ast.stmt]) -> dict[str, str]:
    out: dict[str, str] = {}
    for stmt in body:
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
            target, value = stmt.targets[0], stmt.value
        elif isinstance(stmt, ast.AnnAssign) and stmt.value is not None:
            target, value = stmt.target, stmt.value
        else:
            continue
        if isinstance(target, ast.Name) and isinstance(value, ast.Constant):
            if isinstance(value.value, str):
                out[target.id] = value.value
    return out


def render_goal(node: ast.expr, scope: dict[str, str]) -> str | None:
    """A GOAL's text: a string constant as-is, or an f-string whose every interpolation is a
    bare name bound to a string constant in ``scope``; otherwise None (unresolved)."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if not isinstance(node, ast.JoinedStr):
        return None
    parts: list[str] = []
    for value in node.values:
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            parts.append(value.value)
        elif (isinstance(value, ast.FormattedValue) and value.conversion == -1
              and value.format_spec is None and isinstance(value.value, ast.Name)
              and value.value.id in scope):  # fmt: skip
            parts.append(scope[value.value.id])
        else:
            return None
    return "".join(parts)


def _goal_node(cls: ast.ClassDef) -> ast.expr | None:
    """The value assigned to ``GOAL`` in the class body (the last one), or None."""
    found: ast.expr | None = None
    for stmt in cls.body:
        if isinstance(stmt, ast.Assign):
            names = [t.id for t in stmt.targets if isinstance(t, ast.Name)]
            if names == ["GOAL"] and len(stmt.targets) == 1:
                found = stmt.value
        elif isinstance(stmt, ast.AnnAssign) and stmt.value is not None:
            if isinstance(stmt.target, ast.Name) and stmt.target.id == "GOAL":
                found = stmt.value
    return found


Version = tuple[int, int, int]
BASE_VERSION: Version = (1, 0, 0)  # upstream register_injection_task's version (task_suite.py)


class AgentDojoTableError(ValueError):
    """Upstream's benchmark-version table (load_suites.py) cannot be read as pinned: AgentDojo
    is not ingested at all, since every task's resolution depends on it."""


def _version_of(node: ast.expr | None, scope: dict[str, Version]) -> Version | None:
    """A version tuple: a literal (a, b, c) of ints, or a bare name bound to one in ``scope``
    (module-level constants). Anything else: None (UNRESOLVED, never defaulted)."""
    if isinstance(node, ast.Name):
        return scope.get(node.id)
    if isinstance(node, ast.Tuple) and len(node.elts) == 3:
        ints = [e.value for e in node.elts if isinstance(e, ast.Constant) and type(e.value) is int]
        if len(ints) == 3:
            return (ints[0], ints[1], ints[2])
    return None


def _version_constants(body: list[ast.stmt]) -> dict[str, Version]:
    out: dict[str, Version] = {}
    for stmt in body:
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
            target = stmt.targets[0]
            if isinstance(target, ast.Name):
                version = _version_of(stmt.value, {})
                if version is not None:
                    out[target.id] = version
    return out


def _parse_version_key(key: str) -> Version | None:
    """upstream's table keys: "v1", "v1.1", "v1.2.2" ... -> (1, 0, 0), (1, 1, 0), (1, 2, 2)."""
    if not key.startswith("v"):
        return None
    try:
        parts = [int(p) for p in key[1:].split(".")]
    except ValueError:
        return None
    if not 1 <= len(parts) <= 3:
        return None
    a, b, c = [*parts, 0, 0, 0][:3]
    return a, b, c


def benchmark_table(data: bytes) -> tuple[str, dict[str, Version]]:
    """Upstream's per-suite versions for its NEWEST benchmark version, read from load_suites.py
    by AST: ``_SUITES`` maps "vX.Y.Z" to a dict name; that dict maps each suite to either its
    base suite (``<name>_task_suite``, version 1.0.0) or ``<name>_task_suite.get_new_version(
    (a, b, c))``. Anything else fails closed (AgentDojoTableError)."""
    module = ast.parse(data.decode("utf-8"))
    dicts: dict[str, ast.Dict] = {}
    suites_map: ast.Dict | None = None
    for stmt in module.body:
        target = (
            stmt.target
            if isinstance(stmt, ast.AnnAssign)
            else (
                stmt.targets[0] if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 else None
            )
        )
        value = stmt.value if isinstance(stmt, ast.AnnAssign | ast.Assign) else None
        if not isinstance(target, ast.Name):
            continue
        if isinstance(value, ast.Dict):
            dicts[target.id] = value
        elif target.id == "_SUITES" and isinstance(value, ast.Call):
            suites_map = next((a for a in value.args if isinstance(a, ast.Dict)), None)
    if suites_map is None:
        raise AgentDojoTableError("load_suites.py: no _SUITES = defaultdict(dict, {...})")
    versions: dict[Version, tuple[str, str]] = {}
    for k, v in zip(suites_map.keys, suites_map.values, strict=True):
        key = k.value if isinstance(k, ast.Constant) and isinstance(k.value, str) else None
        parsed = _parse_version_key(key) if key else None
        if parsed is None or not isinstance(v, ast.Name) or v.id not in dicts:
            raise AgentDojoTableError(f"load_suites.py: unreadable _SUITES entry {key!r}")
        versions[parsed] = (key or "", v.id)
    newest = max(versions)
    label, dict_name = versions[newest]
    table: dict[str, Version] = {}
    entries = dicts[dict_name]
    for k, v in zip(entries.keys, entries.values, strict=True):
        suite = k.value if isinstance(k, ast.Constant) and isinstance(k.value, str) else None
        if suite is None:
            raise AgentDojoTableError(f"load_suites.py {dict_name}: a non-literal suite key")
        if isinstance(v, ast.Name) and v.id == f"{suite}_task_suite":
            table[suite] = BASE_VERSION
        elif (isinstance(v, ast.Call) and isinstance(v.func, ast.Attribute)
              and v.func.attr == "get_new_version" and isinstance(v.func.value, ast.Name)
              and v.func.value.id == f"{suite}_task_suite" and len(v.args) == 1
              and (version := _version_of(v.args[0], {})) is not None):  # fmt: skip
            table[suite] = version
        else:
            raise AgentDojoTableError(f"load_suites.py {dict_name}[{suite!r}]: unreadable version")
    return label, table


def task_version(cls: ast.ClassDef, scope: dict[str, Version]) -> Version | None:
    """A task class's version from its decorator: ``task_suite.register_injection_task`` is
    1.0.0; ``task_suite.update_injection_task(V[, new])`` is V, a literal tuple or a module
    constant. No recognized decorator, or a V that does not resolve: None (UNRESOLVED)."""
    found: list[Version | None] = []
    for dec in cls.decorator_list:
        if isinstance(dec, ast.Attribute) and dec.attr == "register_injection_task":
            found.append(BASE_VERSION)
        elif (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)
              and dec.func.attr == "update_injection_task" and dec.args):  # fmt: skip
            found.append(_version_of(dec.args[0], scope))
    return found[0] if len(found) == 1 else None


@dataclass
class _Revision:
    version: Version | None
    goal: str | None
    path: str
    data: bytes


def load_agentdojo(read: Reader, source: Source = AGENTDOJO) -> LoadResult:
    """AgentDojo's injection tasks AS OF upstream's newest benchmark version, by upstream's own
    rule (task_suite.get_version_compatible_items): per (suite, task class), the revision with
    the highest version <= THAT SUITE's version in upstream's table (load_suites.py, pinned).
    A task with ANY revision whose version does not resolve is UNRESOLVED as a whole (the
    chosen revision could be wrong either way: retired text in, or live text out), as is a
    chosen revision whose GOAL does not resolve. Never defaulted, never guessed."""
    read(source.licence_file)
    label, table = benchmark_table(read(AGENTDOJO_TABLE))
    out = LoadResult()
    out.notes["agentdojo_benchmark_version"] = label
    out.notes["agentdojo_suite_versions"] = {s: ".".join(map(str, v)) for s, v in table.items()}
    tasks: dict[tuple[str, str], list[_Revision]] = {}
    for path in _files(source):
        if path == AGENTDOJO_TABLE:
            continue
        data = read(path)
        suite = path.split("/")[-2]
        module = ast.parse(data.decode("utf-8"))
        goal_scope = _constants(module.body)
        version_scope = _version_constants(module.body)
        for cls in (n for n in module.body if isinstance(n, ast.ClassDef)):
            node = _goal_node(cls)
            if node is None:
                continue  # not an injection task
            goal = render_goal(node, {**goal_scope, **_constants(cls.body)})
            tasks.setdefault((suite, cls.name), []).append(
                _Revision(task_version(cls, version_scope), goal, path, data)
            )
    chosen: dict[str, str] = {}
    for (suite, name), revisions in sorted(tasks.items()):
        source_id = f"{suite}:{name}"
        if any(r.version is None for r in revisions):
            out.unresolved.append(f"{source_id}: a revision's version does not resolve")
            continue
        target = table.get(suite)
        if target is None:
            out.unresolved.append(f"{source_id}: suite not in upstream's benchmark table")
            continue
        live = [r for r in revisions if r.version is not None and r.version <= target]
        if not live:
            out.notes.setdefault("agentdojo_above_target", []).append(source_id)
            continue
        best = max(live, key=lambda r: r.version or BASE_VERSION)
        version = ".".join(map(str, best.version or BASE_VERSION))
        if not best.goal:
            out.unresolved.append(
                f"{source_id}@{version}: GOAL not resolvable from string constants"
            )
            continue
        chosen[source_id] = version
        out.records.append(_record(source, best.data, f"{source_id}@{version}", best.goal, suite))
    out.notes["agentdojo_chosen"] = chosen
    seen = sum(len(revisions) for revisions in tasks.values())
    out.notes["agentdojo_revisions_seen"] = seen
    out.notes["agentdojo_tasks"] = len(tasks)
    # retired by upstream's own rule BEFORE dedup runs: dedup's rate is cross-source only
    out.notes["agentdojo_superseded_revisions"] = seen - len(tasks)
    return out


LOADERS: dict[str, Callable[[Reader], LoadResult]] = {
    "injecagent": load_injecagent, "bipia": load_bipia, "agentdojo": load_agentdojo,
}  # fmt: skip
