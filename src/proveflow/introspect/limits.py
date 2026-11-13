"""Shared size limits for line-delimited JSON-RPC over stdio (no proveflow imports).

Moved out of ``transport.py`` in Phase 2 so ``proveflow.proxy`` can use the same limit
without importing the introspection transport (ADR-006, import guard).
"""

from __future__ import annotations

MAX_LINE = 16 * 1024 * 1024
