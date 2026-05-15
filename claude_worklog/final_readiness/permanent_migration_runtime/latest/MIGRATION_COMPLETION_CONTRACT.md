# Permanent Migration Completion Contract

Generated: `2026-05-15`
Scope: V2 Permanent Migration Fix and Professional Frontend Runtime Readiness.
Live gate: `blocked_human_only`. Live symbols: `[]`. Final live approval token: `absent`.

## Purpose

This contract is the single binding definition of when a V2 component may be classified
`MIGRATED_CODEX_PASS`. Every status generator, dashboard payload, and worker inventory
in this repository must use this definition. Any artifact that calls a component
"READY" without satisfying every clause below is rejected by the permanent objective
router (see [v2_permanent_objective_router.py](../../../tools/v2_permanent_objective_router.py)).

## Hard prerequisites for MIGRATED_CODEX_PASS

A component may be classified `MIGRATED_CODEX_PASS` only when all of the following are
true. If any one is missing, the component is downgraded to a non-final classification.

1. **Legacy source paths identified.** A list of the legacy paths the component is
   migrating from. Stored in `legacy_behavior_mapping.json` for the worker.
2. **SHA256 cited.** SHA256 of each legacy file cited from one of:
   * `claude_worklog/legacy_runtime_closure/full_runtime_copied_source_manifest.json`
   * `claude_worklog/legacy_baseline/copied_baseline_manifest.json`
   when the worker is in the baseline scope.
3. **Dependency closure complete.** Worker has a closed dependency graph in
   `trainer_dependency_closure_final.json` (for trainer) or
   `legacy_dependency_closure.json` (for non-trainer workers), with no unresolved
   imports or unsafe-unknown chunks.
4. **Config and env mapping complete.** Every legacy config/env value the worker reads
   has a documented V2 mapping (`*_config_env_parity.json`).
5. **Legacy behavior mapping complete.** Each public legacy behavior the worker
   implements is mapped to a V2 function (`*_legacy_behavior_mapping.json`).
6. **V2 implementation exists.** V2 code under `v2/backend/app/services/<worker>/` or
   `v2/backend/app/cli/v2_<worker>.py`.
7. **Tests cover legacy-equivalent behavior.** V2 integration tests under
   `v2/backend/tests/integration/cli/` (or sibling) exercise the legacy behavior path,
   not just smoke-import the module.
8. **Public runtime payload exists.** V2 worker publishes
   `v2/frontend/public/operator_runtime/<worker>/latest/<worker>_status.json`
   and the payload includes `live_gate`, `live_symbols`, `generated_at`, and the
   `evidence_classification` field used by `freshness_guard`.
9. **Codex PASS exists.** A Codex review file under
   `claude_worklog/final_readiness/<area>/latest/codex_review/CODEX_REVIEW.md` exists
   with a top-line `GO/NO-GO: CODEX_REVIEW_*_PASS` and no blocking findings.
10. **No old Redis writes.** A grep proof in the worker's evidence packet (or
    cited from `forbidden_redis_writers.json`) shows the worker never writes to a
    legacy `mass_*`, `proposal:legacy:*`, or other legacy key.
11. **No exchange mutation.** A grep proof shows the worker never invokes order
    placement, cancellation, modification, leverage change, or margin-mode change
    paths.
12. **`live_gate` remains `blocked_human_only`** in the worker's runtime payload.
13. **`live_symbols` remains `[]`** in the worker's runtime payload.

If any prerequisite is unverifiable from raw evidence, the component is classified
`UNVERIFIED` and the router opens a remediation task with that worker's name.

## Permitted non-final classifications

Components that do not meet every clause above MUST be classified as one of:

| Classification | Meaning |
|----------------|---------|
| `NOT_STARTED` | No V2 code, no payload, no tests. |
| `DESCRIPTOR_ONLY` | Worker has metadata or a description but no executable V2 code. |
| `BACKLOG_ONLY` | Worker is referenced as backlog/planning text and is not implemented. |
| `PARTIALLY_MIGRATED` | Some legacy behavior is covered, but at least one clause above fails. |
| `READONLY_BRIDGED` | Worker is a read-only bridge over legacy outputs; cannot stand on its own. |
| `PAPER_ONLY` | Worker is verified for paper/shadow runtime but not for live/canary. |
| `FAIL_CLOSED_STUB` | Worker is intentionally a deny-by-default stub for safety. |
| `BLOCKED_BY_PARITY` | Worker depends on another worker that has not reached `MIGRATED_CODEX_PASS`. |
| `BLOCKED_BY_EDGE` | Worker is correct in code but paper edge is unproven; live/canary blocked. |
| `BLOCKED_BY_PERMISSION` | Worker is correct but exchange/account permission evidence is missing. |
| `OPERATOR_DECISION_REQUIRED` | Worker can advance only after explicit operator acceptance. |
| `MIGRATED_CODEX_PASS` | All 13 clauses above are satisfied. |

`READY`, `COMPLETE`, `DONE`, `GREEN`, and other informal terms are **not** valid
classifications and must be rewritten to one of the values above by the router or
by Codex review when encountered in a status generator.

## Status generator obligations

Every script that emits a status payload (worker porting orchestrator, decision
observatory, shutdown readiness takeover, frontend operator dashboard, etc.) must:

1. Import or reproduce the classification vocabulary above.
2. Refuse to emit `MIGRATED_CODEX_PASS` unless all 13 prerequisites are satisfied
   from raw evidence (file existence + SHA256 + payload presence + Codex file).
3. Emit the per-worker `evidence_status` field with one of the values above.
4. Emit the `evidence_missing` list of clause IDs (1..13) that failed, where
   applicable.

The permanent objective router enforces this by inspecting status payloads on each
tick and downgrading any payload that claims `MIGRATED_CODEX_PASS` without
satisfying every prerequisite.

## Anti-drift rule

The contract is the only place where the prerequisites for migration completeness are
defined. Any other artifact that introduces a competing definition is treated as
drift and must be reconciled to this contract.

This contract does not authorize live trading, canary trading, legacy shutdown, or
Redis trim.
