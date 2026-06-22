# Product Readiness Phase Blocker Map

Generated: 2026-06-13

Purpose: map AlphaForge v2 phases to the blockers and evidence required before each phase can move forward. This file does not mark any phase, route, launch mode, or live trading state complete.

## Phase blocker map

| Phase | Current status | Primary blockers | Evidence required before advancement |
|---:|---|---|---|
| 0 | IN PROGRESS | Full baseline review not complete | Current route inventory, screenshot review, defect remediation, and docs consistency proof. |
| 1 | IN PROGRESS | Design system extraction incomplete | Shared component/style usage review and route coverage showing consistent professional UI patterns. |
| 2 | IN PROGRESS | Route migration and nav boundaries incomplete | Canonical route map, protected-route checks, public/trader nav cleanliness, and no stale legacy public links. |
| 3 | IN PROGRESS | Production auth/session hardening and durable credential vault incomplete | Alembic version-script approval gate, durable user store, durable token-revocation store, durable admin audit store, secure session/cookie config, revocation retention/rotation, admin audit readiness metadata beyond partial visibility, admin audit retention, environment-backed admin step-up partial evidence, MFA/step-up, admin user create/update/delete plus activation/reset audit events, durable credential vault integration beyond credential vault readiness metadata, secret-redaction smoke artifact metadata, and safe secret-redaction smoke runner, durable admin audit storage, full admin/superadmin API tests. |
| 4 | IN PROGRESS | Native streams, production trader repositories/writers, and alert repositories missing | Native exchange WebSocket/SSE adapters; production portfolio, execution, signal repositories/writers beyond explicit local repository readiness metadata; alert CRUD/delivery/audit repositories beyond the read-only unavailable contract; derivative repositories; source/freshness/stale/missing tests. |
| 5 | IN PROGRESS | Production public status and launch smoke missing | Public-safe `/status`, production monitoring source, incidents/maintenance source, HTTPS smoke, no secret/debug exposure. |
| 6 | IN PROGRESS | Dashboard full QA incomplete | Screenshot/copy/responsive review, current tests, trader-specific account data, and no stale/fake live claims. |
| 7 | IN PROGRESS | Market detail data blockers remain | Request-time public ticker/depth/trades and safe contract stream exist, but native streams, derivatives, signal evidence, source/freshness tests, current screenshots/tests remain incomplete. |
| 8 | IN PROGRESS | Trade terminal data and paper execution blockers remain | Native market streams, production paper submit/cancel validation, explicit paper-action request-scope validation rerun decision, durable paper audit policy, production trader isolation repositories/writers beyond local repository readiness metadata, credential vault validation beyond credential vault readiness metadata, current visual/copy/responsive/tests. |
| 9 | IN PROGRESS | Dedicated derivatives analytics incomplete | Funding, OI, liquidations, long/short, heatmap/map, exchange comparison, current source/freshness evidence. |
| 10 | IN PROGRESS | Signals/AI copy/evidence incomplete | Plain-language signal cards, targets/stops/invalidation, model/run evidence, current tests/screenshots. |
| 11 | IN PROGRESS | Portfolio/workflow routes incomplete | Trader-scoped portfolio, executions, history, backtests, research, alerts CRUD/notification/audit evidence and visual QA. |
| 12 | IN PROGRESS | Admin workflow hardening incomplete | Confirmation/reason/result/audit UI, backend enforcement, superadmin boundaries, and no live-gate bypass. |
| 13 | IN PROGRESS | Full route visual adjudication incomplete | Every visible route/card/table/chart/control reviewed at required viewports with PASS/FIXED/BLOCKED evidence. |
| 14 | IN PROGRESS | Current validation rerun pending | Backend pytest, readiness guards including repository/credential docs guard evidence key, typecheck, build, lint, focused Playwright, screenshot/overflow, and full Chromium after latest changes. |
| 15 | BLOCKED | Production launch evidence missing | Production HTTPS deployment smoke, env checks, auth/session hardening, public status, route smoke, no-live-mutation checks. |

## Current blocker key coverage

| Blocker key | Phase coverage | Monitoring note |
|---|---|---|
| `production_trader_account_repositories_and_writers_missing` | 4, 8, 11 | Durable trader-scoped repositories/writers are not production complete. |
| `backend_only_binance_credential_vault_missing` | 3, 8, 15 | Backend-only credential vault and signed-read account binding remain incomplete. |
| `production_stream_validation_alerting_missing` | 4, 5, 7, 8, 9, 10 | Production stream validation and alerting evidence is incomplete. |
| `derivatives_realtime_sources_missing` | 4, 7, 9 | Derivatives realtime sources and analytics validation remain incomplete. |
| `alert_crud_delivery_audit_repositories_missing` | 4, 11 | Alert CRUD, delivery, and audit repositories are incomplete. |
| `production_paper_fill_writer_missing` | 8, 11 | Production paper fill writer remains incomplete. |
| `production_paper_submit_cancel_validation_missing` | 8 | Production paper submit/cancel validation or disabled-submit decision remains incomplete. |
| `durable_paper_audit_policy_missing` | 8, 12, 15 | Durable paper audit policy and retention evidence remain incomplete. |
| `production_auth_session_hardening_missing` | 3, 12, 15 | Production auth/session hardening remains incomplete. |
| `alembic_auth_revocation_admin_audit_migration_approval_missing` | 3, 12, 15 | Auth revocation/admin audit migration approval remains incomplete. |
| `full_phase13_visual_review_missing` | 13, 15 | Full visual adjudication for all routes is incomplete. |
| `production_https_smoke_missing` | 5, 15 | Production HTTPS/deployment smoke evidence is missing. |
| `current_validation_rerun_pending` | 14, 15 | Validation queue has not been rerun after latest changes. |

## Route-specific hard blockers

| Route | Current status | Hard blockers |
|---|---|---|
| `/trade` | IN PROGRESS | Native market streams, production paper submit/cancel validation, explicit paper-action request-scope validation rerun, durable paper audit policy, production trader-scoped repositories/writers beyond local repository readiness metadata, backend-only credential vault/signed read-only adapter beyond credential vault readiness metadata and signed-read validation artifact metadata, current validation for shared symbol-data fallback removal, ProChart derivative overlay null-clear, explicit local repository/audit-backed open-order action guard, and full visual/copy/responsive QA. |
| `/market/:symbol` | IN PROGRESS | Native market streams, derivatives data including durable liquidation totals/heatmaps/exchange comparison, evidence/source freshness, current validation, full visual/copy/responsive QA. |

## Launch hard blockers

| Launch target | Current status | Hard blockers |
|---|---|---|
| Paper/read-only launch | BLOCKED | Current validation, public-safe production `/status`, production smoke, full route QA, durable data/account sources beyond local repository readiness metadata and credential vault readiness metadata. |
| Full product launch | BLOCKED | Phase 15 prerequisites, production auth hardening, deployment smoke, complete route/data/security/copy evidence. |
| Real live trading | BLOCKED | Explicit operator approval, superadmin live gate, environment-backed admin step-up partial evidence, MFA/step-up, audit, live safety checks, balance/reconciliation, kill switch, no stale data. |


## Auth/session hardening artifact metadata note

- auth/session hardening artifact metadata is partial evidence only and is exposed only through admin-protected readiness metadata.
- Evidence key `auth_session_hardening_artifact_metadata_after_latest_changes` remains `PENDING` until backend tests and the full validation queue are run.
- `production_auth_session_hardening_missing` remains ACTIVE until production evidence is produced, validated, reviewed, and accepted.
- Real live trading remains BLOCKED; this note does not add live submit/cancel/leverage/margin/live-gate mutation.
