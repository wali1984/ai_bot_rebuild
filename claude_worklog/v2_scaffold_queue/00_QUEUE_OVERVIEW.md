# 00 — V2 Scaffold Queue Overview

**STATE:** `AWAITING_CODEX_RERUN`

**Banner:** 015A–015F are `status=blocked_approval`. The queue is **not**
cleared for wave dispatch. Codex flagged 8 blockers in
`06_CODEX_QUEUE_REVIEW.md`; remediation is recorded in
`07_REMEDIATION_CLOSURE.md`,
`../v2_scaffold_queue_remediation/017_REMEDIATION_REPORT.md`, and
`../v2_scaffold_queue_remediation/019_BLOCKER_FIX_REPORT.md`. The Codex
rerun on `04_CODEX_QUEUE_REVIEW_INPUT.md` is the sole remaining gate.

## Current gate

| Gate | File | Required value | Current value |
| --- | --- | --- | --- |
| Codex queue review (rerun) | `06_CODEX_QUEUE_REVIEW_RERUN.md` | green (no blockers) | not yet run |
| Codex queue GO/NO-GO | `06_CODEX_QUEUE_GO_NO_GO.md` | `V2_SCAFFOLD_QUEUE_CODEX_REVIEW_PASS` | `V2_SCAFFOLD_QUEUE_CODEX_REVIEW_BLOCKED` |
| Remediation closure | `07_REMEDIATION_GO_NO_GO.md` | `V2_SCAFFOLD_QUEUE_REMEDIATION_READY_FOR_CODEX_RERUN` | `V2_SCAFFOLD_QUEUE_REMEDIATION_READY_FOR_CODEX_RERUN` |
| Remediation report | `../v2_scaffold_queue_remediation/017_REMEDIATION_GO_NO_GO.md` | `SCAFFOLD_QUEUE_REMEDIATION_READY_FOR_CODEX_REVIEW` | `SCAFFOLD_QUEUE_REMEDIATION_READY_FOR_CODEX_REVIEW` |
| Blocker fix report | `../v2_scaffold_queue_remediation/019_GO_NO_GO.md` | `SCAFFOLD_QUEUE_REMEDIATION_READY_FOR_CODEX_REVIEW` | `SCAFFOLD_QUEUE_REMEDIATION_READY_FOR_CODEX_REVIEW` |

The queue cannot advance until the Codex rerun on
`04_CODEX_QUEUE_REVIEW_INPUT.md` returns
`V2_SCAFFOLD_QUEUE_CODEX_REVIEW_PASS` **and** an authorized human
approver flips each 015X task `status` from `blocked_approval` to
`approved`.

## Queue state table

| Task | Title | Wave | Depends on | Status |
| --- | --- | --- | --- | --- |
| 015a | V2 foundation scaffold | W1 | — | blocked_approval |
| 015b | V2 control-plane API scaffold | W2 | 015a | blocked_approval |
| 015c | V2 audit ledger scaffold | W2 | 015a | blocked_approval |
| 015d | V2 risk gateway scaffold | W3 | 015a, 015b, 015c | blocked_approval |
| 015e | V2 monitor center scaffold | W4 | 015a, 015b, 015c, 015d | blocked_approval |
| 015f | V2 GUI shell scaffold | W4 | 015a, 015b, 015c, 015d | blocked_approval |

Status values are normative: `blocked_approval` means "human approval
required before any wave dispatch". This file does not unblock any task.

## Read/Write boundaries

This file is part of the V2 scaffold queue planning package. Edits are
allowed under `claude_worklog/v2_scaffold_queue/**` per `CLAUDE.md`. No
file in `v2/**` may be authored from this remediation cycle.

## Pointers

- Codex blockers: `06_CODEX_QUEUE_REVIEW.md`
- Remediation report: `../v2_scaffold_queue_remediation/017_REMEDIATION_REPORT.md`
- Blocker-fix report: `../v2_scaffold_queue_remediation/019_BLOCKER_FIX_REPORT.md`
- Remediation gate: `../v2_scaffold_queue_remediation/017_REMEDIATION_GO_NO_GO.md`
- Closure ledger: `07_REMEDIATION_CLOSURE.md`
- Codex rerun gate: `07_REMEDIATION_GO_NO_GO.md`
- Codex rerun input: `04_CODEX_QUEUE_REVIEW_INPUT.md`
- Codex rerun output (next cycle): `06_CODEX_QUEUE_REVIEW_RERUN.md` (Codex authors)
- Waves: `01_IMPLEMENTATION_WAVES.md`
- DAG: `02_TASK_DEPENDENCY_GRAPH.md`
- Guardrails / canonical schemas: `03_SCAFFOLD_BUILD_GUARDRAILS.md`
- Architecture sequence: `../v2_architecture/17_IMPLEMENTATION_SEQUENCE_AND_MILESTONES.md`
- Audit ledger contract: `../v2_architecture/13_AUDIT_LEDGER_AND_AI_CHANGE_GOVERNANCE.md`
- Validator authoring (deferred): `../agent_supervisor/tasks/020_author_audit_evidence_validator.json`
