# Auth/RBAC Audit

Generated: 2026-06-14

Status: IN PROGRESS. Backend-confirmed auth/RBAC now exists for the implemented auth and admin-user endpoints, but admin security is not marked PASS because production session hardening, durable user storage, broader admin endpoint coverage, deployment smoke, and full route review remain incomplete.

## Current Auth Mechanism

| Area | Current state | Status |
|---|---|---|
| Backend login | `POST /api/auth/login` verifies a stored bcrypt password hash and returns a signed bearer token plus HttpOnly session cookie; production env can force `Secure` cookies. | PARTIAL |
| Backend logout | `POST /api/auth/logout` clears the session cookie and revokes the current session token ID through the configured backend revocation store: local file in dev/test or SQLAlchemy when explicitly configured. | PARTIAL |
| Backend refresh | `POST /api/auth/refresh` requires an authenticated session and issues a new token. | PARTIAL |
| Current user | `GET /api/auth/me` returns a safe user payload without `password_hash`, with sanitized exchange account metadata, and with secret-free session/auth-store readiness. | PARTIAL |
| Frontend session | `AuthProvider` calls `/api/auth/me`; frontend role is derived from backend-confirmed user only. | PARTIAL |
| User storage | Minimal file-backed dev store plus explicit SQLAlchemy auth user-store and token-revocation adapter seams selected by `ALPHAFORGE_AUTH_STORE_BACKEND=sqlalchemy` / `ALPHAFORGE_AUTH_REVOCATION_STORE_BACKEND=sqlalchemy` and their database URLs; bcrypt password hashes, initial multi-trader metadata, enforced trader/paper-account scope for `trader` users, duplicate paper-account IDs, exchange-account metadata normalized to the owning user `trader_id` and `paper_account_id`, and production local auth-user/revocation-store access fail closed unless pytest-only overrides are active. | PARTIAL |

## Fake Role Paths

| Path | Finding | Result |
|---|---|---|
| Visible login role selector | Previous login surface had local-role wording and no real backend auth. | Removed from production login page. |
| Demo admin shortcut | No production demo-admin shortcut is exposed in the new login page. | Removed/blocked. |
| Hardcoded frontend admin token | No token is hardcoded in the frontend auth client. | Not present in edited path. |
| Frontend-only admin access | Admin shell no longer renders protected content until `/api/auth/me` confirms role. | Mitigated for `AdminShell`. |

## Query-Param Role Override Paths

| Path | Result |
|---|---|
| `?role=admin` | Stripped during default redirects and does not grant admin access. |
| `?role=superadmin` | Stripped during default redirects and does not grant superadmin access. |
| `?asRole=` | Stripped during default redirects. |
| `?admin=` | Stripped during default redirects. |

## Browser Storage Role Mutation Paths

| Path | Result |
|---|---|
| `sessionStorage` role mutation | Does not grant admin access in Playwright auth/RBAC tests. |
| `localStorage` role mutation | Does not grant admin access in Playwright auth/RBAC tests. |
| Legacy `auth:session` role cache | No longer controls `useRoles`; roles normalize from backend-confirmed `useAuth().user.role`. |

## Route Protection Status

| Route group | Protection | Status |
|---|---|---|
| Public routes | Render without login. | OK for public access. |
| Trader paper/read-only routes | Public read-only/paper surfaces remain available without backend trader role. | INTENTIONAL |
| `/admin/*` | Requires backend-confirmed `admin` or `superadmin` before admin content renders. | PARTIAL |
| System/admin route navigation | Hidden until backend-confirmed admin or superadmin role passes route RBAC. | PARTIAL |
| Superadmin routes | `AdminShell` requires backend-confirmed `superadmin`; backend test route `/api/admin/evidence` requires superadmin. | PARTIAL |

## Admin Routes

| Route | Required role |
|---|---|
| `/admin` | admin or superadmin |
| `/admin/system` | admin or superadmin |
| `/admin/ingestors` | admin or superadmin |
| `/admin/trainer` | admin or superadmin |
| `/admin/orchestrator` | admin or superadmin |
| `/admin/risk` | admin or superadmin |
| `/admin/traders` | admin or superadmin |
| `/admin/execution` | admin or superadmin |
| `/admin/exchanges` | admin or superadmin |
| `/admin/config` | admin or superadmin |
| `/admin/readiness` | admin or superadmin |
| `/admin/users` | admin or superadmin |
| `/admin/logs` | admin or superadmin |
| `/admin/reports` | admin or superadmin |

## Superadmin-Only Routes

| Route | Required role |
|---|---|
| `/admin/audit` | superadmin |
| `/admin/evidence` | superadmin |
| `/admin/scripts` | superadmin |
| `/admin/build-validation` | superadmin |
| `/admin/coverage` | superadmin |
| `/admin/migrations` | superadmin |
| `/admin/codex` | superadmin |
| `/admin/ai-tools` | superadmin |

## Backend Endpoints Added/Wired

| Endpoint | Protection | Status |
|---|---|---|
| `POST /api/auth/login` | public credential check | PARTIAL |
| `POST /api/auth/logout` | public cookie clear plus backend token-ID revocation | PARTIAL |
| `POST /api/auth/refresh` | `require_auth` | PARTIAL |
| `GET /api/auth/me` | optional bearer/cookie session | PARTIAL; safe exchange-account metadata is normalized to the owning user trader and paper-account scope and the response includes secret-free session security status, auth user-store readiness, refresh token rotation, password-change session revocation, and session-version invalidation |
| `GET /api/admin/users` | `require_admin` | PARTIAL |
| `POST /api/admin/users` | `require_admin` | PARTIAL |
| `PUT /api/admin/users/{id}` | `require_admin` | PARTIAL |
| `POST /api/admin/users` | `require_admin` | PARTIAL user-create workflow with secret-free audit event before mutation; local JSONL in dev/test or SQLAlchemy when explicitly configured; temporary password is accepted but never returned |
| `PUT /api/admin/users/{id}` | `require_admin` | PARTIAL user-update workflow with secret-free audit event before mutation; password reset is recorded as a boolean only |
| `DELETE /api/admin/users/{id}` | `require_admin` | PARTIAL user-delete workflow with secret-free audit event before mutation; durable deactivation-first policy still pending |
| `POST /api/admin/users/{id}/activation` | `require_admin` | PARTIAL activation/reset workflow with production step-up gate and secret-free audit event before mutation; temporary password is accepted but never returned |
| `DELETE /api/admin/users/{id}` | `require_admin` | PARTIAL |
| `GET /api/admin/trader-accounts` | `require_admin` | PARTIAL local paper repository route |
| `PUT /api/admin/trader-accounts/{paper_account_id}` | `require_admin` | PARTIAL local paper repository route |
| `GET /api/admin/credential-status` | `require_admin` | PARTIAL safe backend-only credential configured/pending status plus secret-free admin audit-store readiness; no raw values |
| `GET /api/admin/evidence` | `require_superadmin` | PARTIAL test/read-only route |
| `/api/v1/live-gate/*` | router-level `require_superadmin` | PROTECTED, live mutation remains blocked by existing gates |

## Backend Dependency Gaps

| Dependency area | Status |
|---|---|
| `bcrypt` | Added to project dependencies for password hashing. |
| `pytest` | Available through the existing venv after editable dev install; backend tests ran. |
| Production session secret | Must be configured outside source for production; default dev secret is not production-ready. |
| Secure session cookie | `ALPHAFORGE_ENV=production` or `ALPHAFORGE_AUTH_COOKIE_SECURE=true` sets the session cookie `Secure`; validation rerun pending. |
| Durable user database | PARTIAL adapter seam added; `SqlAlchemyUserStore` can persist auth users through an explicit SQLAlchemy URL and secret-free status reports whether it is configured. Production still requires database provisioning, migrations, backup/restore policy, and current validation before admin security can pass. |
| Durable token revocation database | PARTIAL adapter seam added; SQLAlchemy-backed token revocation can be selected through `ALPHAFORGE_AUTH_REVOCATION_STORE_BACKEND=sqlalchemy` and `ALPHAFORGE_AUTH_REVOCATION_DATABASE_URL`, with opt-in schema creation through `ALPHAFORGE_AUTH_REVOCATION_DB_AUTO_CREATE`. Production still requires migrations/provisioning, retention/rotation policy, and current validation. |
| Durable admin audit database | PARTIAL adapter seam added; SQLAlchemy-backed admin audit events can be selected through `ALPHAFORGE_ADMIN_AUDIT_STORE_BACKEND=sqlalchemy` and `ALPHAFORGE_ADMIN_AUDIT_DATABASE_URL`, with opt-in schema creation through `ALPHAFORGE_ADMIN_AUDIT_DB_AUTO_CREATE`. Local admin audit storage now fails closed in production unless the pytest-only override is active. Production still requires migrations/provisioning, retention policy, and current validation. |
| Alembic production migrations | BLOCKED; `backend/migrations/README.md` and `backend/migrations/env.py` state that version scripts are not checked in yet and require explicit human approval in milestone C proper. | BLOCKED |
| Production trader account database | Not complete; current paper account repository is local file-backed storage. |
| Admin step-up | PARTIAL; production activation/reset now requires an environment-backed TOTP step-up code, but full MFA enrollment, recovery, audit, and production validation remain required before live/admin launch claims. |

## Database/User Model Status

| Field | Present in minimal user store |
|---|---|
| `id` | yes |
| `trader_id` | yes |
| `username` | yes |
| `email` | yes |
| `password_hash` | yes, never returned by safe payload |
| `role` | yes |
| `paper_account_id` | yes |
| `exchange_accounts` | yes, sanitized safe metadata only; no API key/secret fields and no frontend-visible credential reference; stored metadata is normalized to the owning user `trader_id` and forced read-only/live-disabled |
| `watchlist` | yes |
| `alert_preferences` | yes |
| `is_active` | yes |
| `created_at` | yes |
| `updated_at` | yes |
| `last_login` | yes |

## Bootstrap

| Item | Status |
|---|---|
| Bootstrap env email | `ALPHAFORGE_BOOTSTRAP_ADMIN_EMAIL` |
| Bootstrap env password | `ALPHAFORGE_BOOTSTRAP_ADMIN_PASSWORD` |
| Auto-disable | Bootstrap is disabled after any admin or superadmin exists in the store. |
| Frontend exposure | No bootstrap control is exposed on the public frontend. |
| Production local store guard | File-backed user-store reads and writes fail closed in production with `production_auth_user_repository_required`; production must select the SQLAlchemy auth store or another durable repository. |

## Initial Trader Seed

| Item | Status |
|---|---|
| Username | `wajidali1984` |
| Email | `wajidali1984@hotmail.com` |
| Trader ID | `trader-wajidali1984` |
| Paper account ID | `paper-wajidali1984` |
| Binance account link | Safe read-only metadata reference `ALPHAFORGE_BINANCE_WAJIDALI1984_READONLY`; no key/secret is stored in source. |
| Binance metadata env overrides | `ALPHAFORGE_INITIAL_TRADER_BINANCE_ACCOUNT_ID`, `ALPHAFORGE_INITIAL_TRADER_BINANCE_LABEL`, `ALPHAFORGE_INITIAL_TRADER_BINANCE_ACCOUNT_TYPE`, `ALPHAFORGE_INITIAL_TRADER_BINANCE_CREDENTIAL_REF` |
| Activation | User is seeded inactive unless `ALPHAFORGE_INITIAL_TRADER_PASSWORD` is provided before first creation or an admin uses `POST /api/admin/users/{id}/activation` with a temporary password and reason. The temporary password is not returned. |
| Live trading | `live_trading_enabled=false`; this seed does not enable live submit/cancel/leverage/margin. |
| Account metadata scope | Exchange-account metadata is normalized to `trader-wajidali1984` and `paper-wajidali1984`; mismatched admin-created account metadata is re-scoped to the owning user and paper account. |
| Future trader rule | Backend user creation/update now requires `trader_id` and `paper_account_id` for `trader` users; duplicate local paper-account IDs are rejected; duplicate email updates are rejected case-insensitively; exchange-account metadata requires trader and paper-account scope. |

## Files Requiring Follow-Up

| File/area | Reason |
|---|---|
| Broader backend admin APIs | Apply `require_admin`/`require_superadmin` consistently beyond the endpoints touched in this pass. |
| Persistent user repository | SQLAlchemy adapter seam exists, but Alembic version-script authoring is still approval-gated by `backend/migrations/README.md`; production migrations, operational DB provisioning, backup/restore, tenant-isolation validation, and deployment smoke remain required. |
| Credential and admin-audit readiness | Safe backend-only configured/pending/binding-required credential status, credential vault readiness metadata, credential permission-probe artifact metadata, signed-read validation artifact metadata, secret-redaction smoke artifact metadata, safe secret-redaction smoke runner, admin audit-store readiness metadata with configurable retention-day metadata, production admin audit writes that fail closed when retention-day metadata is missing, configurable initial Binance credential reference, centralized backend-only environment binding, and optional backend-only local vault-file binding with read-only credential scope enforcement now exist; trader-side account linking is metadata-only and frontend-safe user payloads hide the backend credential reference. Still need durable vault integration, production permission probe, production secret-redaction smoke execution, signed read-only account adapter validation, production audit migrations, and admin audit retention enforcement/policy. |
| Session tokens | Signed tokens and cookies fail closed in production when required auth config is missing or invalid, and production user-provided passwords require length and complexity and include explicit issuer/audience, configurable expiration via `ALPHAFORGE_AUTH_SESSION_MINUTES`, token ID, active-user lookup, protected admin activation/reset with session invalidation coverage, secure cookie in production env, issued-at sanity checks, safe production-secret strength/rotation, issuer/audience, session TTL, password policy, cookie SameSite, revocation-store required/error fail-closed behavior, secret-free session security status with auth user-store and token-revocation store readiness, refresh token rotation, password-change session revocation, session-version invalidation, and configured logout revocation. Admin user create/update/delete and activation/reset now have secret-free audit events before mutation through local JSONL in dev/test or SQLAlchemy when explicitly configured. Still need durable session store, production revocation-store and audit-store migrations/provisioning/rotation/retention, environment-backed admin step-up partial evidence, MFA/step-up, and production HTTPS smoke. |
| Trader account repository | Replace local paper account repository with production DB repository/writers and audit trail. |
| Multi-trader account isolation | Exchange-account metadata is normalized and duplicate paper-account IDs are rejected in the local store, but production DB constraints and repository-level tenant isolation still need implementation. |
| Session/JWT production config | Safe session security status/refresh token rotation/password-change session revocation/session-version invalidation is exposed without secret values; add secret rotation, durable session/revocation storage, cookie security validation, and token TTL policy before production. |
| Admin page inventory | Complete visual/copy QA for every protected admin route after backend role coverage is expanded. |
| Deployment smoke | Verify deployed HTTPS origin, cookies, CORS, and auth failures in production-like environment. |

## Test Evidence

| Command | Result |
|---|---|
| `../.venv/bin/python -m pytest backend/tests/integration/api/test_auth_rbac_and_status.py backend/tests/integration/api/v2/test_market_contract_routes.py` | PASS previously; pending rerun after stream, trader account repository, credential-status/admin-audit-readiness, read-only credential scope enforcement, exchange-account read-only normalization, local auth user-store production access guard, SQLAlchemy auth revocation-store adapter, ProChart realtime merge, timestamp normalization, admin paper-account preservation, and docs guard changes |
| `npm run typecheck` | PASS previously; pending rerun after stream, trader account repository, credential-status, read-only credential scope enforcement, exchange-account read-only normalization, symbol-data fallback removal, ProChart realtime merge, derivative overlay null-clear, timestamp normalization, open-order explicit local repository action guard, admin paper-account preservation, and docs guard changes |
| `npm run build` | PASS previously with existing Vite chunk-size warning; pending rerun after stream, trader account repository, credential-status, read-only credential scope enforcement, exchange-account read-only normalization, symbol-data fallback removal, ProChart realtime merge, derivative overlay null-clear, timestamp normalization, open-order explicit local repository action guard, admin paper-account preservation, and docs guard changes |
| `npm run lint --if-present` | PASS/no lint script output previously; pending rerun after stream, trader account repository, credential-status, read-only credential scope enforcement, exchange-account read-only normalization, symbol-data fallback removal, ProChart realtime merge, derivative overlay null-clear, timestamp normalization, open-order explicit local repository action guard, admin paper-account preservation, and docs guard changes |
| `npx playwright test tests/e2e/auth_rbac_redesign.spec.ts tests/e2e/public_status_redesign.spec.ts tests/e2e/trader_nav_cleanliness.spec.ts tests/e2e/market_detail_redesign.spec.ts tests/e2e/trade_terminal_redesign.spec.ts tests/e2e/api_v2_contract_states.spec.ts tests/e2e/redesign_screenshot_overflow.spec.ts --project=chromium` | PASS previously; pending rerun after stream, trader account repository, credential-status, read-only credential scope enforcement, exchange-account read-only normalization, symbol-data fallback removal, ProChart realtime merge, derivative overlay null-clear, timestamp normalization, open-order explicit local repository action guard, admin paper-account preservation, and docs guard changes |

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


## Auth/session hardening artifact metadata note

- auth/session hardening artifact metadata is partial evidence only and is exposed only through admin-protected readiness metadata.
- Evidence key `auth_session_hardening_artifact_metadata_after_latest_changes` remains `PENDING` until backend tests and the full validation queue are run.
- `production_auth_session_hardening_missing` remains ACTIVE until production evidence is produced, validated, reviewed, and accepted.
- Real live trading remains BLOCKED; this note does not add live submit/cancel/leverage/margin/live-gate mutation.

## 2026-06-14 Durable Credential Vault Artifact Metadata Entry

| Area | Current status | Monitoring note |
|---|---|---|
| Credential vault readiness | IN PROGRESS | `credential_vault_readiness_status()` can now report sanitized `ALPHAFORGE_DURABLE_CREDENTIAL_VAULT_ARTIFACT` metadata for backend-only vault integration, rotation policy, redaction, access control, audit logging, and no-live-mutation evidence. |
| `durable_credential_vault_artifact_metadata_after_latest_changes` | PENDING | Backend tests and full validation queue are pending. `backend_only_binance_credential_vault_missing` remains ACTIVE until durable production vault evidence is produced, validated, and accepted. Event: `durable_credential_vault_artifact_metadata_surfaced`. |
| Real live trading | BLOCKED | No live submit/cancel/leverage/margin/live-gate mutation was added or approved. |

## 2026-06-14 Alembic Auth Migration Approval Smoke Runner Entry

| Area | Current status | Monitoring note |
|---|---|---|
| Alembic auth/revocation/admin-audit migration approval | IN PROGRESS | Added `scripts/run_alembic_auth_migration_approval_smoke.py` to validate already-produced migration approval, rollback, retention, uniqueness, no-plaintext-password, no-DB-mutation, and no-live-mutation evidence. |
| `alembic_auth_migration_approval_smoke_runner_after_latest_changes` | PENDING | Unit coverage and full validation queue are pending. `alembic_auth_revocation_admin_audit_migration_approval_missing` remains ACTIVE until migration approval evidence is produced, validated, and accepted. Event: `alembic_auth_migration_approval_smoke_runner_added`. |
| Real live trading | BLOCKED | No DB migration was run and no live submit/cancel/leverage/margin/live-gate mutation was added or approved. |

## 2026-06-14 - Safe user exchange-account scope serialization

`GET /api/auth/me` safe-user serialization now fails closed for exchange-account metadata. Returned exchange-account rows must match the authenticated user's trader scope and paper workspace and must be read-only/live-disabled. Stale or mismatched rows in local storage are withheld from trader clients.

## 2026-06-14 - Viewer exchange metadata role boundary

- Self-registration creates `viewer` accounts without `trader_id` or `paper_account_id`; admin approval is required before trader-scoped account metadata exists.
- `/api/accounts/me/exchange-accounts` requires complete trader/paper scope plus exact backend role `trader`; admin and superadmin users must use admin-management workflows rather than the trader self-service path.
- User repository validation rejects stored exchange-account metadata on non-trader-capable roles, even if an admin supplies trader/paper scope.
- Current evidence is implementation/test-contract only; backend pytest and full validation remain pending.

## 2026-06-14 continuation audit notes

- Local non-secret metadata currently includes active trader `wajidali1984` / `wajidali1984@hotmail.com` scoped to `trader-wajidali1984` and `paper-wajidali1984`.
- The local user metadata includes Binance USD-M read-only/live-disabled exchange account metadata `binance-wajidali1984` tied to the same trader and paper account scope.
- `/api/auth/me` continues to return only safe exchange-account metadata; backend credential references and raw credential values are not exposed to public/trader payloads.
- Trader-side exchange linking remains exact-role `trader` only and metadata-only; admin/superadmin account management remains separate.
- Trader-visible shell code now disables operator truth, paper runtime, readiness, system-observability, portfolio-state, and runtime-pages payload polling for non-admin users.
- Production DB migrations/provisioning, durable credential vault integration, production session/revocation hardening evidence, and current validation rerun remain blockers.

## 2026-06-14 Initial Trader Bootstrap Repair

- Existing `wajidali1984@hotmail.com` records are now repaired into the configured initial trader scope instead of only attaching partial trader IDs.
- The repair sets role `trader`, configured username, trader/paper account IDs, read-only Binance metadata, and default watchlist when absent.
- If `ALPHAFORGE_INITIAL_TRADER_PASSWORD` is supplied later, the existing initial trader record is activated and its session version is incremented; without that operator-provided password, inactive seeded records stay inactive.
- No exchange credential values are stored in frontend/docs/source, no live trading mutation path is added, and live trading remains disabled.
- Validation was not run after this patch; production durable auth/session and migration blockers remain open.

## 2026-06-14 Initial Trader Bootstrap Test Coverage

- Strengthened `backend/tests/integration/api/test_auth_rbac_and_status.py::test_initial_trader_seed_reconciles_existing_user_scope` so it starts from a stale viewer/inactive record and verifies role repair, username repair, watchlist seed, activation on operator password, session-version increment, read-only Binance scope, and login with the operator-provided initial password.
- The test was authored but not executed in this pass; `current_validation_rerun_pending` remains active.

## 2026-06-14 Initial Trader Scope Fail-Closed Guard

- The initial trader seed now requires both `ALPHAFORGE_INITIAL_TRADER_ID` and `ALPHAFORGE_INITIAL_TRADER_PAPER_ACCOUNT_ID`; missing paper-account scope prevents seed creation/repair.
- Existing-record reconciliation now runs the same trader-scope validation before writing repaired records.
- Added authored regression coverage for the missing-paper-account fail-closed case; not executed in this pass.

## 2026-06-14 Initial Trader Password Repair Idempotence

- The initial trader bootstrap now updates the existing seed password/session version only when the configured operator password does not already verify or the user is still inactive.
- This avoids repeated password hash rotation and session-version increments during normal `list_users` / `get_user` seed checks.
- Regression coverage is authored through the strengthened existing-user reconciliation test; execution remains pending.

## 2026-06-14 Initial Trader Exchange Metadata Idempotence

- Initial trader exchange-account reconciliation now preserves `updated_at` when the stored read-only Binance metadata already matches the configured seed.
- This avoids rewriting the local auth store during repeated user reads when no substantive exchange-account metadata changed.
- Validation remains pending.

## 2026-06-14 update - paper-action request scope hardening

- `/api/v2/orders/paper` now fails closed unless the request includes `trader_id` and `paper_account_id` matching the backend-authenticated user.
- `/api/v2/orders/preview` now reports request-scope echo fields and a `request_scope` risk check while remaining non-mutating.
- This hardens future multi-trader behavior for `wajidali1984` and later trader accounts without adding any live exchange route.
- Backend integration assertions were updated, but the validation queue remains pending until pytest/build/Playwright are explicitly rerun.

## Phase 15 multi-trader account-link hardening update - 2026-06-15

- `/api/accounts/me/exchange-accounts` now rejects extra request fields, so frontend clients cannot silently submit backend credential references or raw key fields into the metadata-only account-link contract.
- Exchange account labels and account-type metadata now reject private-looking terms such as API key, API secret, private key, credential ref, and access token.
- `/api/accounts/me/exchange-accounts/{account_id}` now requires backend-confirmed trader role, trader ID, paper account ID, read-only account metadata, and `live_trading_enabled=false` before removing metadata from the signed-in user's scope.
- The account-settings page mirrors this guard with a disabled submit state and friendly copy: `Account labels cannot contain private exchange values.`
- This closes a narrow self-service metadata hygiene gap only. Production credential vault integration, read-only permission probe evidence, durable audit policy, and validation rerun remain blockers.

## Phase 15 V2 trader-context scope hardening - 2026-06-15

- V2 API envelopes now build `trader_context.exchange_accounts` from the same scoped safe-user filter used by `/api/auth/me`.
- This prevents stale or manually corrupted exchange-account metadata from leaking through V2 trader-context payloads when an account belongs to another trader, lacks read-only posture, or has live trading enabled.
- Backend regression coverage was added to `backend/tests/integration/api/v2/test_market_contract_routes.py`; validation rerun remains pending.
