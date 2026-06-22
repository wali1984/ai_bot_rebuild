# Product Readiness Blocker Owner Map

Generated: 2026-06-13

Purpose: map current AlphaForge v2 readiness blockers to responsible workstreams and required closure evidence. This file does not mark any blocker closed and does not approve launch, paper release, `/trade`, `/market/:symbol`, or real live trading.

## Blocker ownership map

| Blocker | Responsible workstream | Required closure evidence | Current status |
|---|---|---|---|
| Current validation rerun pending | QA / frontend / backend | Readiness guard, backend pytest, typecheck, build, lint, focused Playwright, screenshot/overflow, and full Chromium run after latest stream/repository/account changes. | OPEN |
| Production trader/account repositories and writers missing | Backend data / account platform | Production auth-scoped repositories and writer services for portfolio, positions, orders, executions, signals, and preview; tests proving trader isolation. Local repository integrity, readiness metadata, paper-account uniqueness, the multi-trader account-scope smoke runner, and multi-trader account-scope smoke artifact metadata are partial evidence only. The SQLAlchemy trader account repository adapter seam is also partial evidence until migrations/provisioning and production writer validation pass. | OPEN |
| Binance credential vault missing | Backend security / exchange integration | Durable backend-only credential vault integration; production permission probe, safe signed-read adapter validation, production secret-redaction smoke execution, and tests proving no key/secret leaks to frontend, docs, logs, screenshots, or safe API payloads. Env/local vault-file binding, credential vault readiness metadata, credential permission-probe artifact metadata, signed-read validation artifact metadata, secret-redaction smoke artifact metadata, and safe secret-redaction smoke runner are partial evidence only. | OPEN |
| Production stream validation/alerting missing | Market data / frontend realtime | WebSocket/SSE or equivalent streams for candles, ticker, full depth, recent trades, funding/OI/liquidations, signals, reconnect, stale, lag, missing-source states, production alerting, and dashboard current validation. Local stream alert history, production stream alerting artifact metadata, production stream alerting smoke runner, ProChart invalid OHLC filtering, and idle stream endpoint rotation are partial evidence only. Outbound alert webhook notifier/active-only alert delivery is partial evidence only. Request-time Binance public market endpoints are not a stream replacement. | OPEN |
| Derivatives realtime sources missing | Market data / derivatives analytics | Realtime and durable funding/OI history, liquidations, long/short, basis, exchange comparison, heatmap, and derivatives validation for `/markets`, `/market/:symbol`, and `/derivatives`. Read-only funding/OI snapshots and source-labeled liquidation stream/level runtime status are partial evidence only. | OPEN |
| Alert CRUD/delivery/audit repositories missing | Product backend / notifications | Trader-scoped alert repository, preferences, create/edit/mute/delete APIs, notification delivery channels, delivery audit logging, backend tests, frontend tests, screenshots, and production smoke. The read-only `/api/v2/alerts` unavailable contract is partial evidence only and does not close the alert product workflow. | OPEN |
| Production paper submit/cancel validation missing | Trading product / backend execution safety | Verified paper-only submit/cancel service or explicit product decision to keep submit/cancel disabled; tests proving no real exchange transport path is reachable. Explicit partial local paper execution policy metadata, production paper actions fail closed, paper preview scope binding, and structured repository-blocked envelopes are partial evidence only until current validation passes. | OPEN |
| Production paper fill writer missing | Trading product / backend execution safety | Production paper fill writer exists, is trader-scoped, persistent enough for production use, audited, covered by backend/frontend tests, and still separated from real exchange transport. Local paper fill writer and hash-chained local audit events are partial evidence only until production persistence, isolation validation, and current validation pass. | OPEN |
| Durable paper audit policy missing | Trading product / backend audit | Production durable retention, production writer hardening, and production audit verification for paper submit/cancel/fill evidence. Hash-chained local paper audit events, durable paper audit policy artifact metadata, and append-only local ledger/chain verification/window completeness are partial evidence only. | OPEN |
| Full Phase 13 visual QA missing | Product design / frontend QA | Screenshot review and remediation for every visible route, viewport, card, table, chart, control, empty state, stale state, and error state. | OPEN |
| Production auth/session hardening missing | Backend security / platform | Explicit approval to author Alembic version scripts, SQL-backed auth user, token-revocation, and admin-audit store migrations/provisioning, durable session store, secure cookies, secret rotation/revocation, revocation retention/rotation policy, admin audit retention policy, environment-backed admin step-up partial evidence, MFA/step-up, admin user create/update/delete plus activation/reset audit events, production local auth/revocation/audit-store access guards, durable admin audit storage, and full admin/superadmin API coverage. | OPEN |
| Alembic auth/revocation/admin-audit migration approval missing | Backend platform / release engineering | Human approval to add schema-defining Alembic version scripts under `backend/migrations/versions`, reviewed migration file, round-trip migration test, production deployment plan, rollback plan, and evidence that no legacy or production database was touched during validation. | OPEN |
| Production HTTPS smoke missing | Platform / release engineering | Deployed HTTPS route smoke, console checks, auth checks, public-safe status, no secret exposure, and no-live-mutation checks. | OPEN |
| Real live trading approval missing | Operator / superadmin safety | Explicit operator approval, superadmin live gate, environment-backed admin step-up partial evidence, MFA/step-up, local audit event partial evidence, durable audit trail, balance/reconciliation/open-order/open-position/kill-switch/stale-data checks. | BLOCKED |

## No status promotion rule

If a blocker is `OPEN` or `BLOCKED` in this file, any dependent route, phase, launch mode, or live trading status must remain `IN PROGRESS` or `BLOCKED` in the readiness monitor.

## Machine-readable blocker keys

These keys mirror `docs/product-readiness-status.json` `current_blockers`. They must remain visible until the blocker is closed with current evidence.

| Blocker key | Human-readable owner row | Status |
|---|---|---|
| `production_trader_account_repositories_and_writers_missing` | Production trader/account repositories and writers missing | OPEN |
| `backend_only_binance_credential_vault_missing` | Binance credential vault missing | OPEN |
| `production_stream_validation_alerting_missing` | Production stream validation/alerting missing | OPEN |
| `derivatives_realtime_sources_missing` | Derivatives realtime sources missing | OPEN |
| `alert_crud_delivery_audit_repositories_missing` | Alert CRUD/delivery/audit repositories missing | OPEN |
| `production_paper_fill_writer_missing` | Production paper fill writer missing | OPEN |
| `production_paper_submit_cancel_validation_missing` | Production paper submit/cancel validation missing | OPEN |
| `durable_paper_audit_policy_missing` | Durable paper audit policy missing | OPEN |
| `production_auth_session_hardening_missing` | Production auth/session hardening missing | OPEN |
| `alembic_auth_revocation_admin_audit_migration_approval_missing` | Alembic auth/revocation/admin-audit migration approval missing | OPEN |
| `full_phase13_visual_review_missing` | Full Phase 13 visual QA missing | OPEN |
| `production_https_smoke_missing` | Production HTTPS smoke missing | OPEN |
| `current_validation_rerun_pending` | Current validation rerun pending | OPEN |

## Production HTTPS Smoke Runner Boundary

- `scripts/run_production_https_smoke.py` can validate already-produced deployed HTTPS smoke artifacts for route coverage, public-safe status, auth gates, console checks, secret exposure, and no-live-mutation flags.
- Evidence key `production_https_smoke_runner_after_latest_changes` remains `PENDING` until its unit test and the full validation queue are run.
- `production_https_smoke` remains `MISSING`; this runner does not by itself prove a deployed HTTPS smoke was performed.
- Real live trading remains `BLOCKED`; the runner does not submit, cancel, or mutate exchange/live-gate state.


## Auth/session hardening artifact metadata note

- auth/session hardening artifact metadata is partial evidence only and is exposed only through admin-protected readiness metadata.
- Evidence key `auth_session_hardening_artifact_metadata_after_latest_changes` remains `PENDING` until backend tests and the full validation queue are run.
- `production_auth_session_hardening_missing` remains ACTIVE until production evidence is produced, validated, reviewed, and accepted.
- Real live trading remains BLOCKED; this note does not add live submit/cancel/leverage/margin/live-gate mutation.
