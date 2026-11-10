# ADR-005: Never edit user configs; fixes are patch files

- Status: accepted (2026-11-10)

## Decision

proveflow opens client configs read-only, always. `proveflow fix` writes proposed changes to
`proveflow-fixes/<flow>/` as separate patch files with rationale and expected trade-offs; the
user reviews and applies them manually.

## Rationale

- A security tool that corrupts the user's Claude Desktop/Cursor/VS Code config destroys trust
  permanently; config formats also differ subtly per client and version (see CLIENT_CONFIGS.md).
- The user must stay the authority on their own setup — mitigations like "remove this server"
  (M1) or "split profiles" (M2) are judgment calls with workflow costs only they can weigh.
- Review-before-apply matches how the fixes are verified: `verify` measures the mitigation in
  the twin, which is evidence for a human decision, not grounds for automation.

## Consequences

- Patch renderers must emit each client's exact syntax (verified facts in CLIENT_CONFIGS.md).
- A safety test asserts discovery never mutates fixture configs.
- Slightly worse UX than "click to fix" — accepted deliberately.
