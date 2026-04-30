# 09 Security and Hosting Review

## Scope
Adversarial review of local-first/public-hosting-ready security posture.

## What is covered
- Auth, RBAC, 2FA-ready, TLS, reverse proxy, rate limits, IP allowlist.
- Audit logs and secrets isolation are stated.
- No unauthenticated trading controls and no GUI secret exposure are explicitly required.

## Adversarial findings
1. **Auth/session lifecycle contract is missing (HIGH blocker)**
   - No concrete session/token rotation, revocation, expiry, and replay-protection contract.

2. **RBAC permission model lacks implementable granularity (HIGH)**
   - Roles exist, but permissions schema and route binding are not specified.

3. **Secrets provider boundary not concretely defined (MEDIUM)**
   - Server-side only policy exists, but no architecture contract for provider type, access scope, rotation, and audit coupling.

4. **2FA-ready is declared but not integration-scaffolded (MEDIUM)**
   - No explicit auth flow extensions for step-up auth on dangerous actions.

5. **Public-hosting hardening checklist lacks verification contract (LOW)**
   - Rate-limit and allowlist exist as requirements, but verification evidence schema is not standardized.

## Verdict
Security baseline intent is strong, but public-hosting control contracts are not yet precise enough for safe scaffold implementation.
