# 01 — Implementation Waves

## 1. Purpose
Define the wave grouping under which queue tasks `015A`–`015F` may be dispatched. A wave is a set of tasks whose `gate_evidence_ref` floors are simultaneously satisfied. Tasks within the same wave MAY run in parallel (separate Claude sessions); tasks across waves MUST run in sequence.

The supervisor enforces wave ordering via the per-task `depends_on` field; this document explains the rationale.

## 2. Wave summary

| Wave | Tasks | Rationale |
|------|-------|-----------|
| W1 | 015A, 015E | The repo skeleton (015A) and the test/CI skeleton (015E) are the cheapest to roll back and surface no runtime behavior. CI gates everything downstream, so it is paired with the skeleton at the earliest possible point. |
| W2 | 015B | Database migration skeleton runs on top of the repo skeleton (Alembic config under `v2/backend/migrations/` requires `pyproject.toml` + `alembic.ini` from W1). The skeleton creates the harness only; no migration files are written. |
| W3 | 015C | API route skeleton fills empty routers under `v2/backend/app/api/v1/` and middleware shells. Routers consume schemas (which depend on DB-side type imports) so 015C runs after 015B. Test vectors stay as fixtures (no real handlers). |
| W4 | 015D | Enterprise frontend shell. Pages call the API surface for stub responses; therefore 015D runs after 015C. |
| W5 | 015F | Agent supervisor / dashboard integration wires the supervisor's `queue_status.json`, agent health, validation-artifact catalog, and dashboard stale-state alerts into the V2 backend/frontend shells. Requires 015A through 015D to exist as targets to integrate. |

## 3. Per-task gate evidence floor
Every task carries the global floor from `00_QUEUE_OVERVIEW.md` §6 plus its per-task additions:

| Task | Per-task additions |
|------|--------------------|
| 015A | none beyond the global floor |
| 015B | 015A complete + `B_SCAFFOLD_VALIDATION.md` present + `12A_DATABASE_LINEAGE_CLOSURE.md` checksum verified |
| 015C | 015B complete + `C_DATABASE_SKELETON_VALIDATION.md` present + `12B_API_LINEAGE_ENFORCEMENT_CLOSURE.md` checksum verified |
| 015D | 015C complete + `D_API_SKELETON_VALIDATION.md` present + `06_ENTERPRISE_GUI_UX_ARCHITECTURE.md` page list still equals 26 |
| 015E | 015A complete (CI runs against the skeleton; runs in parallel with 015B–D as those tasks complete) |
| 015F | 015A through 015E complete + `agent_supervisor_reliability/04_GO_NO_GO.md` ready + `B_TEST_CI_VALIDATION.md` present |

The supervisor records each `gate_evidence_ref` resolution in the audit ledger at dispatch time.

## 4. Parallelism rules
- W1 (015A + 015E): MAY run in parallel only if (i) 015A's writes are confined to non-CI paths under `v2/backend` and `v2/frontend`, and (ii) 015E's writes are confined to `v2/ops/ci/` and `v2/.github/workflows/`. The supervisor's pre-dispatch check enforces non-overlapping write paths.
- W2/W3/W4: strictly sequential (each consumes the prior wave's validation artifact as input).
- W5 (015F): single task; runs after W4.

## 5. Reviewer assignments per wave
Per `06_AGENT_SUPERVISED_BUILD_SEQUENCE.md` §5:

| Wave | Authoring | Reviewer |
|------|-----------|----------|
| W1 | Claude | Claude self-review on import graph; Codex adversarial pass on module boundaries (015A) and CI workflow (015E) |
| W2 | Claude | Claude self-review on Alembic harness; Codex on the constraint-coverage matrix (015B) |
| W3 | Claude | Codex on middleware order and error-taxonomy enumeration (015C) |
| W4 | Claude | Claude on RBAC + banner; Codex on default-deny inventory (015D) |
| W5 | Claude | Codex on dashboard wiring + agent governance (015F) |

Codex never authors V2 code; Codex only reviews. Ollama summarizes draft outputs to support Claude but never approves.

## 6. Wave-level human approvals
- W1 unblock: human L2 approval for both 015A and 015E.
- W2 unblock: human L2 approval for 015B AFTER Codex passes the W1 review and the W1 validation artifacts are present.
- W3, W4, W5: same pattern — human L2 approval per task AFTER Codex passes the prior wave.
- No wave is auto-unblocked. The supervisor never flips `blocked_approval` to `pending` on its own.

## 7. Wave-level rollback
- If W1 rolls back, all of `v2/**` must be removed and the W1 validation artifacts deleted. W2–W5 must remain blocked.
- If a downstream wave rolls back, the supervisor refuses to dispatch any later wave until the failed wave's validation artifact is regenerated and re-reviewed.

## 8. Wave-level audit
Each wave dispatch records:
- `wave_id` (W1–W5)
- `gate_evidence_ref[]` resolved
- `verified_by[]` reviewers
- `dispatch_authorized_by` (human subject)
- `dispatch_ts`

These rows are written to the audit ledger and surfaced on the Build/Validation Status page once 015D + 015F land.

## 9. Status
WAVES: PLANNED. EXECUTION: BLOCKED PENDING CODEX QUEUE REVIEW + HUMAN APPROVAL.