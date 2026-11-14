"""Deterministic oracle (Phase 3a; docs/ORACLE.md, ADR-004).

Reads a validated proxy cassette and decides R1 (exfil) and R4 (suspicious, review only).
No LLM, no network, no MCP SDK: this package may import ``proveflow.proxy.cassette``,
``proveflow.proxy.names`` and ``proveflow.core.*`` only (fresh-interpreter import guard in
tests/safety/test_oracle_safety.py). R2 and R3 are not built: R3 needs the agent's final
answer, which only the agent runner (Phase 5) can record; the cassette has no such event.
"""
