"""The control is a TEST INSTRUMENT that deliberately obeys injections (proveflow.runner.control,
Phase 8). It ships in the package only because ``proveflow.runner.verify`` runs it, so NOTHING
else under src/ may import it (Haris's ruling, 2026-11-26). The importers are SCANNED from every
module under src/ by AST, never listed by hand (the family of test_tools_never_imported.py),
absolute and relative imports both; the whole scan is printed on failure."""

from __future__ import annotations

import shipchecks


def test_only_verify_imports_the_control() -> None:
    shipchecks.assert_only_verify_imports_the_control()
