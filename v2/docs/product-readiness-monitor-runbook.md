# Product Readiness Monitor Runbook

Generated: 2026-06-13

Purpose: operational runbook for continuing AlphaForge v2 readiness monitoring until all phases are complete. This runbook does not approve launch, paper/read-only release, `/trade`, `/market/:symbol`, admin security, or real live trading.

## Monitoring cadence

Use this sequence whenever readiness status is reviewed after code, doc, data-source, deployment, or test changes:

1. Check `docs/product-readiness-status.json` for the current machine-readable snapshot.
2. Check `docs/product-readiness-completion-checklist.md` before moving any route, phase, or launch gate forward.
3. Treat older PASS evidence as historical if any relevant source file changed afterward.
4. If validation was not rerun after the latest change, keep Phase 14 `IN_PROGRESS`.
5. If production smoke was not run against a deployed HTTPS URL, keep Phase 15 `BLOCKED`.
6. If production stream alerting/dashboard current validation or production repositories/writers are missing, keep `/trade` and `/market/:symbol` `IN_PROGRESS`.
7. The local stream alert history, production stream alerting artifact metadata, production stream alerting smoke runner, and outbound alert webhook notifier/active-only alert delivery are partial evidence only; they do not replace production alerting/dashboard current validation.
8. If backend-only credential vault/signed read-only account adapter, production paper execution validation decisions, or durable paper audit policy are missing, keep `/trade` `IN_PROGRESS`.
9. If live submit/cancel/leverage/margin/live-gate mutation approval is missing, keep real live trading `BLOCKED`.

## Standard status check

Use the following checks conceptually before editing status docs:

| Check | Required result before advancing status |
|---|---|
| Current validation | Backend pytest, typecheck, build, lint, focused Playwright, screenshot/overflow, and full Chromium pass after latest relevant changes. |
| Readiness guard exactness | Status/schema/docs guards enforce exact source-of-truth, route-status, route-blocker, current-blocker, evidence, validation-queue, launch/phase/guardrail key sets before any route, phase, or launch status can advance. |
| Visual QA | All required screenshots exist and have human-reviewed PASS/FIXED state for every relevant route, not only a focused subset. |
| Data honesty | Every fallback/static/unavailable state remains labeled with source/freshness/stale/missing fields. |
| Trader isolation | Account-sensitive data is scoped by backend-authenticated trader/account repositories, not URL/browser storage. |
| Local repository integrity | Local paper-account IDs are unique across traders, and protected admin status surfaces repository integrity. This is partial evidence only until durable production tenancy constraints exist. |
| Realtime data | Candles, ticker, full depth, recent trades, derivatives, signals, stale/reconnect/missing-source behavior are backed by native streams or production repositories. Safe contract streams are useful but not production realtime completion by themselves. |
| Stream alerting | The local stream alert history, production stream alerting artifact metadata, production stream alerting smoke runner, and outbound alert webhook notifier/active-only alert delivery are partial evidence only; production alerting/dashboard current validation must be connected and validated before closing the stream alerting blocker. |
| Paper audit policy | Paper submit/cancel/fill evidence has production durable retention, production writer hardening, audit verification, and tests proving no exchange transport is reached. Hash-chained local paper audit events and append-only local ledger/chain verification/window completeness are partial evidence only. |
| Auth/RBAC | Production-ready user/session storage, secure cookies/secrets, revocation/rotation, environment-backed admin step-up partial evidence, MFA/step-up, and full admin/superadmin API enforcement are verified. |
| Launch smoke | Deployed HTTPS URL passes route smoke, public-safe `/status`, console checks, auth checks, and no-live-mutation checks. |

## Visual/defect evidence docs rule

`docs/phase-13a-visual-review.md` and `docs/ui-defect-log-after.md` are source-of-truth artifacts because they carry active visual-review and defect-remediation evidence.

These docs intentionally include historical `PASS`, `FIXED`, and historical test-result wording. Treat those entries as historical/partial evidence unless all of the following are true:

1. The evidence was produced after the latest relevant code/docs change.
2. The route, viewport, test, and data/security scope exactly match the gate being advanced.
3. The completion checklist row for the affected route/phase/launch gate is satisfied.
4. A historical-evidence-aware guard or manual review confirms the wording does not promote a current `PASS` claim.

Do not add these docs to a generic no-PASS scan without first teaching the guard to distinguish historical evidence from current promotion. Until then, keep `full_phase13_visual_review_missing` and `current_validation_rerun_pending` active.

## Validation rerun procedure

Run only when explicitly approved for validation:

```bash
python scripts/check_product_readiness_status.py
python scripts/check_readiness_docs_consistency.py
python scripts/check_product_readiness_schema_requirements.py
../.venv/bin/python -m pytest backend/tests/integration/api/test_auth_rbac_and_status.py backend/tests/integration/api/v2/test_market_contract_routes.py
../.venv/bin/python -m pytest backend/tests/unit/scripts/test_run_alembic_auth_migration_approval_smoke.py
../.venv/bin/python -m pytest backend/tests/unit/api/test_readonly_market_stream_parser.py
../.venv/bin/python -m pytest backend/tests/unit/scripts/test_run_derivatives_realtime_source_smoke.py
../.venv/bin/python -m pytest backend/tests/unit/scripts/test_run_production_stream_alerting_smoke.py
../.venv/bin/python -m pytest backend/tests/unit/scripts/test_run_production_alert_delivery_audit_smoke.py
../.venv/bin/python -m pytest backend/tests/unit/scripts/test_run_production_https_smoke.py
../.venv/bin/python -m pytest backend/tests/unit/scripts/test_run_durable_credential_vault_smoke.py
../.venv/bin/python -m pytest backend/tests/unit/scripts/test_run_auth_session_hardening_smoke.py
../.venv/bin/python -m pytest backend/tests/unit/scripts/test_run_trader_account_scope_smoke.py
../.venv/bin/python -m pytest backend/tests/unit/scripts/test_run_production_trader_repository_smoke.py
../.venv/bin/python -m pytest backend/tests/unit/scripts/test_check_readiness_docs_consistency.py
npm run typecheck
npm run build
npm run lint --if-present
npx playwright test tests/e2e/trade_terminal_redesign.spec.ts --project=chromium
npx playwright test tests/e2e/market_detail_redesign.spec.ts --project=chromium
npx playwright test tests/e2e/api_v2_contract_states.spec.ts --project=chromium
npx playwright test tests/e2e/trader_nav_cleanliness.spec.ts --project=chromium
npx playwright test tests/e2e/pro_chart_realtime_contract.spec.ts --project=chromium
npx playwright test tests/e2e/redesign_screenshot_overflow.spec.ts --project=chromium
npx playwright test tests/e2e/symbols_route_readonly_contract.spec.ts --project=chromium
../.venv/bin/python -m pytest backend/tests/unit/scripts/test_run_phase13_visual_review_smoke.py
../.venv/bin/python -m pytest backend/tests/unit/scripts/test_run_current_validation_evidence_smoke.py
npx playwright test --project=chromium
../.venv/bin/python -m pytest backend/tests/unit/scripts/test_run_durable_paper_audit_policy_smoke.py
../.venv/bin/python -m pytest backend/tests/unit/scripts/test_run_production_paper_action_validation_smoke.py
../.venv/bin/python -m pytest backend/tests/unit/services/website/test_website_contracts.py
```

The first guard only checks the machine-readable no-PASS monitoring snapshot and expected active blocker keys. The second guard checks human-readable readiness docs for status drift and unsafe PASS wording. The third guard checks that the status schema still requires exact source-of-truth, route-status, route-blocker, current-blocker, evidence, validation-queue, launch/phase/guardrail key sets. None of these guards proves build health, visual QA, launch readiness, realtime data, or live trading readiness.

## Stream alert notifier controls

The outbound alert webhook notifier/active-only alert delivery is disabled by default and may only send public market-data stream freshness payloads.

| Environment variable | Purpose | Safe default |
|---|---|---|
| `ALPHAFORGE_MARKET_STREAM_ALERT_WEBHOOK_URL` | Optional HTTPS webhook endpoint for market stream freshness alerts. The URL is never exposed in safe API responses. | unset |
| `ALPHAFORGE_MARKET_STREAM_ALERT_WEBHOOK_ENABLED` | Explicit enable flag for outbound alert delivery. | false |
| `ALPHAFORGE_MARKET_STREAM_ALERT_WEBHOOK_TIMEOUT_MS` | Delivery timeout, clamped between 100ms and 5000ms. | 1500 |
| `ALPHAFORGE_MARKET_STREAM_ALERT_ALLOW_INSECURE_WEBHOOK` | Allows HTTP only for local testing. Do not use for production. | false |

After rerun:

1. Record exact command results in `docs/product-readiness-monitor-log.md`.
2. Update `docs/product-readiness-status.json` only if the result changes current evidence posture.
3. Update `docs/redesign-acceptance-matrix.md` and `docs/frontend-redesign-phase-progress.md` only for gates proven by current evidence.
4. Do not change `/trade`, `/market/:symbol`, Phase 15, paper launch, full launch, or real live trading to `PASS` unless their completion-checklist rows are fully satisfied.

## Blocker closure protocol

| Blocker | Closure protocol |
|---|---|
| Current validation rerun pending | Run full validation queue after latest changes and record results. |
| Production trader repositories/writers missing | Implement production account-scoped repositories/writers and tests proving trader isolation. Local repository integrity, paper-account uniqueness, the read-only multi-trader account-scope smoke runner, and multi-trader account-scope smoke artifact metadata are partial evidence only. To generate a local scope artifact from already-produced auth/account repository evidence, run `scripts/run_trader_account_scope_smoke.py --auth-users-path <auth-users-json> --trader-accounts-path <trader-accounts-json> --output <artifact.json>` after validation approval, then set `ALPHAFORGE_TRADER_ACCOUNT_SCOPE_SMOKE_ARTIFACT=<artifact.json>` for protected backend readiness metadata. |
| Binance credential vault missing | Add durable backend-only credential vault integration and secret redaction tests; never expose secrets in safe payloads. Env/local vault-file binding is partial evidence only; credential vault readiness metadata, permission-probe/signed-read/secret-redaction artifact metadata, and the safe secret-redaction smoke runner are also partial evidence only. To generate a smoke artifact, run `scripts/run_secret_redaction_smoke.py --safe-api-payload-path <safe-payloads> --log-path <logs> --screenshot-path <screenshots> --screenshots-reviewed --output <artifact.json>` after validation approval, then set `ALPHAFORGE_SECRET_REDACTION_SMOKE_ARTIFACT=<artifact.json>` for backend readiness status. |
| Production stream validation/alerting missing | The local stream alert history, production stream alerting artifact metadata, production stream alerting smoke runner, and outbound alert webhook notifier/active-only alert delivery are partial evidence only. Add native exchange WebSocket/SSE adapters or equivalent production streams plus stale/reconnect/missing-source tests, lag monitoring, and production alert/dashboard current validation. To generate a smoke artifact from already-produced public-safe evidence, run `scripts/run_production_stream_alerting_smoke.py --alerting-config-path <alerting-json> --dashboard-evidence-path <dashboard-json> --stream-status-path <stream-status-json> --output <artifact.json>` after validation approval, then set `ALPHAFORGE_MARKET_STREAM_PRODUCTION_ALERTING_ARTIFACT=<artifact.json>` for backend stream-status metadata. |
| Paper fill writer missing | Local paper staging/cancel/fill exists with explicit no-auto-fill policy and production paper actions fail closed; implement or verify a production trader-scoped paper fill/execution writer and audit path before closing. |
| Durable paper audit policy missing | Define and validate production durable paper audit retention, production writer hardening, and audit verification before closing `/trade` paper execution readiness. Hash-chained local paper audit events, durable paper audit policy artifact metadata, and append-only local ledger/chain verification/window completeness are partial evidence only. |
| Full visual QA missing | Review all routes/cards/tables/charts/screenshots and record PASS/FIXED/BLOCKED. |
| Production hardening missing | Verify auth/session/security/deployment smoke over HTTPS. |

## No-PASS rules

- Do not mark `/trade` PASS while production stream alerting/dashboard current validation, production credential-vault hardening, signed read-only account validation, local paper submit/cancel/fill production validation, or durable paper audit policy are missing.
- Do not mark `/market/:symbol` PASS while production stream alerting/dashboard current validation or derivatives are missing.
- Do not mark Phase 14 PASS while validation is pending after latest changes.
- Do not mark Phase 15 PASS without production HTTPS smoke and launch verification.
- Do not mark paper/read-only launch PASS while `/status`, auth posture, public/trader route checks, and production smoke are incomplete.
- Do not mark full product launch PASS while production deployment, HTTPS smoke, route smoke, auth/session hardening, durable data sources, and full visual/copy QA are incomplete.
- Do not mark admin security PASS while production auth/session hardening, durable user/session/revocation/admin-audit storage, admin/superadmin API audit, and current validation are incomplete.
- Do not mark any monitored route PASS unless current route-scoped evidence closes its blocker set.
- Do not mark real live trading PASS without explicit operator approval and full live-gate safety evidence.

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

## Production HTTPS Smoke Runner Boundary

- `scripts/run_production_https_smoke.py` can validate already-produced deployed HTTPS smoke artifacts for route coverage, public-safe status, auth gates, console checks, secret exposure, and no-live-mutation flags.
- Evidence key `production_https_smoke_runner_after_latest_changes` remains `PENDING` until its unit test and the full validation queue are run.
- `production_https_smoke` remains `MISSING`; this runner does not by itself prove a deployed HTTPS smoke was performed.
- Real live trading remains `BLOCKED`; the runner does not submit, cancel, or mutate exchange/live-gate state.

## Production Alert Delivery/Audit Smoke Runner Boundary

- `scripts/run_production_alert_delivery_audit_smoke.py` can validate already-produced trader alert repository, notification delivery, durable audit, retention, access-control, scope-enforcement, secret-redaction, and no-live-mutation evidence.
- Evidence key `production_alert_delivery_audit_smoke_runner_after_latest_changes` remains `PENDING` until its unit test and the full validation queue are run.
- `alert_crud_delivery_audit_repositories_missing` remains `ACTIVE`; this runner does not create alerts, send notifications, call an exchange, submit/cancel orders, mutate leverage or margin, touch live-gate state, or close the production alert delivery/audit blocker by itself.
- Real live trading remains `BLOCKED`.

## Production Alert Delivery/Audit Artifact Metadata Boundary

- `/api/admin/trader-accounts` can expose sanitized `ALPHAFORGE_PRODUCTION_ALERT_DELIVERY_AUDIT_ARTIFACT` metadata under `alert_delivery_audit_readiness`.
- Evidence key `production_alert_delivery_audit_artifact_metadata_after_latest_changes` remains `PENDING` until backend tests and the full validation queue are run.
- This is partial admin-only metadata; it does not create alerts, send notifications, call exchanges, submit/cancel orders, mutate repository state, mutate leverage or margin, touch live-gate state, or close `alert_crud_delivery_audit_repositories_missing` by itself.
- Real live trading remains `BLOCKED`.

## SQLAlchemy Alert Repository Boundary

- `/api/v2/alerts` can use `ALPHAFORGE_ALERT_STORE_BACKEND=sqlalchemy` with `ALPHAFORGE_ALERT_DATABASE_URL` for durable trader-scoped paper alert records.
- Evidence key `sqlalchemy_alert_repository_after_latest_changes` remains `PENDING` until backend tests and the full validation queue are run.
- This adapter does not deliver notifications, call exchanges, submit/cancel orders, mutate leverage or margin, touch live-gate state, or close production alert delivery/audit blockers by itself.
- Real live trading remains `BLOCKED`.

## Production HTTPS Smoke Artifact Metadata Boundary

- Admin-only deployment readiness now can read `ALPHAFORGE_PRODUCTION_HTTPS_SMOKE_ARTIFACT` and expose sanitized artifact metadata.
- Evidence key `production_https_smoke_artifact_metadata_after_latest_changes` remains `PENDING` until backend tests and the full validation queue are run.
- This is partial artifact metadata only; `production_https_smoke` remains `MISSING` until deployed HTTPS smoke evidence is produced and accepted.
- Real live trading remains `BLOCKED`; no submit/cancel/leverage/margin/live-gate path is enabled.

## Production Trader Repository Smoke Artifact Boundary

- `scripts/run_production_trader_repository_smoke.py` can validate already-produced durable repository, writer, isolation, migration, and backup/restore evidence.
- Admin trader-account readiness can read `ALPHAFORGE_PRODUCTION_TRADER_REPOSITORY_SMOKE_ARTIFACT` and expose sanitized artifact metadata.
- Evidence keys `production_trader_repository_smoke_runner_after_latest_changes` and `production_trader_repository_smoke_artifact_metadata_after_latest_changes` remain `PENDING` until backend tests and the full validation queue are run.
- `production_trader_repositories_and_writers` remains `MISSING`; this metadata does not by itself close the production repository/writer blocker.
- Real live trading remains `BLOCKED`; no submit/cancel/leverage/margin/live-gate path is enabled.

## Durable Paper Audit Policy Smoke Runner Boundary

- `scripts/run_durable_paper_audit_policy_smoke.py` can validate already-produced durable paper audit policy evidence for production durable store, retention enforcement, writer hardening, audit verification, backup/restore, access control, and no-live-mutation flags.
- Evidence key `durable_paper_audit_policy_smoke_runner_after_latest_changes` remains `PENDING` until its unit test and the full validation queue are run.
- `durable_paper_audit_policy_missing` remains `ACTIVE`; this runner and artifact metadata do not by themselves prove a deployed durable audit policy is complete.
- Real live trading remains `BLOCKED`; no submit/cancel/leverage/margin/live-gate path is enabled.

## Production Paper Action Validation Smoke Runner Boundary

- `scripts/run_production_paper_action_validation_smoke.py` can validate already-produced paper-only submit, cancel, fill or fill-policy, trader-scope, paper-account-scope, durable repository, audit-linkage, and no-live-mutation evidence.
- Evidence key `production_paper_action_validation_smoke_runner_after_latest_changes` remains `PENDING` until its unit test and the full validation queue are run.
- `production_paper_submit_cancel_validation_missing` remains `ACTIVE`; this runner does not call paper endpoints, write repository state, submit/cancel real orders, mutate leverage or margin, touch live-gate state, or close the production paper submit/cancel/fill blocker by itself.
- Real live trading remains `BLOCKED`.

## Production Paper Action Validation Artifact Metadata Boundary

- `/api/admin/trader-accounts` can expose sanitized `ALPHAFORGE_PRODUCTION_PAPER_ACTION_VALIDATION_ARTIFACT` metadata under `paper_action_readiness`.
- Evidence key `production_paper_action_validation_artifact_metadata_after_latest_changes` remains `PENDING` until backend tests and the full validation queue are run.
- This is partial admin-only metadata; it does not call paper endpoints, submit/cancel real orders, mutate repository state, mutate leverage or margin, touch live-gate state, or close `production_paper_submit_cancel_validation_missing` by itself.
- Real live trading remains `BLOCKED`.

## 2026-06-14 Production Auth/Session Hardening Artifact Metadata Entry

| Area | Current status | Monitoring note |
|---|---|---|
| Admin credential readiness | IN PROGRESS | Admin-only `/api/admin/credential-status` can now report sanitized `ALPHAFORGE_AUTH_SESSION_HARDENING_ARTIFACT` metadata under `auth_session_hardening_readiness`. |
| `auth_session_hardening_artifact_metadata_after_latest_changes` | PENDING | Backend tests and full validation queue are pending. `production_auth_session_hardening_missing` remains ACTIVE until production auth/session hardening evidence is produced, validated, and accepted. Event: `auth_session_hardening_artifact_metadata_surfaced`. |
| Real live trading | BLOCKED | No live submit/cancel/leverage/margin/live-gate mutation was added or approved. |
Evidence note: auth/session hardening artifact metadata remains partial and pending current validation.

## 2026-06-14 Auth/Session Hardening Smoke Runner Entry

| Area | Current status | Monitoring note |
|---|---|---|
| Auth/session hardening smoke runner | IN PROGRESS | Added `scripts/run_auth_session_hardening_smoke.py` to validate already-produced auth/session/RBAC/no-live-mutation evidence into a sanitized artifact compatible with `ALPHAFORGE_AUTH_SESSION_HARDENING_ARTIFACT`. |
| `auth_session_hardening_smoke_runner_after_latest_changes` | PENDING | Unit coverage and full validation queue are pending. `production_auth_session_hardening_missing` remains ACTIVE until production auth/session evidence is produced, validated, and accepted. Event: `auth_session_hardening_smoke_runner_added`. |
| Real live trading | BLOCKED | No live submit/cancel/leverage/margin/live-gate mutation was added or approved. |

## 2026-06-14 Production Paper Fill-Writer Artifact Metadata Entry

| Area | Current status | Monitoring note |
|---|---|---|
| Paper execution policy | IN PROGRESS | `/api/v2/orders/preview` and paper action policy responses can now report sanitized `ALPHAFORGE_PRODUCTION_PAPER_FILL_WRITER_ARTIFACT` metadata while keeping production paper actions disabled. |
| `production_paper_fill_writer_artifact_metadata_after_latest_changes` | PENDING | Backend tests and full validation queue are pending. `production_paper_fill_writer_missing` remains ACTIVE until production fill-writer evidence is produced, validated, and accepted. Event: `production_paper_fill_writer_artifact_metadata_surfaced`. |
| Real live trading | BLOCKED | No live submit/cancel/leverage/margin/live-gate mutation was added or approved. |

## 2026-06-14 Durable Credential Vault Artifact Metadata Entry

| Area | Current status | Monitoring note |
|---|---|---|
| Credential vault readiness | IN PROGRESS | `credential_vault_readiness_status()` can now report sanitized `ALPHAFORGE_DURABLE_CREDENTIAL_VAULT_ARTIFACT` metadata for backend-only vault integration, rotation policy, redaction, access control, audit logging, and no-live-mutation evidence. |
| `durable_credential_vault_artifact_metadata_after_latest_changes` | PENDING | Backend tests and full validation queue are pending. `backend_only_binance_credential_vault_missing` remains ACTIVE until durable production vault evidence is produced, validated, and accepted. Event: `durable_credential_vault_artifact_metadata_surfaced`. |
| Real live trading | BLOCKED | No live submit/cancel/leverage/margin/live-gate mutation was added or approved. |

## 2026-06-14 Durable Credential Vault Smoke Runner Entry

| Area | Current status | Monitoring note |
|---|---|---|
| Durable credential vault smoke runner | IN PROGRESS | Added `scripts/run_durable_credential_vault_smoke.py` to validate already-produced backend-only credential vault, read-only scope, rotation, redaction, access-control, audit, and no-live-mutation evidence. |
| `durable_credential_vault_smoke_runner_after_latest_changes` | PENDING | Unit coverage and full validation queue are pending. `backend_only_binance_credential_vault_missing` remains ACTIVE until durable credential-vault evidence is produced, validated, and accepted. Event: `durable_credential_vault_smoke_runner_added`. |
| Real live trading | BLOCKED | No live submit/cancel/leverage/margin/live-gate mutation was added or approved. |

## 2026-06-14 Derivatives Realtime Source Smoke Runner Entry

| Area | Current status | Monitoring note |
|---|---|---|
| Derivatives realtime/source evidence | IN PROGRESS | Added `scripts/run_derivatives_realtime_source_smoke.py` to validate already-produced funding/OI/liquidation/long-short/basis/exchange-comparison freshness and no-fake-live evidence. |
| `derivatives_realtime_source_smoke_runner_after_latest_changes` | PENDING | Unit coverage and full validation queue are pending. `derivatives_realtime_sources_missing` remains ACTIVE until production derivatives source evidence is produced, validated, and accepted. Event: `derivatives_realtime_source_smoke_runner_added`. |
| Real live trading | BLOCKED | No live submit/cancel/leverage/margin/live-gate mutation was added or approved. |

## 2026-06-14 Phase 13 Visual Review Smoke Runner Entry

| Area | Current status | Monitoring note |
|---|---|---|
| Full Phase 13 visual review | IN PROGRESS | Added `scripts/run_phase13_visual_review_smoke.py` to validate already-produced route/viewport screenshot review metadata for visual, copy, responsive, data-honesty, forbidden-string, overflow, and no-live-mutation evidence. |
| `phase13_visual_review_smoke_runner_after_latest_changes` | PENDING | Unit coverage and full validation queue are pending. `full_phase13_visual_review_missing` remains ACTIVE until full screenshot review evidence is produced, validated, and accepted. Event: `phase13_visual_review_smoke_runner_added`. |
| Real live trading | BLOCKED | No live submit/cancel/leverage/margin/live-gate mutation was added or approved. |

## 2026-06-14 Alembic Auth Migration Approval Smoke Runner Entry

| Area | Current status | Monitoring note |
|---|---|---|
| Alembic auth/revocation/admin-audit migration approval | IN PROGRESS | Added `scripts/run_alembic_auth_migration_approval_smoke.py` to validate already-produced migration approval, rollback, retention, uniqueness, no-plaintext-password, no-DB-mutation, and no-live-mutation evidence. |
| `alembic_auth_migration_approval_smoke_runner_after_latest_changes` | PENDING | Unit coverage and full validation queue are pending. `alembic_auth_revocation_admin_audit_migration_approval_missing` remains ACTIVE until migration approval evidence is produced, validated, and accepted. Event: `alembic_auth_migration_approval_smoke_runner_added`. |
| Real live trading | BLOCKED | No DB migration was run and no live submit/cancel/leverage/margin/live-gate mutation was added or approved. |

## 2026-06-14 Production Stream Validation Artifact Metadata Entry

| Area | Current status | Monitoring note |
|---|---|---|
| Market stream source validation | IN PROGRESS | `/api/v2/market/{symbol}/stream-status` can now report sanitized `ALPHAFORGE_MARKET_STREAM_PRODUCTION_VALIDATION_ARTIFACT` metadata separately from stream alerting/dashboard metadata. |
| `production_stream_validation_artifact_metadata_after_latest_changes` | PENDING | Backend tests and full validation queue are pending. `production_stream_validation_alerting_missing` remains ACTIVE until stream source validation and alerting evidence are produced, validated, and accepted. Event: `production_stream_validation_artifact_metadata_surfaced`. |
| Real live trading | BLOCKED | No websocket behavior, exchange call, live submit/cancel/leverage/margin/live-gate mutation was added or approved. |

## 2026-06-14 Current Validation Evidence Smoke Runner Entry

| Area | Current status | Monitoring note |
|---|---|---|
| Current validation evidence | IN PROGRESS | Added `scripts/run_current_validation_evidence_smoke.py` to validate already-produced validation-result artifacts against every queued command without executing tests, builds, Playwright, backend services, database migrations, exchange calls, or live trading actions. |
| `current_validation_evidence_smoke_runner_after_latest_changes` | PENDING | Unit coverage and full validation queue are pending. `current_validation_rerun_pending` remains ACTIVE until current validation artifacts are produced, validated, and accepted. Event: `current_validation_evidence_smoke_runner_added`. |
| Real live trading | BLOCKED | No live submit/cancel/leverage/margin/live-gate mutation was added or approved. |
