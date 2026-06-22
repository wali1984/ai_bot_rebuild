# Product Readiness Docs Index

Generated: 2026-06-14

Purpose: navigation index for AlphaForge v2 readiness monitoring artifacts. This file does not change readiness status and does not approve launch, paper/read-only release, `/trade`, `/market/:symbol`, admin security, or real live trading.

## Core monitoring artifacts

| Artifact | Use it for |
|---|---|
| `docs/product-readiness-docs-index.md` | Navigation index and source-of-truth artifact map for readiness monitoring docs. |
| `docs/product-readiness-current-status.md` | Short human-readable current posture and warning about historical PASS evidence. |
| `docs/product-readiness-monitor.md` | Current blocker posture, exact route-status mirror, evidence classification, source-of-truth precedence, local repository readiness metadata boundary, multi-trader account-scope smoke runner/artifact metadata boundary, credential vault readiness metadata boundary, admin audit readiness metadata boundary, durable paper audit policy blocker, alert CRUD/delivery/audit blocker, read-only alerts unavailable contract, and validation queue. |
| `docs/product-readiness-monitor-log.md` | Timestamped monitoring entries, status-history event slug coverage, and future validation result notes. |
| `docs/product-readiness-completion-checklist.md` | Requirement-by-requirement evidence, exact Phase 0-15 status coverage, and exact pending validation queue coverage needed before any monitored gate can be complete. |
| `docs/product-readiness-phase-blocker-map.md` | Phase-to-blocker mapping and evidence needed before each phase can advance. |
| `docs/product-readiness-blocker-owner-map.md` | Current blocker-to-workstream mapping, owner-label coverage, and required closure evidence. |
| `docs/product-readiness-change-control.md` | Rules and exact current status locks for moving statuses between `BLOCKED`, `IN PROGRESS`, and `PASS`. |
| `docs/product-readiness-monitor-runbook.md` | Procedure for status reviews, validation reruns, blocker closure, and no-PASS rules. |
| `docs/product-readiness-status.json` | Machine-readable current monitored status snapshot. |
| `docs/product-readiness-status-history.jsonl` | Append-only style machine-readable monitoring event history; structured evidence-key references must remain tracked in the current status snapshot. |
| `docs/product-readiness-evidence-status-ledger.md` | Human-readable ledger of every `last_current_evidence` key and status. |
| `docs/product-readiness-pending-evidence-ledger.md` | Human-readable ledger of every pending/current evidence key from `last_current_evidence`. |
| `docs/product-readiness-guardrail-ledger.md` | Human-readable ledger of every `guardrails` boolean from `docs/product-readiness-status.json`. |
| `docs/product-readiness-validation-queue-ledger.md` | Human-readable ledger of every pending validation command. |
| `docs/product-readiness-pending-evidence-validation-coverage-ledger.md` | Maps every pending validation command to the broad pending evidence groups it may cover after execution; not proof of execution. |
| `docs/product-readiness-blocker-closure-ledger.md` | Human-readable ledger of required closure evidence for every active blocker key. |
| `docs/product-readiness-current-blocker-ledger.md` | Human-readable ledger of every active `current_blockers` key. |
| `docs/product-readiness-history-event-ledger.md` | Human-readable ledger of every status-history JSONL event row. |
| `docs/product-readiness-history-supersession-ledger.md` | Human-readable ledger of historical status-history rows superseded by later current-state evidence. |
| `docs/product-readiness-status-snapshot-manifest-ledger.md` | Human-readable ledger of every top-level status snapshot key and shape. |
| `docs/product-readiness-source-artifact-existence-ledger.md` | Human-readable ledger of every source-of-truth artifact path existence state. |
| `docs/product-readiness-source-of-truth-ledger.md` | Human-readable ledger of every `source_of_truth` key and artifact path. |
| `docs/product-readiness-route-status-ledger.md` | Human-readable ledger of every monitored route status row from `route_status`. |
| `docs/product-readiness-route-closure-ledger.md` | Human-readable route-scoped closure evidence matrix for every active route blocker. |
| `docs/product-readiness-route-blocker-ledger.md` | Human-readable ledger of every route-level blocker row from `route_status`. |
| `docs/product-readiness-phase-launch-ledger.md` | Human-readable ledger of every `phase_status` and `launch_status` row. |
| `docs/phase-13a-visual-review.md` | Focused Phase 13A screenshot/visual review record; partial visual evidence only. |
| `docs/ui-defect-log-after.md` | Active UI defect log after the redesign passes; not closure evidence by itself. |
| `docs/product-readiness-status.schema.json` | Schema for the machine-readable readiness snapshot, including required exact source-of-truth, route-status, route-blocker, current-blocker, blocker-closure-ledger drift, current-blocker-ledger drift, evidence, evidence-status-ledger drift, validation-queue, validation-queue-ledger drift, launch/phase/guardrail key sets, repository/credential docs guard evidence, SQLAlchemy trader account repository evidence, multi-trader account-scope smoke runner evidence, multi-trader account-scope smoke artifact metadata, production stream alerting artifact metadata, production stream alerting smoke runner evidence, alert CRUD/delivery/audit blocker, read-only alerts unavailable contract evidence, credential permission-probe artifact evidence, signed-read validation artifact evidence, secret-redaction smoke artifact evidence, safe secret-redaction smoke runner, admin audit readiness metadata and retention-policy guard evidence, production paper actions fail closed evidence, durable paper audit policy artifact metadata, durable paper audit policy blocker/evidence, paper audit retention policy evidence, and validation queue keys. |
| `scripts/check_product_readiness_status.py` | Lightweight guard that checks no-PASS invariants, expected active blocker keys, exact source/evidence/route/blocker/queue key sets, source-of-truth artifact path existence, and status-history evidence-key coupling in `product-readiness-status.json`. |
| `scripts/check_readiness_docs_consistency.py` | Lightweight guard that checks human-readable readiness docs for no-PASS status drift, main monitor route-status drift, change-control status-lock drift, phase-progress tracker status drift, completion checklist phase-status drift, launch-readiness status drift, blocker owner label drift, completion checklist validation-queue drift, unsafe launch/live wording, evidence-status-ledger drift, pending-evidence ledger drift, pending-evidence validation coverage ledger drift, validation-queue-ledger drift, blocker-closure-ledger drift, current-blocker-ledger drift, history-event-ledger drift, status-snapshot-manifest-ledger drift, source-artifact-existence-ledger drift, source-of-truth-ledger drift, guardrail-ledger drift, route-status-ledger drift, route-closure-ledger drift, route-blocker-ledger drift, phase-launch-ledger drift, and status-history event monitor-log drift, and stale exchange-account scope wording in current docs, and history supersession ledger drift. |
| `scripts/check_product_readiness_schema_requirements.py` | Lightweight guard that checks the readiness status schema still requires exact source-of-truth, route-status, route-blocker, current-blocker, evidence, validation-queue, launch/phase/guardrail key sets. |
| `scripts/run_production_https_smoke.py` | Safe artifact validator for already-produced deployed HTTPS route/status/auth/console/no-live-mutation evidence; does not call exchanges or mutate live trading. |
| `scripts/run_production_trader_repository_smoke.py` | Safe artifact validator for already-produced durable trader repository/writer/isolation evidence; does not write repositories or mutate live trading. |
| `backend/app/services/deployment_readiness.py` | Admin-only sanitized production HTTPS smoke artifact metadata helper; partial evidence only until current validation and deployed smoke pass. |

## Existing readiness/status docs

| Artifact | Use it for |
|---|---|
| `docs/frontend-redesign-phase-progress.md` | Phase 0-15 implementation narrative, percentages, and exact machine-readable status tokens guarded against phase-progress tracker status drift. |
| `docs/frontend-redesign-master-todo.md` | Master phase table, immediate queue, and non-negotiable blocks. |
| `docs/redesign-acceptance-matrix.md` | Route-level visual/data/copy/test status. |
| `docs/launch-readiness.md` | Launch-specific readiness gates, production blockers, and exact machine-readable launch rows guarded against launch-readiness status drift. |
| `docs/data-source-inventory.md` | Data-source posture by route area. |
| `docs/api-gap-register.md` | Missing/partial endpoint and stream inventory. |
| `docs/auth-rbac-audit.md` | Auth/RBAC mechanism, fake role cleanup, route protection, and admin/security gaps. |
| `docs/visible-string-ledger.md` | Public/trader/admin copy ledger and forbidden-string cleanup posture. |
| `docs/trade-redesign-audit.md` | `/trade` redesign audit, data-source posture, and remaining terminal blockers. |
| `docs/phase-13a-visual-review.md` | Focused Phase 13A visual review notes; full Phase 13 remains incomplete. |
| `docs/ui-defect-log-after.md` | Active UI defect log and remediation notes; current validation and full route review remain pending. |

## Current authoritative posture

| Item | Status |
|---|---|
| `/` | IN PROGRESS |
| `/login` | IN PROGRESS |
| `/account-settings` | IN PROGRESS |
| `/status` | IN PROGRESS |
| `/dashboard` | IN PROGRESS |
| `/markets` | IN PROGRESS |
| `/markets/symbols` | IN PROGRESS |
| `/trade` | IN PROGRESS |
| `/trade/paper` | IN PROGRESS |
| `/market/:symbol` | IN PROGRESS |
| `/chart/:symbol` | IN PROGRESS |
| `/derivatives` | IN PROGRESS |
| `/signals` | IN PROGRESS |
| `/ai-predictions` | IN PROGRESS |
| `/ai-predictions/model-state` | IN PROGRESS |
| `/alerts` | IN PROGRESS |
| `/backtests` | IN PROGRESS |
| `/backtests/replay` | IN PROGRESS |
| `/research` | IN PROGRESS |
| `/research/technical-analysis` | IN PROGRESS |
| `/portfolio` | IN PROGRESS |
| `/portfolio/executions` | IN PROGRESS |
| `/portfolio/history` | IN PROGRESS |
| `/admin` | IN PROGRESS |
| `/admin/system` | IN PROGRESS |
| `/admin/ingestors` | IN PROGRESS |
| `/admin/trainer` | IN PROGRESS |
| `/admin/orchestrator` | IN PROGRESS |
| `/admin/risk` | IN PROGRESS |
| `/admin/traders` | IN PROGRESS |
| `/admin/execution` | IN PROGRESS |
| `/admin/exchanges` | IN PROGRESS |
| `/admin/config` | IN PROGRESS |
| `/admin/readiness` | IN PROGRESS |
| `/admin/users` | IN PROGRESS |
| `/admin/logs` | IN PROGRESS |
| `/admin/reports` | IN PROGRESS |
| `/system/*` | IN PROGRESS |
| `/admin/audit` | IN PROGRESS |
| `/admin/evidence` | IN PROGRESS |
| `/admin/scripts` | IN PROGRESS |
| `/admin/build-validation` | IN PROGRESS |
| `/admin/coverage` | IN PROGRESS |
| `/admin/migrations` | IN PROGRESS |
| `/admin/codex` | IN PROGRESS |
| `/admin/ai-tools` | IN PROGRESS |
| Phase 13 | IN PROGRESS |
| Phase 14 | IN PROGRESS |
| Phase 15 | BLOCKED |
| Paper/read-only launch | BLOCKED |
| Full product launch | BLOCKED |
| Real live trading | BLOCKED |
| Production-ready claim | BLOCKED |

Every `DOCS_TO_CHECK` entry must be present in `source_of_truth`. The evidence status ledger, pending evidence ledger, pending-evidence validation coverage ledger, validation queue ledger, blocker closure ledger, current blocker ledger, history event ledger, history supersession ledger, status snapshot manifest ledger, source artifact existence ledger, source-of-truth ledger, guardrail ledger, route status ledger, route closure ledger, route blocker ledger, and phase/launch ledger are source-of-truth artifacts. The evidence status ledger drift guard checks every `last_current_evidence` key/status row. The pending evidence ledger drift guard checks every `last_current_evidence` row. The pending-evidence validation coverage ledger drift guard checks every `pending_validation_queue` command has a documented evidence coverage row. The validation queue ledger drift guard checks every `pending_validation_queue` command row. The blocker closure ledger drift guard checks every active blocker closure evidence row. The status snapshot manifest ledger drift guard checks every top-level status snapshot row and shape. The current blocker ledger drift guard checks every `current_blockers` row. The source artifact existence ledger drift guard checks every `source_of_truth` path existence row. The source-of-truth ledger drift guard checks every `source_of_truth` key/path row. The guardrail ledger drift guard checks every `guardrails` row. The route status ledger drift guard checks every `route_status` status row. The route closure ledger drift guard checks every `route_status` blocker closure row. The route blocker ledger drift guard checks every `route_status` blocker row. The phase and launch ledger drift guard checks every `phase_status` and `launch_status` row. The history event ledger drift guard checks every JSONL status-history event row. The history supersession ledger drift guard checks known superseded history rows against current evidence status. The status-history event monitor-log drift guard checks every JSONL `event` slug is visible in `docs/product-readiness-monitor-log.md`. The status-history evidence-key snapshot guard checks every structured JSONL `details.evidence_key` remains present in `last_current_evidence`. The `source_of_truth` snapshot also includes all docs-consistency guard checked docs: `docs/frontend-redesign-master-todo.md`, `docs/api-gap-register.md`, `docs/auth-rbac-audit.md`, `docs/data-source-inventory.md`, `docs/visible-string-ledger.md`, and `docs/trade-redesign-audit.md`.

## Exact source-of-truth coverage

`docs/product-readiness-status.json` now explicitly tracks `docs/product-readiness-current-status.md`, `docs/product-readiness-status.json`, `docs/product-readiness-status-history.jsonl`, and `docs/product-readiness-guardrail-ledger.md` as source-of-truth artifacts alongside the other core monitor docs and guard scripts.

## 2026-06-14 source-of-truth registry audit

- The machine-readable `source_of_truth` snapshot currently contains 42 artifacts.
- Current status, monitor log, acceptance matrix, phase progress, launch readiness, visible-string ledger, trade audit, status snapshot, source-of-truth ledger, source-artifact existence ledger, route ledgers, blocker ledgers, phase/launch ledger, and validation queue ledger are all declared.
- Phase 13A visual review and the active UI defect log are now declared as source-of-truth artifacts because they are active visual/defect readiness evidence.
- This audit confirms registry coverage only. It does not execute validation, close blockers, or advance any route, phase, launch, admin security, paper/read-only, `/trade`, `/market/:symbol`, `/chart/:symbol`, or real live trading status.

## Exact guard coverage

The monitor now treats `exact source-of-truth, history-event-ledger drift, status-snapshot-manifest-ledger drift, source-of-truth ledger drift, source-artifact-existence-ledger drift, source-of-truth artifact existence, route-status, route-blocker, route-closure-ledger drift, route-blocker to global-current-blocker coupling, route-status-ledger drift, route-blocker-ledger drift, phase-launch-ledger drift, current-blocker, current-blocker key mirror, evidence, validation-queue, launch/phase/guardrail key sets, and guardrail-ledger drift` as explicit readiness guard surfaces. These checks are `PENDING` after the latest changes until `python scripts/check_product_readiness_status.py`, `python scripts/check_readiness_docs_consistency.py`, and `python scripts/check_product_readiness_schema_requirements.py` are rerun.

## Monitoring rule

If any existing doc conflicts with the monitor or completion checklist, keep the more conservative status until current evidence resolves the conflict.

Route-level blockers are represented in global `current_blockers`; drift is tracked as pending evidence until validation reruns.

## Machine-readable current blocker key mirror

These rows mirror `current_blockers` from `docs/product-readiness-status.json`. They are not closure evidence and do not mark any blocker resolved.

| Current blocker key | Status |
|---|---|
| `production_trader_account_repositories_and_writers_missing` | ACTIVE |
| `backend_only_binance_credential_vault_missing` | ACTIVE |
| `production_stream_validation_alerting_missing` | ACTIVE |
| `derivatives_realtime_sources_missing` | ACTIVE |
| `alert_crud_delivery_audit_repositories_missing` | ACTIVE |
| `production_paper_fill_writer_missing` | ACTIVE |
| `production_paper_submit_cancel_validation_missing` | ACTIVE |
| `durable_paper_audit_policy_missing` | ACTIVE |
| `production_auth_session_hardening_missing` | ACTIVE |
| `alembic_auth_revocation_admin_audit_migration_approval_missing` | ACTIVE |
| `full_phase13_visual_review_missing` | ACTIVE |
| `production_https_smoke_missing` | ACTIVE |
| `current_validation_rerun_pending` | ACTIVE |


## Auth/session hardening artifact metadata note

- auth/session hardening artifact metadata is partial evidence only and is exposed only through admin-protected readiness metadata.
- Evidence key `auth_session_hardening_artifact_metadata_after_latest_changes` remains `PENDING` until backend tests and the full validation queue are run.
- `production_auth_session_hardening_missing` remains ACTIVE until production evidence is produced, validated, reviewed, and accepted.
- Real live trading remains BLOCKED; this note does not add live submit/cancel/leverage/margin/live-gate mutation.
