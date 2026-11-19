"""Schema twins (Phase 4; docs/ARCHITECTURE.md §5.4).

``guard``: AST no-I/O check for twin source (the dual-role forwarding condition only, NOT a
spawn gate). ``_runtime``: stdlib-only validator/dispatcher whose source text is embedded into
every generated twin. ``schema_subset``: which inputSchema keywords the twin validates.
"""
