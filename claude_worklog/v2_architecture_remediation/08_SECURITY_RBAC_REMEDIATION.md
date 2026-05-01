```markdown
# 08 Security and RBAC Remediation

## Status
- Source blocker: actual Codex CLI architecture review, `claude_worklog/v2_architecture_codex_review/12_ACTUAL_CODEX_CLI_ARCHITECTURE_REVIEW_OUTPUT.md`, **Blocker 7** — *"Public-hosting security/RBAC scaffold: user-role mapping, sessions/tokens with revocation, permission matrix per route, MFA flow, server-side secrets / secret-provider boundary, IP controls."*
- Reconciled in `claude_worklog/v2_architecture_codex_review/13_ACTUAL_CODEX_RECONCILIATION.md`, consolidated blocker **#7**.
- Provisional blocker references: `claude_worklog/v2_architecture_codex_review/09_SECURITY_HOSTING_REVIEW.md` adversarial findings 1 (auth/session lifecycle missing — HIGH), 2 (RBAC granularity — HIGH), 3 (secrets provider boundary — MEDIUM), 4 (2FA / step-up auth not integration-scaffolded — MEDIUM), 5 (public-hosting verification contract — LOW).
- Architecture file under remediation: `claude_worklog/v2_architecture/15_PUBLIC_HOSTING_SECURITY_AND_RBAC_ARCHITECTURE.md` (current text is a 26-line stub that names a security baseline checklist, a five-layer ingress→audit stack, and a one-line "server-side secret handling only" policy — but defines no session object, no token rotation/revocation contract, no per-route permission matrix, no MFA/step-up auth flow, no secrets-provider boundary, no IP-control evidence schema, and no non-bypass invariants).
- Companion remediation files this document references:
  - `04_API_CONTRACT_REMEDIATION.md` — defines the universal request/response envelope (§1.2), the standard error envelope (§3), the RBAC scope tokens (§2.2), the live-block response posture (§7), and the `X-Approval-Token` / `X-Live-Confirm` headers used by step-up auth (§1.2). This document supplies the **session, identity, permission, MFA, and secret** layers that those routes assume.
  - `05_RISK_GATEWAY_REMEDIATION.md` — defines the `policy_bundles` whose L4/L5 promotion requires the step-up auth flow defined here (§5).
  - `07_AI_GOVERNANCE_REMEDIATION.md` — defines the `approval_chains` state machine; this document defines the *human identity, session, MFA assertion, and capability lookup* feeding `approval_decisions[].user_id|session_id|mfa_assertion_id` rows (`07 §1` GOV-INV-08, GOV-INV-15) and the `actor_type='human'` originator constraint at L5 (`07 §2.1`, GOV-INV-02).
- This document does **not** ship V2 code, does not write Redis, does not place or cancel exchange instructions, does not modify the legacy runtime tree, does not restart any service, does not provision identities, does not generate keys, and does not enable live trading. It is an architecture-layer deliverable producing schemas, state machines, route-permission matrices, MFA flows, secret-provider boundary contracts, and test-vector matrices that make the public-hosting security posture non-bypass enforceable in scaffold tests.

## Read/write boundary compliance
Writes only to `./claude_worklog/v2_architecture_remediation/`. Does not edit `./legacy_reference/**` or the sibling legacy bot tree. No `.env`, no secrets, no Redis writes, no service restarts, no exchange actions. All examples are schema, state-machine, header, and policy fragments — no executable runtime is created or modified. Live mutation routes referenced here remain blocked-by-default per `CLAUDE.md`; the contract encodes the block, it does not enable autonomous L4/L5 changes against live systems.

## Scope of remediation
This file produces, in order:

1. Non-bypass invariants the architecture must enforce for security/RBAC (the contract implementations are scored against).
2. Identity and account model — `users`, `roles`, `role_grants`, `service_identities`, `human_origin_attestations`.
3. Session and token lifecycle — issuance, refresh-rotation, idle/absolute expiry, binding, revocation, replay-protection, propagation.
4. RBAC route-permission matrix — scope tokens, role→scope grants, route→scope binding, denial precedence, decision determinism.
5. Step-up authentication — MFA factor enrollment, freshness windows, dangerous-action gates, anti-bypass.
6. Secrets provider boundary — provider envelope, access-scope leasing, rotation, decoupling from application memory, audit coupling.
7. Edge controls — IP allowlist, rate limits, public-hosting hardening evidence schema.
8. Cross-domain bindings — how this layer plugs into AI governance approvals (`07`), API envelope (`04`), Risk Gateway promotions (`05`), and the audit ledger.
9. Durable persistence tables — `users`, `roles`, `role_grants`, `sessions`, `refresh_tokens`, `revocation_lists`, `mfa_factors`, `mfa_assertions`, `secret_leases`, `ip_allowlists`, `rate_limit_buckets`, `auth_audit_events`.
10. Test-vector matrix that any scaffold implementation MUST pass before V2 build clears Blocker 7.
11. Audit / evidence-packet requirements.
12. Traceability table mapping every sub-claim of Codex Blocker 7 to the section that closes it.
13. Gate recommendation.

---

## 1. Non-bypass invariants (the contract security/RBAC is judged against)

These are the architectural invariants every security/RBAC implementation MUST satisfy. They are restated as machine-checkable statements so scaffold tests can assert them directly.

| ID | Invariant | Assertion form |
| --- | --- | --- |
| SEC-INV-01 | No mutating route may execute its handler without a satisfied `(authentication, rbac, idempotency, version, approval_or_step_up)` 5-tuple. The middleware chain MUST evaluate in that exact order; no handler may execute on partial satisfaction. | Static check: the only mutating-route entrypoint is the chain dispatcher; chain order is read from `auth_middleware_version` and matches the canonical sequence in §4.5. |
| SEC-INV-02 | Authentication failure is a hard reject with the standard error envelope (`04 §3.1`) and `error.class='auth'`; it MUST NOT fall through to "anonymous viewer" or any default identity. There is no anonymous mutating path. | Route-table assertion: every non-`read:public` route lists `auth_required=true`; static lint rejects route definitions missing the field. |
| SEC-INV-03 | Permission decisions are deterministic given `(session_token, route_id, payload_action_key, capability_matrix_version, role_grants_version)`. Re-running the resolver on the same inputs MUST produce the byte-identical decision (`allow|deny`) and the byte-identical `failing_check`. | Re-evaluation harness produces same decision, same `failing_check`, same `matched_scope_tokens[]`, same `denial_reason`. |
| SEC-INV-04 | A session is bound at issuance to `(user_id, ip_class, user_agent_fingerprint, mfa_baseline_factor_id|null, issued_ts_ms)`. Any request that arrives outside the bound `ip_class` is rejected unless the session has been explicitly re-bound via §3.6 (mobile roaming flow); rebinding is itself an audit event. | Service-layer guard at session-validate; mismatch produces `error.code='SESSION_BINDING_MISMATCH'`. |
| SEC-INV-05 | Refresh tokens are single-use (rotating). A refresh-token replay MUST (a) reject the replayed request, (b) immediately revoke the entire session family, (c) emit an `auth_audit_event` with `event_kind='refresh_replay_detected'`, and (d) propagate the revocation to all coordinators within `revocation_propagation_max_ms` (default 5000ms). | Replay test: issuing two consecutive `POST /api/v1/auth/refresh` with the same refresh JTI returns first-success, second-rejected, and the original session is invalidated for all subsequent calls. |
| SEC-INV-06 | Session/token revocation propagates to every read-and-mutate path. A revoked session, used after `revocation_ts_ms + revocation_propagation_max_ms`, MUST be rejected with `error.code='SESSION_REVOKED'`. A revoked session used *within* the propagation window that nevertheless succeeded MUST emit an `auth_audit_event` with `event_kind='revocation_race_loss'` AND, if the action was L2+, auto-emit a governance review. | Static cache discipline: every middleware reads from the revocation list with TTL ≤ `revocation_propagation_max_ms`; assertion test injects a revocation, advances clock by propagation max, asserts every coordinator rejects. |
| SEC-INV-07 | RBAC denials are the *first* failure surfaced when both auth and RBAC fail (auth check runs first, but if it passes and RBAC denies, the response is `error.class='forbidden'` not `error.class='auth'`). The error envelope MUST NOT leak whether a different role would have been allowed; the `details.required_scopes` list is populated only for `actor_type='human'` sessions. | Response-shaping test: machine-actor (`claude|codex|ollama|system`) denials return `details.required_scopes=null`; human denials return the list. |
| SEC-INV-08 | Step-up auth (MFA assertion) is required for every L3+ mutation per `07_AI_GOVERNANCE_REMEDIATION.md §2.1`. Freshness window is `≤300s` for L4/L5 and `≤600s` for L3. A stale or missing assertion is rejected at the route boundary with `error.code='STEP_UP_REQUIRED'` and the response MUST include `details.step_up_challenge_id` so the GUI can resume after factor verification. | Route guard test: synthesize an L4 mutation with `mfa_assertion.issued_ts_ms = now - 301_000` and assert `403 STEP_UP_REQUIRED`. |
| SEC-INV-09 | L5 routes additionally require: (a) two distinct `live_admin` MFA assertions both ≤300s old, (b) `X-Live-Confirm: I-UNDERSTAND` header, (c) `actor.actor_type='human'` for the originator and both approvers per `07 GOV-INV-15`, (d) a non-zero `human_origin_attestations` row whose `attestation_id` matches the `approval_request.human_origin_attestation.attestation_id`. | Route guard test asserts each of (a)–(d) independently; failing any one returns `error.code='LIVE_CONFIRM_INVALID'` with the specific failing predicate in `details.failing_check`. |
| SEC-INV-10 | Secrets are never accessible to the API process as plaintext globals. The application requests a *lease* for a named secret, the lease is bound to `(session_id, route_id, action_key, expires_ts_ms)` with `expires_ts_ms - issued_ts_ms ≤ 60_000`, and the lease auto-revokes after first use. The application memory MUST NOT retain the secret beyond the single operation; structured logging MUST NEVER emit the secret value. | Static check: the secrets-provider client exposes only `lease(secret_name, purpose) → SecretLeaseHandle`, no `read(secret_name)`. Memory-scrub test asserts the lease handle's `value_bytes` is zeroed after `.consume()`. |
| SEC-INV-11 | Secrets-provider operations participate in the audit chain: every `lease_request`, `lease_grant`, `lease_consume`, `lease_revoke`, `rotation_started`, `rotation_completed` is an `auth_audit_event` whose row is in the `audit_ledger` hash chain (per `07 GOV-INV-05`). The secret value is never recorded; only the `secret_name`, `version`, `purpose`, lease IDs, and timestamps. | Audit-replay test reconstructs every secret lifecycle from `auth_audit_events` alone. |
| SEC-INV-12 | IP allowlists apply to a sub-set of routes (default: `write:rbac`, `write:live_gate`, `write:kill_switch`, all L5 routes, `/api/v1/admin/**`, `/api/v1/secrets/**`). A request from a non-allowlisted IP is rejected with `error.code='IP_NOT_ALLOWLISTED'` *before* authentication runs (so a leaked token cannot be used from outside the allowlist). | Middleware-order test asserts IP guard runs before auth on the IP-restricted routes; injection of a valid token from an out-of-list IP returns 403 with the IP error code, not an auth error. |
| SEC-INV-13 | Rate limits apply per `(actor_id, route_class, ip_class)` triple, with separate buckets for read vs. mutate. Bucket exhaustion returns `error.code='RATE_LIMITED'` with `error.retry_after_ms` populated; rate-limit decisions are deterministic given the bucket state and clock. | Rate-limit replay test: same bucket state + same clock + same request produces same `Retry-After` value. |
| SEC-INV-14 | All security-relevant events (`session_issued`, `session_revoked`, `refresh_rotated`, `refresh_replay_detected`, `mfa_assertion_issued`, `mfa_factor_enrolled`, `mfa_factor_revoked`, `secret_leased`, `secret_consumed`, `ip_block`, `rate_limit_hit`, `step_up_required`, `step_up_satisfied`, `live_confirm_received`, `human_origin_attestation_recorded`) are immutable rows in `auth_audit_events`, and each row is also written into `audit_ledger` with the canonical hash chain (`07 GOV-INV-05`). | DB role grants exclude `UPDATE`/`DELETE` on `auth_audit_events`; nightly chain-walker validates per-row `prev_hash`/`row_hash` consistency. |
| SEC-INV-15 | Default state at coordinator boot: `accepting_auth=false` until (`role_grants_version`, `capability_matrix_version`, `secrets_provider_health=ok`, `revocation_list_warm=true`) are all satisfied. Until then every non-public route returns `503 SERVICE_NOT_READY` with `details.failing_check`. There is no "fail open" path. | Boot test: bring up the security coordinator with one of the four conditions failing; assert 503 on every protected route; flip the failing condition; assert routes become available. |
| SEC-INV-16 | Service identities (`actor_type` ∈ `{claude, codex, ollama, system}`) authenticate via mutually-authenticated client certificates or signed JWTs bound to a private key held by the secrets provider. They MUST NEVER use human session tokens. Cross-use is a hard reject and emits `auth_audit_event` `event_kind='actor_type_mismatch'`. | Service-layer guard: `service_identity.session_token_compatible=false`; injecting a service identity into a human session token validation returns `403 ACTOR_TYPE_MISMATCH`. |
| SEC-INV-17 | Anti-bypass under all execution modes (paper, replay, simulator, live): the auth/RBAC/step-up middleware chain MUST NOT branch on `mode`. Step-up freshness windows and approval *levels* may differ by mode (per `07 §2.1`), but presence-of-check is invariant. | Static check: middleware code path contains no `if mode == ...` branches that disable any of the five gate stages. |
| SEC-INV-18 | The security coordinator never mutates legacy systems, never edits old Redis keys, never restarts the legacy trainer. All session, MFA, secret, and audit state is in V2-namespaced storage only. | Static config: `REDIS_PREFIX='v2:'` at the security coordinator; CI grep rejects legacy key prefixes in coordinator source. |

---

## 2. Identity and account model

The architecture stub names roles but does not define users, role grants, service identities, or the human-origin attestation that anchors L5. This section enumerates them.

### 2.1 `users`

```sql
CREATE TABLE users (
  user_id            uuid PRIMARY KEY,
  username           text NOT NULL UNIQUE,
  email              text NOT NULL UNIQUE,
  display_name       text NOT NULL,
  account_state      text NOT NULL CHECK (account_state IN ('provisional','active','suspended','disabled','deleted')),
  password_hash_ref  text NULL,                       -- pointer to secrets-provider lease, never raw hash
  password_algo      text NOT NULL DEFAULT 'argon2id',
  password_updated_ts_ms bigint NOT NULL,
  failed_attempt_count int NOT NULL DEFAULT 0,
  lockout_until_ts_ms bigint NULL,
  created_ts_ms      bigint NOT NULL,
  created_by_user_id uuid NULL,                       -- null only for the genesis admin
  schema_version     text NOT NULL DEFAULT '1.0.0',
  CHECK (account_state <> 'active' OR password_hash_ref IS NOT NULL)
);
```

Rules:
- `password_hash_ref` is a *reference* to a value in the secrets provider, not the hash itself. The DB never stores authentication material directly (SEC-INV-10).
- `account_state='provisional'` is the boot state for users created by L3 `rbac.user.create`; transitions to `active` only after the user completes MFA enrollment (§5.1) and a `live_admin` confirms.
- `lockout_until_ts_ms` enforces hard lockout on `failed_attempt_count >= max_failed_attempts` (default 10 within 15 min); lockout extends on subsequent failures.

### 2.2 `roles`

```sql
CREATE TABLE roles (
  role_id            text PRIMARY KEY,
  role_name          text NOT NULL UNIQUE,
  description        text NOT NULL,
  is_human_only      boolean NOT NULL,                -- true for live_admin, security_admin
  is_grantable_at    text NOT NULL CHECK (is_grantable_at IN ('L2','L3','L4','L5')),
  capability_version text NOT NULL,
  schema_version     text NOT NULL DEFAULT '1.0.0'
);
```

Canonical seed rows:

| `role_id` | `is_human_only` | `is_grantable_at` | Notes |
| --- | --- | --- | --- |
| `viewer` | false | L3 | Per `04 §2.1`. |
| `operator` | false | L3 | Per `04 §2.1`. |
| `admin` | false | L3 | Per `04 §2.1`. |
| `security_admin` | true | L5 | Granting requires L5 (per `07 §2.2 rbac.role.grant_live_admin`-equivalent rule extended). |
| `live_admin` | true | L5 | Per `07 §2.2`; granting is L5. |
| `system` | false | L4 | Service-only. |

Granting `live_admin` or `security_admin` is itself an L5 action per `07 §2.2 rbac.role.grant_live_admin` (architectural extension: same level applies to `security_admin`).

### 2.3 `role_grants`

```sql
CREATE TABLE role_grants (
  grant_id            uuid PRIMARY KEY,
  user_id             uuid NOT NULL REFERENCES users(user_id),
  role_id             text NOT NULL REFERENCES roles(role_id),
  granted_by_user_id  uuid NOT NULL REFERENCES users(user_id),
  granted_via_approval_chain_id uuid NULL REFERENCES approval_chains(approval_chain_id),
  granted_ts_ms       bigint NOT NULL,
  expires_ts_ms       bigint NULL,
  revoked_ts_ms       bigint NULL,
  revoked_by_user_id  uuid NULL REFERENCES users(user_id),
  revocation_reason   text NULL,
  schema_version      text NOT NULL DEFAULT '1.0.0',
  UNIQUE (user_id, role_id, granted_ts_ms)
);
```

Rules:
- `live_admin` and `security_admin` grants MUST have a non-null `granted_via_approval_chain_id` whose `risk_level='L5'` (per SEC-INV-09 + `07 §2.2`).
- A grant is *active* when `revoked_ts_ms IS NULL AND (expires_ts_ms IS NULL OR expires_ts_ms > now)`.
- The active role set at request time is `{r | exists active grant_row for (user_id, r)}`. Permission resolution uses this set (§4).

### 2.4 `service_identities`

```sql
CREATE TABLE service_identities (
  identity_id         uuid PRIMARY KEY,
  actor_type          text NOT NULL CHECK (actor_type IN ('claude','codex','ollama','system')),
  display_name        text NOT NULL,
  public_key_pem_ref  text NOT NULL,                  -- pointer to secrets provider
  cert_fingerprint    text NOT NULL,
  not_before_ts_ms    bigint NOT NULL,
  not_after_ts_ms     bigint NOT NULL,
  account_state       text NOT NULL CHECK (account_state IN ('provisional','active','revoked','rotating')),
  approved_via_approval_chain_id uuid NOT NULL REFERENCES approval_chains(approval_chain_id),
  schema_version      text NOT NULL DEFAULT '1.0.0'
);
```

Rules:
- Service identities authenticate via mTLS or signed JWT with the corresponding private key held inside the secrets provider; they do not have passwords (SEC-INV-16).
- `claude|codex|ollama` identities can NEVER be granted `live_admin` or `security_admin` — enforced both by `roles.is_human_only=true` and by service-layer guard.

### 2.5 `human_origin_attestations`

Required by `07 GOV-INV-15` for L5 actions. Records the proof that a real human, present at a real terminal, with a fresh MFA factor, originated the L5 action.

```sql
CREATE TABLE human_origin_attestations (
  attestation_id       uuid PRIMARY KEY,
  user_id              uuid NOT NULL REFERENCES users(user_id),
  session_id           uuid NOT NULL REFERENCES sessions(session_id),
  mfa_assertion_id     uuid NOT NULL REFERENCES mfa_assertions(assertion_id),
  client_ip            inet NOT NULL,
  user_agent_fp        text NOT NULL,
  challenge_solved_id  uuid NOT NULL,                 -- reference to a server-issued nonce challenge
  issued_ts_ms         bigint NOT NULL,
  expires_ts_ms        bigint NOT NULL,               -- = issued_ts_ms + 300_000
  consumed_ts_ms       bigint NULL,
  consumed_by_approval_chain_id uuid NULL REFERENCES approval_chains(approval_chain_id),
  schema_version       text NOT NULL DEFAULT '1.0.0',
  CHECK (expires_ts_ms = issued_ts_ms + 300000)
);
```

Rules:
- An attestation is single-use against a single approval chain (`consumed_by_approval_chain_id`).
- Re-use is rejected with `error.code='HUMAN_ATTESTATION_CONSUMED'`.
- Expiry is hard 5 minutes; expired attestations cannot be reused (no extension path).

---

## 3. Session and token lifecycle

The architecture stub names "auth/session service" but defines no concrete session object, no rotation contract, and no replay protection. This section closes that gap.

### 3.1 `sessions`

```sql
CREATE TABLE sessions (
  session_id            uuid PRIMARY KEY,
  user_id               uuid NOT NULL REFERENCES users(user_id),
  family_id             uuid NOT NULL,                -- groups all refresh-rotated descendants
  parent_session_id     uuid NULL REFERENCES sessions(session_id),
  bound_ip_class        text NOT NULL,                -- /24 for IPv4, /64 for IPv6, or "any" for service
  bound_user_agent_fp   text NOT NULL,
  mfa_baseline_factor_id uuid NULL REFERENCES mfa_factors(factor_id),
  issued_ts_ms          bigint NOT NULL,
  idle_expires_ts_ms    bigint NOT NULL,              -- bumps on every authenticated read
  absolute_expires_ts_ms bigint NOT NULL,             -- never bumps; hard cutoff
  state                 text NOT NULL CHECK (state IN ('active','idle_expired','absolute_expired','revoked','superseded')),
  revoked_ts_ms         bigint NULL,
  revoked_reason        text NULL,
  schema_version        text NOT NULL DEFAULT '1.0.0'
);
```

Default windows (configurable via L3 `rbac.session_policy.update`):

| Role on session | Idle TTL | Absolute TTL | Refresh max chain length |
| --- | --- | --- | --- |
| `viewer`, `operator` | 30 min | 12 h | 24 |
| `admin` | 15 min | 8 h | 16 |
| `security_admin`, `live_admin` | 10 min | 4 h | 8 |
| `system` (service) | n/a (continuous) | 24 h, then forced rotation | 0 (mTLS only) |

### 3.2 Access token vs refresh token

Two distinct tokens, both signed by a private key held in the secrets provider:

| Token | Lifetime | Use | Single-use? | Replayable? |
| --- | --- | --- | --- | --- |
| `access_token` | 10 min | Borne in `Authorization: Bearer <jwt>` header on every API call | No | No (replay-detected by jti+nonce in revocation list during the 10-min window) |
| `refresh_token` | = `idle_expires_ts_ms - issued_ts_ms` | Borne ONLY on `POST /api/v1/auth/refresh` | **Yes** (rotation) | **No** (replay = family revocation per SEC-INV-05) |

Access token JWT claims (canonical):

```json
{
  "iss": "v2-auth",
  "sub": "user_id",
  "sid": "session_id",
  "fam": "family_id",
  "rls": ["operator","admin"],
  "iat": 1735689600,
  "exp": 1735690200,
  "jti": "uuid-v7",
  "ipc": "203.0.113.0/24",
  "uafp": "sha256:<hex>",
  "mfa_factor_id": "uuid-v7|null",
  "schema_version": "1.0.0"
}
```

Rules:
- `iss`, `sub`, `sid`, `fam`, `iat`, `exp`, `jti`, `ipc`, `uafp`, `schema_version` are all REQUIRED. Missing any field = `401 SESSION_INVALID`.
- `rls` is the *snapshot* of active role IDs at issuance — but the middleware MUST re-resolve current grants from `role_grants` if the snapshot is older than `role_grants_version_at_issue`'s newest revocation; this prevents using a stale token after a role grant is revoked.
- Service identity tokens additionally include `actor_type ∈ {claude,codex,ollama,system}` and OMIT `mfa_factor_id`.

### 3.3 Issuance flow (`POST /api/v1/auth/login`)

Request:
```json
{
  "schema_version": "1.0.0",
  "request_id": "uuid-v7",
  "username": "string",
  "password_proof": "argon2id-verifier-output",
  "client_ts_ms": 1735689600000,
  "client_ip_seen": "string",
  "user_agent": "string"
}
```

Server steps (deterministic order):
1. IP allowlist check for `/api/v1/auth/**` (per SEC-INV-12 — auth endpoints are not in the IP-allowlisted set by default, but a hosting profile may enable it).
2. Rate limit check against `(username, client_ip_class)` bucket (default 10 / 5 min, then 1 / 5 min after first failure).
3. Lookup `users.username`; if absent or `account_state ∉ {active}`, return generic `error.code='AUTH_FAILED'` (no user-existence leak) AND emit `auth_audit_event` `event_kind='login_attempt_unknown_user'`.
4. Verify `password_proof` against `password_hash_ref` (lease the verifier from secrets provider; consume; zero memory per SEC-INV-10).
5. On success, branch:
   - If user has any enrolled MFA factor → return `200` with body `{ "step_up_challenge_id": "...", "factors": [...] }`; **no session is issued yet**. Client must complete §5.2 step-up before tokens are minted.
   - If user has zero MFA factors AND role set ⊆ `{viewer}` → issue session with `mfa_baseline_factor_id=null` (read-only sessions may bypass MFA per hosting profile).
   - Otherwise → enrollment-required response, no session issued.
6. On MFA satisfied (§5.2 returns), mint `access_token` + `refresh_token`, write `sessions` row, write `auth_audit_event` `event_kind='session_issued'`, and return token pair.

### 3.4 Refresh-rotation flow (`POST /api/v1/auth/refresh`)

Request bears `Authorization: Bearer <refresh_token>`. Single-use semantics enforced.

Server steps:
1. Decode and verify signature.
2. Lookup `sessions.session_id = jwt.sid`.
3. If `sessions.state != 'active'` → reject; if the prior session was already superseded (a rotation has already consumed this refresh JTI) → **detect replay**:
   - Set `sessions.state='revoked'` for ALL rows with `family_id = jwt.fam`.
   - Emit `auth_audit_event` `event_kind='refresh_replay_detected'` with `details.victim_family_id=jwt.fam`.
   - Push the family into `revocation_lists` with `propagation_max_ms=5000`.
   - Return `401 SESSION_REVOKED` (SEC-INV-05).
4. If clean: mint new access+refresh pair, mark old session `superseded`, insert new `sessions` row with `parent_session_id=old`, `family_id=old.family_id`, `idle_expires_ts_ms=now+idle_ttl`, `absolute_expires_ts_ms=old.absolute_expires_ts_ms` (absolute window does NOT extend on rotation).
5. Reject if rotation chain length (count of `family_id`) exceeds `roles.max_refresh_chain_length` from §3.1; force re-login.
6. Emit `auth_audit_event` `event_kind='refresh_rotated'`.

### 3.5 Revocation flow

Routes:
- `POST /api/v1/auth/logout` — revokes the calling session only.
- `POST /api/v1/auth/sessions/{session_id}/revoke` — revokes a specific session (RBAC: own session OR `security_admin`).
- `POST /api/v1/auth/users/{user_id}/sessions/revoke_all` — revokes the user's entire family set (RBAC: `security_admin`; L3 mutation).
- `POST /api/v1/auth/role_grants/{grant_id}/revoke` — revokes a role grant; cascade-revokes all sessions that depend on it for any active role (i.e. sessions whose `rls` snapshot would change).

All revocations:
- Set `sessions.state='revoked'`, `revoked_ts_ms=now`, `revoked_reason=<enum>`.
- Insert into `revocation_lists` with `propagation_max_ms=5000` (SEC-INV-06).
- Emit `auth_audit_event` per revocation.

### 3.6 Session re-binding (mobile/PWA roaming)

When a mobile client roams between IP classes (e.g. cellular → WiFi), the session would fail SEC-INV-04. Rather than forcing re-login on every IP change, the architecture allows explicit re-binding:

- `POST /api/v1/auth/sessions/{session_id}/rebind`
- Request requires a fresh MFA assertion (≤300s, regardless of session role).
- Server records the IP-class change in `auth_audit_events` with `event_kind='session_rebound'`, updates `sessions.bound_ip_class`, and issues a new access token.
- Re-binding is rate-limited to `≤3 per hour per session`; exceeding triggers automatic session revocation with `revoked_reason='rebind_quota_exceeded'`.
- Re-binding is NOT permitted for `live_admin` or `security_admin` sessions — those must re-login.

---

## 4. RBAC route-permission matrix

The architecture stub names roles but provides no implementable mapping from route → required scopes → permitted role set. This section closes that gap.

### 4.1 Decision algorithm

A request to route `R` by user `U` with active roles `{r1, …, rn}` is allowed iff:

```
require_scopes := route_scope_table[R]
have_scopes    := union(role_scope_table[r_i] for r_i in active_roles(U, now))
decision       := allow if (require_scopes ⊆ have_scopes) else deny
```

The decision MUST be a pure function of (`active_roles`, `route_scope_table_version`, `role_scope_table_version`). Time enters only via `active_roles(U, now)`. Re-running with same inputs MUST produce same decision (SEC-INV-03).

### 4.2 `route_scope_table` (canonical mapping)

The route table consumes the scope tokens defined in `04_API_CONTRACT_REMEDIATION.md §2.2`. Each route declares its required scopes. A non-exhaustive but representative subset:

| Route | Method | `require_scopes` | Auth | Step-up level | IP allowlisted | L5 confirm |
| --- | --- | --- | --- | --- | --- | --- |
| `/api/v1/health` | GET | `read:public` | optional | n/a | no | no |
| `/api/v1/universe/{id}` | GET | `read:universe` | yes | n/a | no | no |
| `/api/v1/lineage/{signal_id}` | GET | `read:lineage` | yes | n/a | no | no |
| `/api/v1/audit/events` | GET | `read:audit` | yes | n/a | no | no |
| `/api/v1/paper/replay/start` | POST | `write:paper` | yes | L2 | no | no |
| `/api/v1/symbols/{id}/override` | POST | `write:override` | yes | L2 | no | no |
| `/api/v1/risk/policy_bundles/{id}/promote` (paper) | POST | `write:strategy` | yes | L4 | no | no |
| `/api/v1/risk/policy_bundles/{id}/promote` (live) | POST | `write:strategy`, `write:live_gate` | yes | L5 | yes | yes |
| `/api/v1/risk/kill_switch/trip` | POST | `write:kill_switch` | yes | L4 | yes | no |
| `/api/v1/risk/kill_switch/disarm` | POST | `write:kill_switch`, `write:live_gate` | yes | L5 | yes | yes |
| `/api/v1/connectors/{id}/live_enable` | POST | `write:live_gate` | yes | L5 | yes | yes |
| `/api/v1/exchange_accounts/{id}/api_key/rotate` | POST | `write:live_gate` | yes | L5 | yes | yes |
| `/api/v1/auth/login` | POST | (none) | no | n/a | optional | no |
| `/api/v1/auth/refresh` | POST | (refresh-token semantics) | refresh | n/a | no | no |
| `/api/v1/auth/sessions/{id}/revoke` | POST | `write:rbac` | yes | L3 | yes | no |
| `/api/v1/rbac/users` | POST | `write:rbac` | yes | L3 | yes | no |
| `/api/v1/rbac/role_grants` (live_admin/security_admin) | POST | `write:rbac`, `write:live_gate` | yes | L5 | yes | yes |
| `/api/v1/secrets/{name}/lease` | POST | scoped per `secret_name.purpose` | yes | per §6.4 | yes | per §6.4 |
| `/api/v1/secrets/{name}/rotate` | POST | `write:rbac`, `write:live_gate` | yes | L5 | yes | yes |
| `/api/v1/system/monitor/publish` | POST | `system:monitor` | mTLS service identity | n/a | yes (egress IP) | no |

Definitions:
- `Auth=optional` → route may be called anonymously; the response is sanitized of any tenant/identity-bearing fields.
- `Auth=refresh` → route validates a refresh token, not an access token (§3.4).
- `Step-up level` follows `07_AI_GOVERNANCE_REMEDIATION.md §2.1` and `07 §2.2`. `n/a` = no MFA assertion required.
- `IP allowlisted=yes` → the route is in the SEC-INV-12 default IP-restricted set.
- `L5 confirm=yes` → the route requires `X-Live-Confirm: I-UNDERSTAND` and dual MFA assertions (§5.4).

### 4.3 `role_scope_table` (canonical role → scope-token grants)

| Role | Granted scopes |
| --- | --- |
| `viewer` | `read:public, read:universe, read:lineage, read:trader_fleet, read:audit, read:config, read:monitor` |
| `operator` | viewer scopes + `write:paper, write:trader_fleet` (paper-only target enforced at action level) |
| `admin` | operator scopes + `write:override, write:config, write:strategy, write:approval` (within own authority level) |
| `security_admin` | viewer scopes + `write:rbac, write:approval` (within security domain), partial `read:secrets_metadata` (names + versions, never values) |
| `live_admin` | admin scopes + `write:kill_switch, write:live_gate, write:approval@L5` |
| `system` | `system:monitor, system:adapter` ONLY |

Rules:
- A user with both `admin` and `live_admin` has the union of scopes; the L5 step-up gate still applies per route.
- A user with `security_admin` is NOT permitted to grant L5 roles to themselves; self-grant of `live_admin` is rejected at the service layer with `error.code='SELF_GRANT_FORBIDDEN'`.
- `system` cannot be combined with any other role on the same identity.

### 4.4 Denial precedence and information disclosure

When a request fails multiple gates, the response code follows this precedence (highest blocks first):

1. `IP_NOT_ALLOWLISTED` (403) — runs *before* auth so a leaked token cannot be used out-of-perimeter.
2. `RATE_LIMITED` (429).
3. `SERVICE_NOT_READY` (503) — boot-incomplete state per SEC-INV-15.
4. `AUTH_FAILED` / `SESSION_INVALID` / `SESSION_EXPIRED` / `SESSION_REVOKED` / `SESSION_BINDING_MISMATCH` (401).
5. `ACTOR_TYPE_MISMATCH` (403).
6. `STEP_UP_REQUIRED` (403, with `details.step_up_challenge_id`).
7. `LIVE_CONFIRM_INVALID` (403, with `details.failing_check`).
8. `FORBIDDEN` (RBAC scope mismatch — 403). Per SEC-INV-07, `details.required_scopes` is populated only for human actor sessions.
9. `APPROVAL_REQUIRED` / `APPROVAL_STATE_INVALID` (409, per `04 §3` and `07 §3`).
10. `IDEMPOTENCY_REPLAY_MISMATCH` / `PRECONDITION_FAILED` (409 / 412).

This precedence is enforced by the middleware chain order in §4.5.

### 4.5 Canonical middleware chain

Mutating-route middleware runs in this exact order (SEC-INV-01):

1. `ip_allowlist_guard` — for routes in the IP-restricted set; rejects with `IP_NOT_ALLOWLISTED` before auth.
2. `rate_limit_guard` — per `(actor_id|client_ip, route_class)` bucket.
3. `boot_readiness_guard` — rejects with `SERVICE_NOT_READY` until SEC-INV-15 conditions met.
4. `authentication_guard` — verifies access token signature, expiry, binding.
5. `actor_type_guard` — rejects service tokens on human-only routes and vice versa.
6. `step_up_guard` — verifies fresh MFA assertion for L3+; consults `mfa_assertions`.
7. `live_confirm_guard` — for L5 routes only; verifies `X-Live-Confirm`, dual MFA assertions, human origin attestation.
8. `rbac_guard` — verifies `require_scopes ⊆ have_scopes` per §4.1.
9. `approval_token_guard` — verifies `X-Approval-Token` resolves to a satisfied chain (per `07 §3`).
10. `idempotency_guard` — per `04 §4`.
11. `concurrency_guard` (`If-Match`) — per `04 §5`.
12. `handler` — only runs if every prior gate passed.

The chain is declarative: each route's `route_scope_table` row names which stages apply (e.g. read routes skip 6/7/9/10/11).

---

## 5. Step-up authentication

The architecture stub says "2FA-ready" but defines no factor enrollment, no challenge flow, no freshness windows, and no anti-bypass. This section defines them.

### 5.1 `mfa_factors`

```sql
CREATE TABLE mfa_factors (
  factor_id          uuid PRIMARY KEY,
  user_id            uuid NOT NULL REFERENCES users(user_id),
  factor_type        text NOT NULL CHECK (factor_type IN ('totp','webauthn','recovery_code')),
  display_label      text NOT NULL,
  secret_ref         text NOT NULL,                   -- pointer to secrets provider; never raw seed
  enrolled_ts_ms     bigint NOT NULL,
  state              text NOT NULL CHECK (state IN ('pending_verification','active','revoked','suspended')),
  last_used_ts_ms    bigint NULL,
  use_count          int NOT NULL DEFAULT 0,
  enrolled_via_session_id uuid NOT NULL REFERENCES sessions(session_id),
  schema_version     text NOT NULL DEFAULT '1.0.0'
);
```

Rules:
- A user gains `account_state='active'` only after enrolling at least one TOTP or WebAuthn factor with `state='active'`.
- `live_admin` and `security_admin` MUST have at least one WebAuthn (hardware-backed) factor; TOTP-only is rejected at grant time.
- `recovery_code` factors are batch-issued (10 single-use codes); enrolling new recovery codes invalidates all prior codes; emits `auth_audit_event` `event_kind='recovery_codes_rotated'`.

### 5.2 `mfa_assertions`

```sql
CREATE TABLE mfa_assertions (
  assertion_id       uuid PRIMARY KEY,
  user_id            uuid NOT NULL REFERENCES users(user_id),
  session_id         uuid NOT NULL REFERENCES sessions(session_id),
  factor_id          uuid NOT NULL REFERENCES mfa_factors(factor_id),
  challenge_id       uuid NOT NULL,                   -- server-issued nonce, single-use
  issued_ts_ms       bigint NOT NULL,
  expires_ts_ms      bigint NOT NULL,                 -- = issued_ts_ms + factor_freshness_ms (per §5.3)
  consumed_ts_ms     bigint NULL,
  consumed_by_request_id uuid NULL,                   -- the API request_id that satisfied step-up
  consumed_for_action_key text NULL,                  -- the action_key (per 07 §2.2) it was bound to
  schema_version     text NOT NULL DEFAULT '1.0.0'
);
```

Rules:
- An assertion is single-use: `consumed_ts_ms` and `consumed_by_request_id` set on first satisfying use; subsequent attempts return `error.code='MFA_ASSERTION_CONSUMED'`.
- Expired assertions (`now > expires_ts_ms`) are not consumable.
- An assertion is bound at consume-time to a single `action_key`; a fresh assertion CANNOT satisfy step-up for a different action.
- L4/L5 routes additionally enforce that the assertion's `factor_id` is one of the user's `webauthn` factors (TOTP cannot satisfy L4/L5 step-up).

### 5.3 Freshness windows

| Action level | Freshness | Permitted factor types | Notes |
| --- | --- | --- | --- |
| L0/L1/L2 | n/a | n/a | No step-up required. |
| L3 | ≤600s | totp, webauthn | Default for non-live operational mutations. |
| L4 | ≤300s | webauthn | TOTP rejected. |
| L5 | ≤300s, dual | webauthn (both approvers) | Per SEC-INV-09. |

### 5.4 L5 dual-assertion flow

L5 routes require two independent MFA assertions, one per approver, both fresh. The flow:

1. Originator (`actor_type='human'`) creates the `approval_request` per `07 §3.1`. Originator's MFA assertion is stored in `human_origin_attestations` (§2.5) and linked via `approval_request.human_origin_attestation.attestation_id`.
2. First approver (`live_admin`, distinct from originator) issues `mfa_assertion` and submits `approval_decision` per `07 §3.2`. Decision row stores `mfa_assertion_id`.
3. Second approver (`live_admin`, distinct from originator AND from first approver) repeats step 2.
4. Apply request bears:
   - `Authorization: Bearer <originator_access_token>`
   - `X-Approval-Token: <approval_chain_id>` (the chain that has both decisions in `state='satisfied'`)
   - `X-Live-Confirm: I-UNDERSTAND`
   - `X-Origin-Attestation: <attestation_id>`
   - All headers per `04 §1.2` standard request envelope
5. `live_confirm_guard` (§4.5 stage 7) verifies:
   - `X-Live-Confirm` exact-match `I-UNDERSTAND`,
   - originator's attestation row exists, unconsumed, fresh,
   - approval chain has ≥2 decisions, both with `actor_type='human'`, both with `mfa_assertions.expires_ts_ms > now`,
   - the two approver `user_id`s are distinct from each other AND from the originator,
   - the two MFA factors used are both WebAuthn.
6. On any failure, returns `403 LIVE_CONFIRM_INVALID` with `details.failing_check ∈ {'header_missing','header_value','attestation_consumed','attestation_expired','approver_count','approver_distinct','approver_actor_type','assertion_expired','factor_not_webauthn'}`.
7. On success, the attestation and both assertions are atomically marked `consumed`; the apply proceeds; `auth_audit_event` `event_kind='live_confirm_received'` is emitted.

### 5.5 Anti-bypass invariants

- A step-up assertion cannot be re-used for a different `action_key` (§5.2 rule 3).
- A step-up assertion cannot be transferred between sessions (`assertion.session_id` is bound).
- A step-up assertion cannot be transferred between users (`assertion.user_id` is bound).
- The challenge-issuance route (`POST /api/v1/auth/step_up/challenge`) is rate-limited to `≤5 / min / session`; exceeding triggers `auth_audit_event` `event_kind='step_up_challenge_flood'`.
- Failed step-up verifications increment `failed_attempt_count`; ≥5 within 5 min suspends the factor (`mfa_factors.state='suspended'`); recovery requires `security_admin` action.

---

## 6. Secrets provider boundary

The architecture stub says "server-side secret handling only" but defines no provider type, no lease semantics, no rotation contract, and no audit coupling. This section closes that gap.

### 6.1 Provider capabilities (architectural contract, provider-agnostic)

The secrets provider MUST satisfy:

| Capability | Requirement |
| --- | --- |
| Storage | Encryption at rest with provider-managed KMS; cipher MUST be authenticated (e.g. AES-256-GCM); cipher version is part of `secret_versions`. |
| Access | Lease-based only; no "read by name" raw-value API exposed to the application. |
| Audit | Every operation produces an event the application can ingest into `audit_ledger`. |
| Rotation | Atomic version rollover; old versions retained for `rollback_retention_window` (default 14 days). |
| Quorum | `live_api_key` rotations require dual-approval per `07 §2.2 exchange_account.api_key.rotate` (L5). |
| Revocation | Immediate; propagation MUST satisfy SEC-INV-06 (≤5000ms). |
| Sealing | Provider boots `sealed`; unsealing requires Shamir-share-style quorum or KMS attestation (provider-internal); unsealing is not an application-level operation. |

### 6.2 Provider type allowed (architecture-level)

Three provider classes are supported behind a single boundary interface. The selection is per-deployment-profile and is itself an L5 change.

| Provider class | Use | Notes |
| --- | --- | --- |
| `local-keyring` | Single-host development / paper-only | Filesystem-backed, OS-keyring-encrypted; never used in live profile. |
| `hashicorp-vault` | Self-hosted production | Application authenticates via AppRole + bound IP/cert. |
| `cloud-kms-backed` | Hosted cloud production | Application authenticates via instance identity / workload identity; KMS owned by deployment account. |

The application code path is identical across all three; the boundary is the `SecretsProvider` interface (§6.3).

### 6.3 Boundary interface (architectural shape)

The application MUST interact with secrets exclusively through this interface. No other entry point is permitted; static lint enforces that no other module imports a provider-specific SDK directly.

```
interface SecretsProvider {
  // Issue a single-use lease for a named secret.
  // The handle's underlying value is materialized only when .consume() is called,
  // and is zeroed immediately after the handler returns.
  lease(secret_name, version_pin, purpose, ttl_ms <= 60_000) -> SecretLeaseHandle

  // Initiate a rotation; returns a rotation_id; rotation completion is async
  // and signaled via auth_audit_event 'rotation_completed'.
  rotate(secret_name, approval_chain_id) -> rotation_id

  // List metadata only — name, current_version, last_rotation_ts_ms.
  // NEVER returns the value. Available to security_admin only.
  list_metadata() -> [SecretMetadata]

  // Probe; returns ok / sealed / unhealthy.
  health() -> HealthStatus
}

interface SecretLeaseHandle {
  consume(operation: () -> T) -> T          // executes operation with the value materialized; zeros after
  metadata() -> { name, version, expires_ts_ms, lease_id }
  // No raw-value accessor.
}
```

Rules:
- `consume` is the ONLY way to access the value. The closure receives the value bytes and returns a result; the bytes are zeroed before `consume` returns. No caller may capture the value bytes outside the closure.
- `lease.ttl_ms ≤ 60_000` is hard-capped (SEC-INV-10).
- `version_pin=null` means "current version"; pinning enables deterministic rollback during rotation.
- `purpose` is one of an enumerated set (`db_password|jwt_signing|exchange_api|password_hash_verify|mfa_seed|mtls_private_key|...`); leases for purposes outside the permitted set for the calling route's `action_key` are rejected.

### 6.4 Lease scope and route binding

Every secret has a `secret_policy` row that names which `(action_key, route_id)` pairs may lease it and at which step-up level.

```sql
CREATE TABLE secret_policies (
  secret_name        text NOT NULL,
  action_key         text NOT NULL,                   -- per 07 §2.2
  route_id           text NOT NULL,
  required_step_up_level text NOT NULL CHECK (required_step_up_level IN ('L2','L3','L4','L5')),
  required_role      text NOT NULL,
  ip_allowlisted     boolean NOT NULL,
  schema_version     text NOT NULL DEFAULT '1.0.0',
  PRIMARY KEY (secret_name, action_key, route_id)
);
```

A lease request whose `(secret_name, action_key, route_id)` is not in `secret_policies` is rejected with `error.code='SECRET_POLICY_NOT_FOUND'` — there is no implicit-permit fallback.

### 6.5 `secret_leases`

```sql
CREATE TABLE secret_leases (
  lease_id           uuid PRIMARY KEY,
  secret_name        text NOT NULL,
  version            int NOT NULL,
  session_id         uuid NOT NULL REFERENCES sessions(session_id),
  route_id           text NOT NULL,
  action_key         text NOT NULL,
  request_id         uuid NOT NULL,
  purpose            text NOT NULL,
  issued_ts_ms       bigint NOT NULL,
  expires_ts_ms      bigint NOT NULL CHECK (expires_ts_ms - issued_ts_ms <= 60000),
  consumed_ts_ms     bigint NULL,
  revoked_ts_ms      bigint NULL,
  schema_version     text NOT NULL DEFAULT '1.0.0'
);
```

Rules:
- A lease is consumed at most once. After `consumed_ts_ms` is set, further uses are rejected.
- A lease can be revoked (e.g. on session revocation); `revoked_ts_ms` is set; subsequent consume attempts are rejected.
- The lease value bytes are NEVER stored in this table.

### 6.6 Rotation flow

`POST /api/v1/secrets/{name}/rotate` is L5 (per §4.2). On success:
1. Provider creates `version+1` with new value; old version retained for `rollback_retention_window`.
2. Application emits `auth_audit_event` `event_kind='rotation_started'` with `secret_name, old_version, new_version, approval_chain_id`.
3. Provider asynchronously promotes `version+1` to `current` once dependent services have re-leased (max wait window per secret class; default 5 min).
4. On promotion completion, `auth_audit_event` `event_kind='rotation_completed'`.
5. On failure or timeout, automatic rollback: `current` reverts to `version`; `event_kind='rotation_rolled_back'` with failure detail.

### 6.7 Forbidden patterns (CI-enforced)

- `process.env.<SECRET_NAME>` for any name in `secret_policies` is forbidden — secrets MUST come through the boundary.
- Plain-text secrets in any file under `./v2/**` is forbidden (lint rejects on commit).
- Logging the bytes of a `SecretLeaseHandle` is forbidden; the handle's `__repr__` returns only `{name, version, lease_id}`.
- Caching the materialized value beyond a `consume()` closure is forbidden (static lint flags any closure-escape pattern).

---

## 7. Edge controls

### 7.1 IP allowlist

```sql
CREATE TABLE ip_allowlists (
  list_id            uuid PRIMARY KEY,
  scope              text NOT NULL CHECK (scope IN ('admin','live_gate','secrets','rbac','full_global')),
  cidr               cidr NOT NULL,
  description        text NOT NULL,
  added_via_approval_chain_id uuid NOT NULL REFERENCES approval_chains(approval_chain_id),
  added_ts_ms        bigint NOT NULL,
  removed_ts_ms      bigint NULL,
  removed_via_approval_chain_id uuid NULL REFERENCES approval_chains(approval_chain_id),
  schema_version     text NOT NULL DEFAULT '1.0.0'
);
```

Rules:
- Adding/removing an entry in `ip_allowlists` is itself an L4 mutation (`rbac.ip_allowlist.update`); adding to `live_gate` or `secrets` scope is L5.
- The `ip_allowlist_guard` middleware reads the active set with TTL ≤2s; a removed entry stops permitting traffic within ≤2s.
- A request from an IP not in any list relevant to the route's IP-allowlisted set is rejected with `IP_NOT_ALLOWLISTED` *before* auth (SEC-INV-12).

### 7.2 Rate limits

```sql
CREATE TABLE rate_limit_buckets (
  bucket_key         text PRIMARY KEY,                -- canonical "{actor_id|ip_class}:{route_class}:{verb}"
  capacity           int NOT NULL,
  refill_per_minute  int NOT NULL,
  current_tokens     int NOT NULL,
  last_refill_ts_ms  bigint NOT NULL,
  schema_version     text NOT NULL DEFAULT '1.0.0'
);
```

Default policy (configurable via L3 `rbac.rate_limit_policy.update`):

| Bucket key | Capacity | Refill |
| --- | --- | --- |
| `human:{ip_class}:read` | 600 | 600 / min |
| `human:{ip_class}:mutate` | 60 | 60 / min |
| `human:{ip_class}:auth_login` | 10 | 10 / 5 min |
| `human:{user_id}:step_up_challenge` | 5 | 5 / min |
| `service:{identity_id}:any` | per service contract | per service contract |

A `429 RATE_LIMITED` response includes `error.retry_after_ms` derived from the bucket's refill schedule. Bucket states are deterministic given clock + history (SEC-INV-13).

### 7.3 Public-hosting hardening evidence schema

The provisional review (`09_SECURITY_HOSTING_REVIEW.md` finding 5) flagged that hardening requirements lack a verification contract. The architecture closes this with a standardized evidence packet emitted on each deployment and re-emitted hourly:

```json
{
  "schema_version": "1.0.0",
  "evidence_packet_kind": "public_hosting_hardening",
  "evidence_packet_id": "uuid-v7",
  "captured_ts_ms": 1735689600000,
  "deployment_profile": "local|self-hosted|cloud",
  "checks": [
    {"check_id": "tls.min_version", "expected": "TLS1.3", "observed": "TLS1.3", "ok": true},
    {"check_id": "tls.certificate_valid_until_ts_ms", "expected_min": 1735776000000, "observed": 1738281600000, "ok": true},
    {"check_id": "reverse_proxy.installed", "expected": true, "observed": true, "ok": true},
    {"check_id": "reverse_proxy.csp_header", "expected": "default-src 'self'; ...", "observed": "...", "ok": true},
    {"check_id": "rate_limit.policy_loaded", "expected": true, "observed": true, "ok": true},
    {"check_id": "ip_allowlist.policy_loaded", "expected": true, "observed": true, "ok": true},
    {"check_id": "secrets_provider.health", "expected": "ok", "observed": "ok", "ok": true},
    {"check_id": "auth_audit_chain.head_verifies", "expected": true, "observed": true, "ok": true},
    {"check_id": "revocation_list.warm", "expected": true, "observed": true, "ok": true},
    {"check_id": "session_policy.loaded", "expected": true, "observed": true, "ok": true},
    {"check_id": "mfa_policy.loaded", "expected": true, "observed": true, "ok": true},
    {"check_id": "live_block.posture", "expected": "blocked_by_default", "observed": "blocked_by_default", "ok": true}
  ],
  "all_ok": true,
  "first_failing_check_id": null
}
```

If `all_ok=false`, the security coordinator transitions to `accepting_auth=false` for the affected scope until the failing check returns to `ok`; this is an automatic, defense-in-depth posture — no human override path exists.

---

## 8. Cross-domain bindings

This layer is the substrate underneath every other governance contract. The bindings are:

| Binding | Where | What this layer supplies |
| --- | --- | --- |
| `04_API_CONTRACT_REMEDIATION.md` standard request envelope (`§1.2`) | every mutating route | The `Authorization`, `X-Approval-Token`, `X-Live-Confirm`, `X-Idempotency-Key`, `If-Match` headers that this layer validates in middleware. |
| `04 §3` standard error envelope | every non-2xx | The `auth`, `forbidden`, `precondition_failed`, `live_confirm_invalid`, `step_up_required`, `ip_not_allowlisted`, `rate_limited`, `service_not_ready` error classes are emitted from this layer's middleware stages. |
| `04 §7` live-block posture | every L5 route | This layer's `live_confirm_guard` is the route-level enforcement that the "default LIVE TRADING: BLOCKED" posture cannot be bypassed by a leaked token alone. |
| `05_RISK_GATEWAY_REMEDIATION.md` policy-bundle promotions (paper L4 / live L5) | `POST /api/v1/risk/policy_bundles/{id}/promote` | The MFA assertion(s), human-origin attestation, and IP allowlist check that gate L4/L5 promotions. |
| `06_HOT_RELOAD_REMEDIATION.md` `live_affecting=true` rollouts | `POST /api/v1/hot_reload/...` | The L4/L5 step-up flow per HR INV-08. |
| `07_AI_GOVERNANCE_REMEDIATION.md` `approval_decisions` (`07 §3.2`) | every L2+ approval submission | The `user_id`, `session_id`, `mfa_assertion_id`, `client_ip` fields that this layer materializes and stamps into the `approval_decisions` row (`07 GOV-INV-08`, `GOV-INV-15`). |
| `07 §2.1` originator constraints (`actor_type='human'` for L5) | every L5 origination | This layer's `actor_type_guard` (§4.5 stage 5) is the architectural enforcement of `07 GOV-INV-02` and `07 GOV-INV-15`. |
| Audit ledger (`07 §9`) | every security event | This layer's `auth_audit_events` rows participate in the audit hash chain via `07 GOV-INV-05` (`prev_hash`/`row_hash`), `GOV-INV-06` (sequence monotonicity), `GOV-INV-10` (lineage tuple). |

The boundary is asymmetric: this layer publishes events into the audit chain but never *reads* governance decisions to decide auth. The five-stage middleware chain (§4.5) is the only place where governance intent (approval token) and security state (session, MFA, scopes) meet.

---

## 9. Durable persistence tables (consolidated)

The full set of tables this remediation introduces:

| Table | Purpose | Append-only | Audit-chained |
| --- | --- | --- | --- |
| `users` | Account identity | No (mutable account_state, password_updated_ts_ms) | Yes (every state change is an event) |
| `roles` | Role catalog (seed-managed) | No (capability_version may bump) | Yes |
| `role_grants` | User→role mapping over time | No (revoked_ts_ms set) | Yes |
| `service_identities` | Non-human actor identities | No | Yes |
| `human_origin_attestations` | L5 originator proof | Append-only after consume | Yes |
| `sessions` | Session state | No (state transitions) | Yes (every transition) |
| `refresh_tokens` (logical view of sessions w/ refresh chain) | Refresh single-use tracking | Append-only | Yes |
| `revocation_lists` | TTL-bounded revoke propagation | Append-only | Yes |
| `mfa_factors` | Enrolled second factors | No (state transitions) | Yes |
| `mfa_assertions` | Single-use step-up tokens | Append-only after consume | Yes |
| `secret_policies` | Allowed secret leases by route | No (versioned) | Yes |
| `secret_leases` | Lease ledger | Append-only after consume/revoke | Yes |
| `ip_allowlists` | IP-restricted CIDR ranges | No (removed_ts_ms set) | Yes |
| `rate_limit_buckets` | Token-bucket state | Mutable | No (state-only; events on hit/exhaustion are audited) |
| `auth_audit_events` | Security audit log | **Append-only (no UPDATE/DELETE grants)** | **Yes** (rows in `audit_ledger`) |

`auth_audit_events` row shape:

```sql
CREATE TABLE auth_audit_events (
  audit_event_id     uuid PRIMARY KEY,
  sequence_id        bigint NOT NULL,                 -- assigned by audit_ledger writer; gapless
  event_kind         text NOT NULL,                   -- enumerated; see SEC-INV-14 list
  actor_user_id      uuid NULL REFERENCES users(user_id),
  actor_service_id   uuid NULL REFERENCES service_identities(identity_id),
  actor_type         text NOT NULL,
  session_id         uuid NULL REFERENCES sessions(session_id),
  subject_type       text NOT NULL,
  subject_id         uuid NULL,
  approval_chain_id  uuid NULL REFERENCES approval_chains(approval_chain_id),
  client_ip          inet NULL,
  user_agent_fp      text NULL,
  details_json       jsonb NOT NULL,
  prev_hash          text NOT NULL,
  row_hash           text NOT NULL,                   -- sha256(prev_hash || canonicalized row excluding row_hash)
  capability_matrix_version text NOT NULL,
  role_grants_version text NOT NULL,
  audit_chain_version text NOT NULL,
  ts_ms              bigint NOT NULL,
  schema_version     text NOT NULL DEFAULT '1.0.0',
  CHECK ((actor_user_id IS NOT NULL) OR (actor_service_id IS NOT NULL))
);
```

DB role grants (deployment-time):
- Application role: `INSERT, SELECT` on `auth_audit_events`. **No `UPDATE`, no `DELETE`.**
- Read-only audit role: `SELECT` only.
- Migration role: separate from application; rotates per release.

---

## 10. Test-vector matrix

Any scaffold implementation MUST pass every row of this matrix before V2 build clears Blocker 7. Each row names the invariant it asserts and the failing-check expected on negative paths.

| Test ID | Path | Inputs | Expected outcome | Asserts |
| --- | --- | --- | --- | --- |
| SEC-T-001 | `POST /api/v1/auth/login` | wrong password | `401 AUTH_FAILED` + `auth_audit_event` `login_failed` | SEC-INV-02, §3.3 |
| SEC-T-002 | `POST /api/v1/auth/login` | correct password, MFA enrolled | `200` with `step_up_challenge_id`; **no session minted** | §3.3 step 5, SEC-INV-08 |
| SEC-T-003 | step-up complete then login finalize | valid TOTP | session minted; `auth_audit_event` `session_issued` with `mfa_factor_id` populated | §3.3 step 6 |
| SEC-T-004 | `POST /api/v1/auth/refresh` (once) | valid refresh | new token pair; old `superseded` | §3.4 |
| SEC-T-005 | `POST /api/v1/auth/refresh` (replay same JTI) | replay | `401 SESSION_REVOKED`; **entire family revoked**; `event_kind='refresh_replay_detected'` | SEC-INV-05, §3.4 step 3 |
| SEC-T-006 | any route | session from outside `bound_ip_class` | `401 SESSION_BINDING_MISMATCH` | SEC-INV-04 |
| SEC-T-007 | revoke session, wait 5001ms, retry | revoked | `401 SESSION_REVOKED` at every coordinator | SEC-INV-06 |
| SEC-T-008 | revoke session, retry within 100ms (race) | succeeds | `auth_audit_event` `revocation_race_loss` emitted; if action L2+, governance review auto-armed | SEC-INV-06 |
| SEC-T-009 | L4 mutation with no MFA assertion | fail | `403 STEP_UP_REQUIRED` + `details.step_up_challenge_id` | SEC-INV-08, §5.3 |
| SEC-T-010 | L4 mutation with TOTP assertion (not WebAuthn) | fail | `403 STEP_UP_REQUIRED` + `details.failing_check='factor_not_webauthn'` | §5.3 row L4 |
| SEC-T-011 | L4 mutation with stale (>300s) WebAuthn assertion | fail | `403 STEP_UP_REQUIRED` + `details.failing_check='assertion_expired'` | SEC-INV-08, §5.3 |
| SEC-T-012 | L4 mutation with assertion bound to different `action_key` | fail | `403 STEP_UP_REQUIRED` + `details.failing_check='action_key_mismatch'` | §5.2 rule 3, SEC-INV-08 |
| SEC-T-013 | L5 mutation with valid headers but originator non-human | fail | `403 ACTOR_TYPE_MISMATCH` | SEC-INV-09, §4.5 stage 5 |
| SEC-T-014 | L5 mutation with one approver only | fail | `403 LIVE_CONFIRM_INVALID` + `details.failing_check='approver_count'` | SEC-INV-09, §5.4 step 5 |
| SEC-T-015 | L5 mutation with two approvers but same user_id | fail | `403 LIVE_CONFIRM_INVALID` + `details.failing_check='approver_distinct'` | SEC-INV-09, §5.4 step 5 |
| SEC-T-016 | L5 mutation with `X-Live-Confirm: yes` (wrong value) | fail | `403 LIVE_CONFIRM_INVALID` + `details.failing_check='header_value'` | SEC-INV-09 |
| SEC-T-017 | L5 mutation, attestation already consumed | fail | `403 HUMAN_ATTESTATION_CONSUMED` | §2.5 rule 2 |
| SEC-T-018 | L5 route from non-allowlisted IP, with valid token | fail | `403 IP_NOT_ALLOWLISTED` (auth not even attempted) | SEC-INV-12, §4.4 row 1, §4.5 stage 1 |
| SEC-T-019 | RBAC: viewer calls `write:strategy` route | fail | `403 FORBIDDEN` + `details.required_scopes=['write:strategy']` | §4.1, SEC-INV-07 |
| SEC-T-020 | RBAC: machine actor (`claude`) gets RBAC denial | fail | `403 FORBIDDEN` + `details.required_scopes=null` | SEC-INV-07 |
| SEC-T-021 | service identity (`system`) used on human-only route | fail | `403 ACTOR_TYPE_MISMATCH` | SEC-INV-16, §4.5 stage 5 |
| SEC-T-022 | self-grant of `live_admin` | fail | `403 SELF_GRANT_FORBIDDEN` | §4.3 rule 2 |
| SEC-T-023 | grant `live_admin` without L5 approval chain | fail | `409 APPROVAL_REQUIRED` | §2.3 rule 1, `07 §2.2` |
| SEC-T-024 | secret lease for `(secret_name, action_key, route_id)` not in `secret_policies` | fail | `403 SECRET_POLICY_NOT_FOUND` | §6.4 |
| SEC-T-025 | secret lease with `ttl_ms=120_000` (above 60s cap) | fail | `400 VALIDATION` | SEC-INV-10, §6.5 CHECK |
| SEC-T-026 | secret lease re-consume | fail | `409 SECRET_LEASE_CONSUMED` | §6.5 rule 1 |
| SEC-T-027 | `consume()` closure attempts to capture value bytes outside closure | fail | static lint reject | §6.7 |
| SEC-T-028 | `process.env.<SECRET_NAME>` reference in `./v2/**` | fail | static lint reject | §6.7 |
| SEC-T-029 | rate limit exhaustion | succeeds with delay | `429 RATE_LIMITED` + `error.retry_after_ms` populated; rate decision deterministic | SEC-INV-13, §7.2 |
| SEC-T-030 | boot with `secrets_provider.health=sealed` | every protected route | `503 SERVICE_NOT_READY` + `details.failing_check='secrets_provider_unsealed'` | SEC-INV-15, §7.3 |
| SEC-T-031 | boot with `revocation_list.warm=false` | every protected route | `503 SERVICE_NOT_READY` + `details.failing_check='revocation_list_cold'` | SEC-INV-15 |
| SEC-T-032 | nightly chain-walker on `auth_audit_events` | recompute every `row_hash` | matches stored row_hash for every row; sequence_id gapless | SEC-INV-14, `07 GOV-INV-05/06` |
| SEC-T-033 | mode=paper L4 mutation skipping step-up | fail | `403 STEP_UP_REQUIRED` (no mode-branch) | SEC-INV-17 |
| SEC-T-034 | mobile rebind from new IP class with fresh MFA | success | session updated, `event_kind='session_rebound'` | §3.6 |
| SEC-T-035 | mobile rebind, 4th rebind in 1 hour | fail | session auto-revoked with `revoked_reason='rebind_quota_exceeded'` | §3.6 rule 4 |
| SEC-T-036 | rebind for `live_admin` session | fail | `403 REBIND_FORBIDDEN_FOR_ROLE` | §3.6 rule 5 |
| SEC-T-037 | secret rotation timeout | rollback | `event_kind='rotation_rolled_back'`; current version reverts | §6.6 step 5 |
| SEC-T-038 | `ip_allowlists` removal, retry after 2.1s | fail | `403 IP_NOT_ALLOWLISTED` | §7.1 rule 2 |
| SEC-T-039 | re-evaluation determinism | run permission resolver twice with same inputs | byte-identical decision and `failing_check` | SEC-INV-03 |
| SEC-T-040 | re-evaluation determinism (rate limit) | replay bucket state + clock | identical `Retry-After` | SEC-INV-13 |

---

## 11. Audit / evidence-packet requirements

Two new evidence-packet kinds are introduced; both follow `04_API_CONTRACT_REMEDIATION.md §1.4` lineage requirements and `07_AI_GOVERNANCE_REMEDIATION.md §13` event envelope.

### 11.1 `evidence_packet_kind = 'auth_audit_chain'`

Emitted nightly. Walks `auth_audit_events` from the prior packet's `last_sequence_id+1` through `now`; recomputes every `row_hash`; verifies gapless `sequence_id`; verifies every row's `prev_hash` matches the prior row's `row_hash`. Records:

```json
{
  "schema_version": "1.0.0",
  "evidence_packet_kind": "auth_audit_chain",
  "evidence_packet_id": "uuid-v7",
  "captured_ts_ms": 1735689600000,
  "first_sequence_id": 100001,
  "last_sequence_id": 105234,
  "rows_walked": 5234,
  "hash_chain_ok": true,
  "first_failing_sequence_id": null,
  "row_hash_at_first_fail": null,
  "expected_prev_hash": null,
  "actor_breakdown": { "human": 4321, "claude": 0, "codex": 0, "ollama": 0, "system": 913 },
  "event_kind_breakdown": { "session_issued": 312, "session_revoked": 14, "refresh_rotated": 4001, "...": "..." }
}
```

If `hash_chain_ok=false`, the security coordinator transitions to `accepting_auth=false` and a `chain_integrity_breach` packet is also emitted (per `07 GOV-INV-06`).

### 11.2 `evidence_packet_kind = 'public_hosting_hardening'`

Already specified in §7.3. Re-emitted on every deployment and hourly thereafter.

### 11.3 Lineage requirement

Every `auth_audit_event` row carries the lineage tuple per `07 GOV-INV-10`. For events that arose from a governed mutation (e.g. `secret_leased` for an L5 rotation), `approval_chain_id` is populated; for events that did not (e.g. `session_issued` from a successful login), `approval_chain_id IS NULL` AND `details_json.lineage_gap_reason='auth_event_no_governance_subject'` is set explicitly. There is no silent omission.

---

## 12. Traceability — Codex Blocker 7 sub-claims to closing sections

| Codex sub-claim | Closing section(s) |
| --- | --- |
| "user-role mapping" | §2.1 (`users`), §2.2 (`roles`), §2.3 (`role_grants`); §4.3 (role→scope), §4.1 (decision algorithm) |
| "sessions/tokens with revocation" | §3.1 (`sessions`), §3.2 (token shapes), §3.3 (issuance), §3.4 (refresh-rotation single-use), §3.5 (revocation flow), SEC-INV-04, SEC-INV-05, SEC-INV-06 |
| "permission matrix per route" | §4.2 (`route_scope_table`), §4.3 (`role_scope_table`), §4.4 (denial precedence), §4.5 (middleware chain), SEC-INV-01, SEC-INV-03, SEC-INV-07 |
| "MFA flow" | §5.1 (`mfa_factors`), §5.2 (`mfa_assertions`), §5.3 (freshness windows), §5.4 (L5 dual-assertion), §5.5 (anti-bypass), SEC-INV-08, SEC-INV-09 |
| "server-side secrets / secret-provider boundary" | §6.1 (provider capabilities), §6.2 (provider classes), §6.3 (boundary interface — leases only), §6.4 (`secret_policies`), §6.5 (`secret_leases`), §6.6 (rotation), §6.7 (forbidden patterns), SEC-INV-10, SEC-INV-11 |
| "IP controls" | §7.1 (`ip_allowlists`), §4.5 stage 1 (guard order), SEC-INV-12 |
| (Provisional finding 1) "auth/session lifecycle missing" | §3 in full |
| (Provisional finding 2) "RBAC granularity" | §4 in full |
| (Provisional finding 3) "secrets boundary not concretely defined" | §6 in full |
| (Provisional finding 4) "step-up auth not integration-scaffolded" | §5 in full + §5.4 L5 dual-assertion |
| (Provisional finding 5) "public-hosting verification contract" | §7.3 (`public_hosting_hardening` packet), §11.2 |
| `CLAUDE.md` "LIVE TRADING: BLOCKED" default | §4.2 (live routes require `write:live_gate` + L5 + IP allowlist + `X-Live-Confirm`); §5.4 dual-assertion; SEC-INV-09 |
| `CLAUDE.md` "Level 5 is never autonomous" | §5.4, SEC-INV-09, §4.5 stage 5 (`actor_type_guard`) |
| `CLAUDE.md` "no unauthenticated trading controls" | §4.2 every mutating row sets `Auth=yes`, SEC-INV-02, SEC-INV-15 |
| `CLAUDE.md` "admin-only dangerous controls" | §4.3 role-scope table; L5 routes require `write:live_gate` (only granted to `live_admin`) |
| `CLAUDE.md` "no GUI secret exposure" | §6.3 boundary interface (no raw-value accessor); §6.7 forbidden patterns |
| `CLAUDE.md` Mobile/iPhone Future Rule | §3.6 (session re-binding for mobile roaming), §5.3 (TOTP permitted at L3 for mobile-first PWA flows; WebAuthn required at L4+) |
| Cross-reference into `07` audit chain | §8 binding table; §9 row shape carries `prev_hash`/`row_hash`; §10 SEC-T-032; §11.1 nightly chain packet |
| Cross-reference into `04` envelope/error catalog | §4.4 denial precedence references `04 §3` error classes; §8 binding table |
| Cross-reference into `05`/`06` step-up gates | §8 binding table; §4.2 `policy_bundles` and `hot_reload` rows |

---

## 13. Gate recommendation

Status of Codex Blocker 7 (security/RBAC scaffold) per this remediation: **closed at architecture layer**, conditional on:

1. Scaffold implementation passing every row of the §10 test-vector matrix (40 tests, SEC-T-001 through SEC-T-040).
2. The `auth_audit_chain` evidence packet (§11.1) emitting `hash_chain_ok=true` over a contiguous 7-day window before V2 build clears the gate.
3. The `public_hosting_hardening` packet (§7.3 / §11.2) emitting `all_ok=true` for the target deployment profile at the moment the gate is evaluated.
4. Static lint rules from §6.7 active in CI and passing on `./v2/**`.
5. Re-running the actual Codex CLI architecture review (`12_ACTUAL_CODEX_CLI_ARCHITECTURE_REVIEW_OUTPUT.md` regeneration) against the amended `15_PUBLIC_HOSTING_SECURITY_AND_RBAC_ARCHITECTURE.md` and getting an explicit PASS on Blocker 7.

Until conditions 1–5 are met, V2 build remains **NO-GO** per `13_ACTUAL_CODEX_RECONCILIATION.md`. The `LIVE TRADING: BLOCKED` default per `CLAUDE.md` is independently enforced by the `live_confirm_guard` (§4.5 stage 7) — closing this blocker does not lift that block; the live-trading lift is itself an L5 action gated by this layer.
```