# Dataset license audit

> Rule (CLAUDE.md): raw datasets are never committed to this repo. They are fetched at runtime
> with a pinned revision + checksum, and the license is recorded per normalized record.
> A source with an unclear or incompatible license is **dropped**.
>
> All rows verified from the linked official source on **2026-11-10**. Haris must review before
> Phase 6 (corpus) implementation.

| Dataset | License | Size / format | Location | Redistribution | Decision |
|---|---|---|---|---|---|
| **LLMail-Inject** | MIT | ~462k rows (371k Phase 1, 90.9k Phase 2); JSON + Parquet | <https://huggingface.co/datasets/microsoft/llmail-inject-challenge> | MIT permits, with attribution | **USE** (primary: adaptive human-written email-borne attacks) |
| **InjecAgent** | MIT | 1,054 test cases, 17 user tools, 62 attacker tools; JSONL/JSON in `data/` | <https://github.com/uiuc-kang-lab/InjecAgent> | MIT permits, with attribution | **USE** |
| **BIPIA** | MIT (code + repo, per `LICENSE`); but **data is mixed-origin** | 5 tasks (web/email/table QA, summarization, code QA); JSONL/JSON in `benchmark/` | <https://github.com/microsoft/BIPIA> | Web QA + Summarization source data must be downloaded from original sources per their own terms; README: "should only be used for research on indirect prompt injection attacks" | **USE-WITH-CARE**: only the attack texts and tasks whose source data ships in-repo (email QA, table QA, code QA attack files); **DROP** Web QA + Summarization contexts unless their upstream licenses are individually verified in Phase 6 |
| **AgentDojo** | MIT | task suites + injection tasks; pip package `agentdojo`; docs at agentdojo.spylab.ai | <https://github.com/ethz-spylab/agentdojo> | MIT permits, with attribution | **USE** (derive injection-task payloads) |

## Per-record requirements (Phase 6)

Every normalized corpus record carries: `source_dataset`, `source_id`, `license`, `sha256`,
dataset revision pin (git commit / HF revision), fetch checksum. Pins are chosen at Phase 6
implementation time and recorded here.

## Open items

- BIPIA: enumerate exactly which attack/context files are self-contained vs. externally sourced
  before writing its loader; record the per-task decision in this table. [research]
- LLMail-Inject: dataset is split across phases/scenarios; choose the stratified sample and
  revision pin in Phase 6. [research]
