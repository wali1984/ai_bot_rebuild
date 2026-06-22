# Product Readiness Change Control

Generated: 2026-06-13

Purpose: status transition rules for AlphaForge v2 readiness monitoring. This document defines how a route, phase, or launch gate may move between `BLOCKED`, `IN PROGRESS`, and `PASS` without weakening evidence standards.

## Status transition rules

| From | To | Allowed only when |
|---|---|---|
| `BLOCKED` | `IN PROGRESS` | The blocking prerequisite has a concrete implementation path started, the blocker is still recorded, and no launch/completion claim is made. |
| `IN PROGRESS` | `PASS` | Every requirement in `docs/product-readiness-completion-checklist.md` for that item has current evidence. Historical PASS evidence is insufficient after later changes. |
| `PASS` | `IN PROGRESS` | A later code/docs/config/data-source change affects the proven scope and validation has not been rerun. |
| `PASS` | `BLOCKED` | A required external dependency, security gate, runtime source, or launch/safety invariant is missing or contradicted. |
| `BLOCKED` | `PASS` | Not allowed directly. Move through `IN PROGRESS` with current implementation and validation evidence. |

## Current machine-readable status locks

These rows mirror `docs/product-readiness-status.json` and exist only to prevent status-transition drift. They do not mark any item complete.

| Item | Required status now | Lock source |
|---|---|---|
| `/` | IN_PROGRESS | `route_status` |
| `/login` | IN_PROGRESS | `route_status` |
| `/account-settings` | IN_PROGRESS | `route_status` |
| `/status` | IN_PROGRESS | `route_status` |
| `/dashboard` | IN_PROGRESS | `route_status` |
| `/markets` | IN_PROGRESS | `route_status` |
| `/markets/symbols` | IN_PROGRESS | `route_status` |
| `/trade` | IN_PROGRESS | `route_status` |
| `/trade/paper` | IN_PROGRESS | `route_status` |
| `/market/:symbol` | IN_PROGRESS | `route_status` |
| `/chart/:symbol` | IN_PROGRESS | `route_status` |
| `/derivatives` | IN_PROGRESS | `route_status` |
| `/signals` | IN_PROGRESS | `route_status` |
| `/ai-predictions` | IN_PROGRESS | `route_status` |
| `/ai-predictions/model-state` | IN_PROGRESS | `route_status` |
| `/alerts` | IN_PROGRESS | `route_status` |
| `/backtests` | IN_PROGRESS | `route_status` |
| `/backtests/replay` | IN_PROGRESS | `route_status` |
| `/research` | IN_PROGRESS | `route_status` |
| `/research/technical-analysis` | IN_PROGRESS | `route_status` |
| `/portfolio` | IN_PROGRESS | `route_status` |
| `/portfolio/executions` | IN_PROGRESS | `route_status` |
| `/portfolio/history` | IN_PROGRESS | `route_status` |
| `/admin` | IN_PROGRESS | `route_status` |
| `/admin/system` | IN_PROGRESS | `route_status` |
| `/admin/ingestors` | IN_PROGRESS | `route_status` |
| `/admin/trainer` | IN_PROGRESS | `route_status` |
| `/admin/orchestrator` | IN_PROGRESS | `route_status` |
| `/admin/risk` | IN_PROGRESS | `route_status` |
| `/admin/traders` | IN_PROGRESS | `route_status` |
| `/admin/execution` | IN_PROGRESS | `route_status` |
| `/admin/exchanges` | IN_PROGRESS | `route_status` |
| `/admin/config` | IN_PROGRESS | `route_status` |
| `/admin/readiness` | IN_PROGRESS | `route_status` |
| `/admin/users` | IN_PROGRESS | `route_status` |
| `/admin/logs` | IN_PROGRESS | `route_status` |
| `/admin/reports` | IN_PROGRESS | `route_status` |
| `/system/*` | IN_PROGRESS | `route_status` |
| `/admin/audit` | IN_PROGRESS | `route_status` |
| `/admin/evidence` | IN_PROGRESS | `route_status` |
| `/admin/scripts` | IN_PROGRESS | `route_status` |
| `/admin/build-validation` | IN_PROGRESS | `route_status` |
| `/admin/coverage` | IN_PROGRESS | `route_status` |
| `/admin/migrations` | IN_PROGRESS | `route_status` |
| `/admin/codex` | IN_PROGRESS | `route_status` |
| `/admin/ai-tools` | IN_PROGRESS | `route_status` |
| Phase 0 | IN_PROGRESS | `phase_status` |
| Phase 1 | IN_PROGRESS | `phase_status` |
| Phase 2 | IN_PROGRESS | `phase_status` |
| Phase 3 | IN_PROGRESS | `phase_status` |
| Phase 4 | IN_PROGRESS | `phase_status` |
| Phase 5 | IN_PROGRESS | `phase_status` |
| Phase 6 | IN_PROGRESS | `phase_status` |
| Phase 7 | IN_PROGRESS | `phase_status` |
| Phase 8 | IN_PROGRESS | `phase_status` |
| Phase 9 | IN_PROGRESS | `phase_status` |
| Phase 10 | IN_PROGRESS | `phase_status` |
| Phase 11 | IN_PROGRESS | `phase_status` |
| Phase 12 | IN_PROGRESS | `phase_status` |
| Phase 13 | IN_PROGRESS | `phase_status` |
| Phase 14 | IN_PROGRESS | `phase_status` |
| Phase 15 | BLOCKED | `phase_status` |
| Full product launch | BLOCKED | `launch_status` |
| Paper/read-only launch | BLOCKED | `launch_status` |
| Real live trading | BLOCKED | `launch_status` |
| Production-ready claim | BLOCKED | `launch_status` |

## Route-specific transition gates

| Item | Minimum evidence before `PASS` |
|---|---|
| `/trade` | Current tests/build pass; screenshots visually approved; native market streams are wired with freshness/stale handling; backend-only credential vault/signed read-only account adapter is verified beyond credential vault readiness metadata; admin audit readiness metadata remains partial until production audit retention is proven; production trader repositories are verified beyond local repository readiness metadata; paper submit/cancel/fill policy and durable paper audit policy are verified; no live exchange mutation path exists. |
| `/market/:symbol` | Current tests/build pass; screenshots visually approved; ticker, depth, trades, derivatives, signals, evidence, stale, and missing states are sourced and tested. |
| `/status` | Public-safe fields only; production monitoring source or accepted degraded state; no logs/secrets/debug output; current tests and screenshots pass. |
| `/login` | Backend-authenticated flow; no role selector/fake admin; current tests and screenshots pass. |
| Public/trader nav | No forbidden admin/operator/developer wording; role boundaries tested after latest nav changes. |

## Phase-specific transition gates

| Phase | Cannot reach `PASS` until |
|---:|---|
| 3 | Production auth/session hardening, durable user storage, Alembic version-script approval gate closure for auth/revocation/admin-audit migrations, activation/reset flow with audit event, durable credential vault integration beyond credential vault readiness metadata, admin audit readiness metadata beyond partial visibility, environment-backed admin step-up partial evidence, MFA/step-up, and full admin/superadmin API coverage are verified. |
| 4 | Production data repositories/writers beyond local repository readiness metadata and native streams cover required market, portfolio, execution, signal, freshness, stale, and missing-source states. |
| 7 | `/market/:symbol` and markets surfaces pass visual/copy/responsive/current tests and realtime data blockers are resolved or explicitly accepted. |
| 8 | `/trade` passes terminal visual/copy/responsive/current tests and paper/realtime data blockers are resolved or explicitly accepted. |
| 13 | Every visible route/card/table/chart/control has screenshot review and remediation evidence. |
| 14 | Backend pytest, typecheck, build, lint, focused Playwright, screenshot/overflow, and full Chromium pass after latest relevant changes. |
| 15 | Production HTTPS deployment smoke, env checks, auth checks, public status, route smoke, and no-live-mutation checks pass. |

## Live trading transition rule

Real live trading must remain `BLOCKED` unless all of the following are true:

1. Explicit operator approval exists for a specific live activation scope.
2. Superadmin live-gate controls are backend-enforced.
3. environment-backed admin step-up partial evidence plus MFA/step-up and audit trail are complete.
4. Balance, reconciliation, open-order, open-position, kill-switch, and stale-data checks pass.
5. Live submit/cancel/leverage/margin behavior was explicitly approved and tested.
6. Production deployment and monitoring evidence exists.

If any item is missing, live trading remains `BLOCKED`.

## Evidence update procedure

1. Record new command/screenshot/deployment evidence in `docs/product-readiness-monitor-log.md`.
2. Update `docs/product-readiness-status.json` only for evidence produced after the latest relevant change.
3. Update route/phase docs only if the completion checklist row is satisfied.
4. If evidence is partial, keep status `IN PROGRESS` and add the remaining blocker, including durable paper audit policy when local-only paper audit evidence is not production durable.
5. If evidence is missing or contradicted, keep or move status to `BLOCKED`.

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
