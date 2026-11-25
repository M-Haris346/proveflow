"""Writing a ``FixBundle`` to ``<out_dir>/<flow_id>/<kind>/`` (Phase 8).

* The target directory must NOT exist (``FixTargetExists``): a fix is never overwritten.
* NO PARTIAL OUTPUT: everything is written into a fresh sibling temp directory, which is then
  renamed into place; on any error the temp directory is removed.
* Only that directory is written. Nothing else is opened for writing, and the user's config is
  never opened at all (``render`` reads only the scan).
"""

from __future__ import annotations

import contextlib
import json
import shutil
import tempfile
from pathlib import Path

from proveflow.core.mitigations import MitigationKind
from proveflow.fix.catalog import CATALOG
from proveflow.fix.render import M3_SYNTAX_HEADER, FixBundle

FIX_SCHEMA = 1
VERIFY_STATUS = (
    "Twin verify (Phase 8) applies this catalog entry's TWIN policy against the CONTROL (a "
    "scripted client), not this patch file, and not in a real client: this patch was NOT "
    "verified against a real client. See docs/results/ for the verify reports."
)


class FixTargetExists(FileExistsError):
    """The fix directory already exists; nothing was written."""


def manifest(bundle: FixBundle) -> dict[str, object]:
    return {
        "format": "proveflow-fix", "schema_version": FIX_SCHEMA, "flow_id": bundle.flow_id,
        "mitigation": bundle.kind.value, "applied": False,
        "target": {"profile": bundle.profile, "server": bundle.server, "tool": bundle.tool},
        "edits": [{"file": e.file, "client": e.client, "scope": e.scope, "patch": e.patch,
                   "kind": e.kind, "pointers": list(e.pointers), "merge_into": list(e.merge_into)}
                  for e in bundle.edits],
        "refused": [{"client": r.client, "scope": r.scope, "file": r.file, "reason": r.reason}
                    for r in bundle.refused],
        "sources": list(CATALOG[bundle.kind].sources),
        "review": M3_SYNTAX_HEADER if bundle.kind is MitigationKind.M3_HUMAN_APPROVAL else None,
    }  # fmt: skip


def rationale(bundle: FixBundle) -> str:
    e = CATALOG[bundle.kind]
    target = f"{bundle.server}/{bundle.tool if bundle.tool is not None else '*'}"
    lines = [
        f"# {e.title}", "",
        f"Flow `{bundle.flow_id}` in profile `{bundle.profile}`; sink `{target}`.", "",
        "**This patch has NOT been applied.** proveflow never edits a client config.", "",
        *([f"**{M3_SYNTAX_HEADER}**", ""]
          if bundle.kind is MitigationKind.M3_HUMAN_APPROVAL else []),
        f"- What it does: {e.does}", f"- Expected trade-off: {e.tradeoff}",
        f"- What it does NOT do: {e.does_not}", f"- How to apply: {e.apply}",
        f"- How to undo: {e.undo}", f"- Verify status: {VERIFY_STATUS}", "",
        "Sources: " + ", ".join(e.sources),
    ]  # fmt: skip
    if bundle.refused:
        lines += ["", "Not patched (each with its reason):"]
        lines += [f"- {r.client} {r.scope} {r.file}: {r.reason}" for r in bundle.refused]
    return chr(10).join(lines) + chr(10)


def refuse_existing(target: Path) -> None:
    if target.exists():
        raise FixTargetExists(f"{target} exists: a fix is never overwritten")


def write_bundle(bundle: FixBundle, out_dir: Path) -> Path:
    """Write the bundle; return its directory."""
    target = out_dir / bundle.flow_id / bundle.kind.value
    refuse_existing(target)
    made = [p for p in (target.parent, *target.parent.parents) if not p.exists()]
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=".proveflow-fix-", dir=target.parent))
    try:
        for name, data in bundle.files.items():
            (tmp / name).write_bytes(data)
        (tmp / "manifest.json").write_bytes(
            (json.dumps(manifest(bundle), indent=2) + chr(10)).encode("utf-8")
        )
        (tmp / "rationale.md").write_bytes(rationale(bundle).encode("utf-8"))
        tmp.rename(target)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        for p in made:  # the directories this call created, deepest first, if still empty
            with contextlib.suppress(OSError):
                p.rmdir()
        raise
    return target
