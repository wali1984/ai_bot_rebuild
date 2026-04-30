# 07 Security, Hosting, and RBAC Review

## Scope
Verify public hosting readiness, security baseline, and RBAC are represented.

## Inputs
- Architecture: 03, 05, 15
- Requirements: 10, 15

## Mandatory security controls

| Control | Requirement 15 | Architecture 15 | Verdict |
|---|---|---|---|
| Authentication (no unauth access; session/token revocation) | yes | yes | covered |
| RBAC (viewer/operator/admin/security-admin) | yes | yes (role separation principle in 06; `roles` table in 03) | covered |
| HTTPS/TLS mandatory | yes | yes | covered |
| Reverse proxy / WAF / rate limits | yes | yes (edge ingress layer 1) | covered |
| Audit logs (immutable, action/config/auth) | yes | yes (`audit_events` 03; ledger 13) | covered |
| IP allowlist for admin/trading-control | yes | yes | covered |
| 2FA-ready architecture | yes | yes | covered |
| Secrets server-side only; never in GUI payloads | yes | yes (file 15 secrets policy) | covered |
| No unauthenticated trading-control endpoints | yes | yes (file 05 safety behavior) | covered |

## Layered architecture
File 15 defines five layers (edge ingress / auth+session / RBAC+approval middleware / API services / audit+telemetry). This is sufficient for public-hosting readiness.

## Public hosting readiness
- Deployment model supports internet-facing posture without redesign — covered (15 + 17).
- Security posture dashboard in deployment admin area — covered (06 Deployment/Hosting Admin page).
- Auth/RBAC/audit are first-class in core, not bolt-on — covered.

## RBAC enforcement points
- API contracts (05) require auth + RBAC + audit envelope on every mutation endpoint.
- Risk-level tagged operations require approval workflow (05 + `approvals` table 03).
- GUI page map (06 + requirement 16) separates `controls` from `admin-only controls` for every page.

## Trading-control safety
- Live mutations remain blocked until live readiness gates pass — covered (architecture 05, 09, 12, 17).
- Dangerous actions require approval and audit — covered.

## Risks and notes
- File 15 is concise (25 lines). Build-phase artifacts must include concrete role definitions, permission JSON shape, secret-provider boundary spec, and 2FA mechanism (TOTP/WebAuthn).
- IP allowlist policy is declared but not detailed; this is acceptable at architecture phase.
- Database schema 03 includes `users`, `roles`, `approvals`. Sufficient for RBAC persistence.

## Verdict
Security, hosting, and RBAC baselines are present and adversarial-review-ready. No mandatory control is unrepresented.
