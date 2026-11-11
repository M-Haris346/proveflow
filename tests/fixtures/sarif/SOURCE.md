# Pinned SARIF 2.1.0 JSON schemas

Downloaded byte-for-byte from the official OASIS document server on **2026-11-10**. Do not edit.
`tests/unit/test_sarif.py` checks the sha256 below before validating, so a modified file fails.

| File | Source URL | sha256 | JSON Schema draft |
|---|---|---|---|
| `sarif-schema-2.1.0-errata01.json` | <https://docs.oasis-open.org/sarif/sarif/v2.1.0/errata01/os/schemas/sarif-schema-2.1.0.json> | `c3b4bb2d6093897483348925aaa73af03b3e3f4bd4ca38cef26dcb4212a2682e` | draft-04 |
| `sarif-schema-2.1.0-os.json` | <https://docs.oasis-open.org/sarif/sarif/v2.1.0/os/schemas/sarif-schema-2.1.0.json> | `ad6db49878699b091f3eeb765b6e29e92a34bad4da88664d000c923b549c3a25` | draft-07 |

The errata01 version is the latest OASIS approved form of SARIF 2.1.0. proveflow's SARIF output
names it in `$schema` and is validated against **both** files.
