# 03 — V2 Scaffold Build Guardrails

This file is normative. Every 015X task JSON must validate against the
canonical schemas declared here. The wave dispatcher must refuse to
dispatch any task whose JSON fails validation.

## gate_evidence_ref schema (canonical)

```yaml
type: array
description: |
  Eight ordered evidence pointers. Each element is a non-empty string.
  Slot order is normative — index N MUST hold a pointer that fulfils the
  role at index N. A pointer is one of:
    - file path (relative to repo root)
    - file path with line range (e.g. path:start-end)
    - URL of an artifact (Codex review, observability dashboard, etc.)
    - well-known marker token (e.g. "PENDING_HUMAN_APPROVAL")
minItems: 8
maxItems: 8
slots:
  0: claim                      # human-readable claim being defended
  1: raw_evidence_pointer       # raw source/line range/log/Redis key
  2: verification_command       # exact command a reviewer can run
  3: confidence                 # one of: high, medium, low, unverified
  4: missing_evidence           # gaps; "" when none
  5: codex_review_pointer       # Codex review URL or marker
  6: observability_pointer      # path to summary.json or dashboard URL
  7: rollback_pointer           # rollback runbook path or marker
```

A `gate_evidence_ref` array of length != 8 MUST be rejected.

## audit_evidence schema (canonical)

```yaml
type: object
required:
  - schema_version
  - claim
  - raw_evidence_pointer
  - verification_command
  - confidence
  - missing_evidence
  - codex_review_pointer
properties:
  schema_version:
    type: string
    enum: ["v1"]
  claim:
    type: string
    minLength: 1
  raw_evidence_pointer:
    type: string
    minLength: 1
  verification_command:
    type: string
    minLength: 1
  confidence:
    type: string
    enum: [high, medium, low, unverified]
  missing_evidence:
    type: string         # "" allowed; null is not allowed
  codex_review_pointer:
    type: string         # may be "PENDING" before Codex rerun
additionalProperties: false
```

`audit_evidence` is the body of every `gate_evidence_ref[1]` claim and
must round-trip into the audit ledger contract declared in
`../v2_architecture/13_AUDIT_LEDGER_AND_AI_CHANGE_GOVERNANCE.md`.

## observability summary.json requirement

Every 015X task MUST declare:

```yaml
observability:
  summary_json_required: true
  summary_json_path: <relative path the task will write at exit>
```

`summary.json` is the Monitor Center ingest contract. Tasks that do not
emit `summary.json` cannot satisfy W4 monitor-shell ingest and therefore
cannot pass W4 exit gate.

## Status floor

`status` MUST be one of `blocked_approval`, `approved`, `in_progress`,
`merged`, `abandoned`. Any 015X task with `status != "blocked_approval"`
while either remediation gate is red MUST be rejected by CI.

## CI hooks (referenced)

- `tools/validate_task_audit_evidence.py` — schema validator for
  `audit_evidence` and `gate_evidence_ref`. *(Not authored in this
  remediation cycle; tracked under B5 missing_evidence in
  `../v2_scaffold_queue_remediation/017_REMEDIATION_REPORT.md`.)*
- `tools/validate_task_dag.py` — DAG cycle detector and node-set
  consistency checker. *(Tracked alongside B5 follow-up.)*

## Read/Write boundaries

This file is part of `claude_worklog/v2_scaffold_queue/**`. It does not
authorize any file under `v2/**`.
