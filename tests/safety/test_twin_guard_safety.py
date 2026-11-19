"""Twin guard safety (R-C1): the guard refuses I/O scripts, refuses the fake twin, and there is
no way to make it report "passed" for a guard-failing script.

Proxy half (Phase 4 step 7): ``UpstreamState.guard_passed`` is computed by
``upstream.twin_stdio`` from the real guard on the hashed bytes, and no fixture, patch or
session field can set it to True for a guard-failing script:
* the session refuses any guard/marker key (``extra=forbid``);
* a pre-set ``guard_passed=True`` is overwritten by twin_stdio (assignment, not OR);
* in ``src`` the attribute is assigned only inside ``twin_stdio``, only from the guard step;
* in ``tests`` nothing assigns it except this file's overwrite test, and only mutation tests
  pass ``guard_passed=True`` to anything;
* end to end: a dual-role session on the guard-failing fake twin is sandboxed (its log).
"""

from __future__ import annotations

import ast
import inspect
import json
import os
from pathlib import Path

import anyio
import pytest
from pydantic import ValidationError

import proveflow
from proveflow.proxy import upstream
from proveflow.proxy.gate import UpstreamGate
from proveflow.proxy.session import ProxySession
from proveflow.twin import guard
from proveflow.twin.generator import generate_twin
from proveflow.twin.guard import TwinGuardError, check_no_io
from proxyhelpers import make_session, proxy_twin_root  # noqa: F401
from twinchecks import IO_SCRIPTS, assert_guard_refuses_io_scripts, stored_tools
from twinproxy import assert_dual_role_never_reaches_guard_failing_twin, twin_session

FAKE_TWIN = Path(__file__).resolve().parents[1] / "fixtures" / "fake_twin.py"
SRC = Path(proveflow.__file__).resolve().parent
TESTS = Path(__file__).resolve().parents[1]


def test_guard_refuses_io_scripts() -> None:
    assert_guard_refuses_io_scripts()


def test_the_fake_twin_fails_the_guard_on_its_first_import() -> None:
    """Premise of R-C1, measured: the fake twin (file I/O evidence log) fails the guard."""
    with pytest.raises(TwinGuardError) as exc:
        check_no_io(FAKE_TWIN.read_text(encoding="utf-8"))
    assert exc.value.reason == "import not allowed: from __future__ import annotations"
    assert exc.value.lineno == 26


def test_guard_cannot_be_made_to_pass_for_a_failing_script() -> None:
    """check_no_io takes the source and nothing else, reads no environment, no file and no
    flag, and its only non-raising outcome is completing the AST walk."""
    assert list(inspect.signature(check_no_io).parameters) == ["source"]
    tree = ast.parse(Path(guard.__file__).read_text(encoding="utf-8"))
    imported = {
        a.name for n in ast.walk(tree) if isinstance(n, ast.Import | ast.ImportFrom)
        for a in (n.names if isinstance(n, ast.Import) else [ast.alias(n.module or "")])
    }  # fmt: skip
    assert imported <= {"__future__", "ast"}, imported  # no os/environ/config access
    for src in [*IO_SCRIPTS.values(), FAKE_TWIN.read_text(encoding="utf-8")]:
        with pytest.raises(TwinGuardError):
            check_no_io(src)


# --- proxy half: guard_passed cannot be set by any fixture, patch or session field -----


@pytest.mark.parametrize("key", ["guard_passed", "guard", "markers", "marker"])
def test_no_session_field_can_carry_a_guard_result_or_markers(tmp_path: Path, key: str) -> None:
    data = json.loads(make_session(tmp_path).model_dump_json())
    data[key] = True if "guard" in key else {"t": "pfmark_0"}
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ProxySession.model_validate(data)


def _guard_passed_after_stdio(session: ProxySession, preset: bool) -> bool:
    state = upstream.UpstreamState()
    state.guard_passed = preset  # the one assignment tests are allowed (overwrite check)
    seen: list[bool] = []

    async def run() -> None:
        async with upstream.twin_stdio(
            session.upstream,
            session.twin_sha256,
            UpstreamGate(session.policy),
            state,
            lambda *a, **k: None,
            dict(os.environ),
            max_messages=100,
            on_limit=lambda reason: None,
        ):
            seen.append(state.guard_passed)

    anyio.run(run)
    [value] = seen
    return value


def test_twin_stdio_overwrites_a_preset_guard_passed(tmp_path: Path) -> None:
    """Fake twin (guard-failing) with a pre-set True -> False; a generated twin with a
    pre-set False -> True. The verdict comes from the bytes, never from prior state."""
    assert _guard_passed_after_stdio(make_session(tmp_path), preset=True) is False
    tools = stored_tools("fetch")
    build = generate_twin("fetch", tools, seed="overwrite")  # type: ignore[arg-type]
    gen = twin_session(tmp_path, build, tools)  # type: ignore[arg-type]
    assert _guard_passed_after_stdio(gen, preset=False) is True


def _stores(tree: ast.AST) -> list[tuple[ast.AST, ast.AST]]:
    """(assign node, value) for every store to an attribute named guard_passed."""
    out: list[tuple[ast.AST, ast.AST]] = []
    for node in ast.walk(tree):
        targets: list[ast.expr] = []
        value: ast.AST | None = None
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AugAssign | ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        for t in targets:
            if isinstance(t, ast.Attribute) and t.attr == "guard_passed" and value is not None:
                out.append((node, value))
    return out


def _setattr_strings(tree: ast.AST) -> list[ast.Call]:
    return [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and any(isinstance(a, ast.Constant) and a.value == "guard_passed" for a in n.args)
    ]


def _enclosing_function(tree: ast.Module, target: ast.AST) -> str | None:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            if any(child is target for child in ast.walk(node)):
                return node.name
    return None


def test_guard_passed_is_assigned_only_in_twin_stdio_from_the_guard_step() -> None:
    found: list[tuple[str, str | None, str]] = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node, value in _stores(tree):
            found.append((path.name, _enclosing_function(tree, node), ast.unparse(value)))
        assert not _setattr_strings(tree), f"setattr of guard_passed in {path.name}"
        for call in (n for n in ast.walk(tree) if isinstance(n, ast.Call)):
            for kw in call.keywords:
                if kw.arg == "guard_passed":  # the only keyword use READS the state field
                    assert ast.unparse(kw.value) == "upstream_state.guard_passed", path.name
    assert sorted(found) == [
        ("upstream.py", "twin_stdio", "False"),
        ("upstream.py", "twin_stdio", "passed"),
    ], found
    source = Path(upstream.__file__).read_text(encoding="utf-8")
    assert (
        "copy, passed = prepare_twin_copy(Path(upstream.argv[1]), Path(workdir.name), "
        "twin_sha256)" in source
    )
    assert upstream.UpstreamState().guard_passed is False


# EXACT set (compared with ==, like ALLOWED_BY_PATH_LOADERS): every call in the suite that
# passes guard_passed= anything but the literal False, as (file, called function). Adding or
# removing one is a visible, deliberate diff here.
ALLOWED_TRUE_CALLS = {
    # unit test of the PURE function server.forwardable_dual_roles (no script, no state)
    ("unit/test_proxy_dual_role.py", "forwardable_dual_roles"),
    # the "dual-role without guard_passed" mutant wraps the real function
    ("mutation/test_twin_dual_role_mutation.py", "real"),
}


def test_no_fixture_or_patch_in_the_suite_sets_guard_passed() -> None:
    """Only this file's overwrite test assigns guard_passed; the calls that pass a
    non-False ``guard_passed=`` are exactly ALLOWED_TRUE_CALLS."""
    me = Path(__file__).resolve()
    true_calls: set[tuple[str, str]] = set()
    for path in sorted(TESTS.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        stores = _stores(tree)
        if path.resolve() == me:
            assert [ast.unparse(v) for _, v in stores] == ["preset"]
        else:
            assert not stores, f"{path.relative_to(TESTS)} assigns guard_passed"
        assert not _setattr_strings(tree), f"{path.relative_to(TESTS)} setattr guard_passed"
        for call in (n for n in ast.walk(tree) if isinstance(n, ast.Call)):
            for kw in call.keywords:
                if kw.arg == "guard_passed" and ast.unparse(kw.value) != "False":
                    true_calls.add((path.relative_to(TESTS).as_posix(), ast.unparse(call.func)))
    assert true_calls == ALLOWED_TRUE_CALLS


def test_dual_role_session_on_the_guard_failing_fake_twin_is_sandboxed(tmp_path: Path) -> None:
    """End to end: session evidence AND proxy classifier both say fetch_url is source +
    sink; nothing in the session can unlock it; the fake twin's own log shows no call."""
    assert_dual_role_never_reaches_guard_failing_twin(tmp_path)
