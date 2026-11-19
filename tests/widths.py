"""The ONE render width for every test that asserts Rich- or Click-rendered text.

Why a single, very large pinned width (Phase 4 finding, found by the per-commit worktree
verification, not by CI): Rich takes its width from ``COLUMNS`` minus ``legacy_windows``
(rich 15.0.0, ``rich/console.py:685-687``) and, when ``soft_wrap`` is off, inserts hard
line breaks into any longer line. Many rendered lines carry absolute paths (the
interpreter, fixtures, ``tmp_path``, config files), so their length depends on WHERE the
repo and the temp dir live. With the old ``COLUMNS=400`` a worktree under a long path made
the consent prompt's ``command:`` line 472 characters long, Rich wrapped it, and
``test_consent_prompt_text_is_exact_and_redacted`` failed; CI passed only because
``/home/runner/work/proveflow/proveflow`` happens to be short.

The bound: a Windows extended-length path is at most about 32,767 characters ("a maximum
total path length of 32,767 characters", Microsoft Learn, Maximum Path Length Limitation,
cited in docs/ARCHITECTURE.md section 8; the page calls the figure approximate because the
``\\\\?\\`` prefix may expand), and the longest asserted line holds far fewer than
``MAX_PATHS_PER_LINE`` paths. ``TEST_COLUMNS`` is above their product, so no line any test
can produce is wrapped: the result no longer depends on the path, the terminal or the
console width. Pinned by tests/unit/test_render_width.py.
"""

from __future__ import annotations

WINDOWS_EXTENDED_PATH_MAX = 32_767  # approximate per the cited page
MAX_PATHS_PER_LINE = 30  # generous: the consent prompt's command line holds 4
TEST_COLUMNS = 1_000_000


def assert_render_width_is_pinned() -> None:
    """Named check: COLUMNS is the pinned width, Rich uses it, and it is above the bound."""
    import os

    from rich.console import Console

    if os.environ.get("COLUMNS") != str(TEST_COLUMNS):
        raise AssertionError(f"COLUMNS is {os.environ.get('COLUMNS')!r}, not the pinned width")
    if Console(stderr=True).width < TEST_COLUMNS - 1:  # minus legacy_windows
        raise AssertionError("Rich does not use the pinned width")
    if TEST_COLUMNS < MAX_PATHS_PER_LINE * WINDOWS_EXTENDED_PATH_MAX:
        raise AssertionError("pinned width is below the stated path bound")


def long_command_consent(
    tmp_path: object, monkeypatch: object, extra_args: tuple[str, ...] = ()
) -> tuple[object, str]:
    """Run ``scan`` on a project whose one server has a synthetic command line over 5,000
    characters (plus ``extra_args``), answer the consent prompt "n" (nothing is launched),
    and return (CliRunner result, ``consent_prompt_text`` for that server)."""
    import json
    import sys
    from pathlib import Path

    from typer.testing import CliRunner

    import proveflow.cli as cli
    from fakehome import FAKE_SERVER, make_host
    from proveflow.discover import run_discovery

    tmp = Path(str(tmp_path))
    sep = chr(92)  # backslash, built at run time: no escape sequence in this source
    deep = "C:" + sep + sep.join(f"dir{i:04d}" for i in range(700)) + sep + "fixture.py"
    project = tmp / "project"
    project.mkdir(exist_ok=True)
    args = [str(FAKE_SERVER), "--extra", deep, *extra_args]
    entry = {"command": sys.executable, "args": args}
    (project / ".mcp.json").write_text(json.dumps({"mcpServers": {"proj": entry}}), "utf-8")
    host = make_host(tmp)
    monkeypatch.setattr(cli, "_host", lambda: host)  # type: ignore[attr-defined]
    monkeypatch.setattr(cli, "_interactive", lambda: True)  # type: ignore[attr-defined]
    result = CliRunner().invoke(
        cli.app,
        ["scan", "--json", "--project", str(project), "--cache-dir", str(tmp / "cache"),
         "--yes"],
        input="n\n",
    )  # fmt: skip
    spec = next(sp for c in run_discovery(host, project) for sp in c.servers if sp.name == "proj")
    return result, cli.consent_prompt_text(spec)


def assert_long_command_prompt_is_exact(tmp_path: object, monkeypatch: object) -> None:
    """Named check: a consent prompt whose command line is over 5,000 characters (far longer
    than any CI path) still appears in stderr EXACTLY as ``consent_prompt_text`` builds it.
    The server is declined, so nothing is launched."""
    result, expected = long_command_consent(tmp_path, monkeypatch)
    result_stderr: str = result.stderr  # type: ignore[attr-defined]
    if max(len(line) for line in expected.splitlines()) < 5000:
        raise AssertionError("check is vacuous: the command line is not long")
    if expected not in result_stderr:
        raise AssertionError("long consent prompt was wrapped or altered in stderr")
