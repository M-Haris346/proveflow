# ADR-002: SQLite over Postgres for the run store

- Status: accepted (2026-11-10)

## Decision

Runs, trials, and verdicts are stored in a single SQLite file next to a cassette directory.
No server database.

## Rationale

- proveflow is a local CLI; requiring a database server would kill adoption for its actual
  users (individual developers, CI jobs).
- Run volumes are small (thousands of trials, not millions of rows/second).
- A single file is trivially copyable, archivable, and attachable to a bug report; replay needs
  exactly this property.
- Postgres competence is already demonstrated in the author's other repos — this choice is about
  fit, not ability.

## Consequences

- No concurrent multi-writer support — acceptable: one campaign writes at a time.
- Migrations handled with simple versioned SQL files in `store/migrations/`.
- If a future hosted mode ever existed (it is a non-goal, see ADR-001), this decision would be revisited.
