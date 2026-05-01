# 15 — Public Hosting Security and RBAC Architecture

> Canonical security, identity, RBAC, MFA, secrets, and edge-control
> contract for V2. Replaces the prior 26-line stub. Source remediation:
> `claude_worklog/v2_architecture_remediation/08_SECURITY_RBAC_REMEDIATION.md`.

## 1. Non-bypass invariants (SEC-INV-01..18)

1. SEC-INV-01 — TLS terminated only at the trusted edge; intra-mesh requires mTLS.
2. SEC-INV-02 — All routes pass through the standard middleware chain (§4); no bypasses for "internal".
3. SEC-INV-03 — Sessions and tokens are server-side revocable; client-side expiry alone is insufficient.
4. SEC-INV-04 — MFA freshness window enforced for L3+ and re-verified for L4/L5 step-up.
5. SEC-INV-05 — RBAC is allowlist-only; missing scope means deny.
6. SEC-INV-06 — Service identities never inherit human approval capabilities.
7. SEC-INV-07 — Secrets are leased, never embedded; lease TTL ≤ tier ceiling.
8. SEC-INV-08 — Lease issuance requires chain consumption for L3+ leases.
9. SEC-INV-09 — IP allowlist applied before authentication for live-mutation routes.
10. SEC-INV-10 — Per-route rate limits enforced; lockout audited.
11. SEC-INV-11 — Auth audit events are append-only and hash-chained (§9).
12. SEC-INV-12 — Step-up auth produces a signed assertion bound to action class + window.
13. SEC-INV-13 — Human-origin attestations required for any approval seat.
14. SEC-INV-14 — Token replay across origins forbidden (audience binding).
15. SEC-INV-15 — Session fixation prevented (rotate on auth state change).
16. SEC-INV-16 — Password / WebAuthn material never logged or transmitted to non-auth services.
17. SEC-INV-17 — Tenant isolation enforced in DB row-level policies, not only in handlers.
18. SEC-INV-18 — Hardening evidence collected at deploy and stored under `raw_evidence/security/`.

## 2. Identity and account model

```
users(user_id PK, primary_email, display_name, status, created_at)
roles(role_id PK, name, description)
role_scopes(role_id, scope, PK(role_id, scope))
role_grants(grant_id PK, user_id, role_id, tenant_id|null, granted_by, granted_at, expires_at)
service_identities(svc_id PK, name, owner_team, status, created_at)
service_identity_scopes(svc_id, scope, PK(svc_id, scope))
human_origin_attestations(attestation_id PK, user_id, factor_kind, evidence_ref, attested_at)
```

Service identities cannot be granted L4/L5 capabilities; human origin attestation is required for approver seats.

## 3. Session and token lifecycle

| Token | Issuer | TTL | Audience binding | Revocation |
| --- | --- | --- | --- | --- |
| Session cookie | auth service | 12h sliding | host | server-side store |
| Access JWT | auth service | 5m | service audience | rotation + jti revoke list |
| Refresh token | auth service | 14d, sliding | session id | revocation list |
| Step-up assertion | mfa service | ≤ action-class window (typ. 5m) | action_class + body_hash | one-shot consume |
| Service token | identity service | 1h | service audience | rotation + jti revoke |

Lifecycle:
- Login → MFA → session + refresh.
- Access JWT minted from refresh.
- Step-up minted from active session + MFA assertion bound to declared action_class.
- All tokens checked against `revocation_lists` (§13 §12) on each verification.

## 4. RBAC route-permission matrix and middleware chain

### 4.1 Route → required scopes
Examples:
- `POST /v1/risk/policies/{id}/activate` → `risk:policy:activate` + level ≥ L4.
- `POST /v1/connectors/{id}/live_enable` → `connector:live:enable` + level L5.
- `POST /v1/mode/switch` → `mode:switch` + level L5.
- `POST /v1/iam/role_grants` → `iam:role:grant` + level L3.
- `GET /v1/audit/events` → `audit:event:read`.
- `POST /v1/hot_reload/rollouts` → `hot_reload:rollout:create` + level L4.

### 4.2 Middleware chain (12 stages, in order)
1. Edge controls (TLS, IP allowlist, WAF).
2. Request envelope validation.
3. Session / token verification + revocation check.
4. MFA freshness check (route-level requirement).
5. Tenant context resolution + isolation enforcement.
6. RBAC scope evaluation.
7. Route-level rate limit.
8. Approval gate evaluation (chain id required if route declares level ≥ L1).
9. Live-block envelope (per `05` §7).
10. Idempotency replay check.
11. Optimistic concurrency check.
12. Handler dispatch.

Each stage emits an audit event on denial; passing stages are batched into one trace event.

## 5. Step-up authentication

```
mfa_factors(factor_id PK, user_id, kind: 'totp'|'webauthn'|'hwkey', enrollment_evidence_ref, enrolled_at, status)
mfa_assertions(assertion_id PK, user_id, factor_id, action_class, body_hash, asserted_at, consumed_at|null, expires_at)
```
Flow:
- Client requests step-up with `action_class` and `body_hash`.
- Server requires fresh factor proof (≤ 60 s for L5, ≤ 5 min for L4).
- Server issues `mfa_assertion`; client attaches `assertion_id` in chain creation.
- L5 dual-assertion: two distinct users, each providing a fresh assertion bound to the same `action_class` + `body_hash`.

## 6. Secrets provider boundary (lease-only)

```
SecretsProvider {
  issue_lease(secret_ref, requester_subject, ttl, chain_id|null) -> lease
  revoke_lease(lease_id, reason) -> ack
  introspect_lease(lease_id) -> metadata (no material)
}
```
Constraints:
- Application code obtains material only via short-lived lease.
- Material never persisted to disk by app; only in process memory.
- L3+ leases require consumed approval chain.
- All issue/revoke audited (§9).

## 7. Edge controls

- Mandatory IP allowlist for live-mutation routes; default-deny.
- WAF rules versioned and deployed alongside app; rule pack hash recorded in deployment evidence.
- Per-route rate limits + per-subject burst caps; sustained breach → temporary lockout audited.
- Hardening evidence packet at deploy time: TLS config, WAF rule pack hash, IP allowlist diff, dependency pin lockfile, secret store reachability proof.

## 8. Cross-domain bindings

- Approval chains (`13`) reference `mfa_assertion.assertion_id` in approver assertions.
- Hot-reload (`08`) requires session+RBAC+approval chain at `POST /v1/hot_reload/rollouts`.
- Risk Gateway live-gate (`12` §9) requires consumed L5 chains rooted in dual-assertion.
- Connector boundary (`12` §10) re-verifies tenant isolation and IP origin.

## 9. Durable persistence (auth_audit_events with hash chain)

```
auth_audit_events(event_id PK, stream_id, seq, ts, actor_subject, kind, payload jsonb, prev_hash, hash)
```
Anchored daily into `audit_anchors` together with `audit_ledger` (§13 §9 / §12).

## 10. Test-vector matrix (SEC-T-001..040)

40 vectors across: TLS/edge (5), session lifecycle (6), MFA freshness (5), L5 dual-assertion (4), RBAC allowlist (5), tenant isolation (4), secrets lease (4), audit chain (3), rate-limit/lockout (2), hardening evidence presence (2).

## 11. Audit / evidence packets

Per deploy: hardening evidence packet under `raw_evidence/security/<deploy_id>/`.
Per security event of interest: token revocation logs, MFA enrollment/assertion logs, IP allowlist changes, WAF rule diffs.