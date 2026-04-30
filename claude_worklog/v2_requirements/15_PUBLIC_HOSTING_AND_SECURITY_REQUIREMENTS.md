# 15 Public Hosting and Security Requirements

## Requirement ID
V2-HOSTING-SECURITY-001

## Objective
Platform is local-first but public-hosting ready with enterprise-grade security controls.

## Mandatory security requirements
1. Authentication
- No unauthenticated access to operator/admin endpoints.
- Session and token lifecycle controls with revocation.

2. RBAC
- Enforce role boundaries (viewer/operator/admin/security-admin).
- Trading-control actions restricted by least-privilege policy.

3. Transport and edge
- HTTPS/TLS mandatory.
- Reverse proxy/WAF-ready ingress model.
- Request rate limits and abuse controls.

4. Audit logging
- Immutable audit logs for auth, control actions, config changes, and gate overrides.

5. Network controls
- IP allowlist support for admin/trading-control surfaces.
- Zero-trust-friendly policy model for future remote/public hosting.

6. 2FA readiness
- Architecture must support 2FA for admin and dangerous actions.

7. Secrets handling
- Secrets must never be exposed in GUI responses or client-side bundles.
- Secret access only server-side through approved secret provider boundary.

## Public hosting readiness requirements
- Deployment model supports internet-facing posture without redesign.
- Security controls are first-class in platform architecture, not post-hoc patches.
- Security posture dashboard included in deployment admin area.

## Trading-control safety
- Trading mutation controls remain blocked unless live readiness gates pass.
- Dangerous actions require explicit approval and audit record.

## Pre-architecture acceptance
- Auth/RBAC/TLS/reverse-proxy/rate-limit/audit/IP-allowlist/2FA-ready controls are all in requirement baseline.
