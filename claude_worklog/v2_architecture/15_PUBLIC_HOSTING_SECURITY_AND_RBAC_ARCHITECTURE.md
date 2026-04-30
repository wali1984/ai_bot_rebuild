# 15 Public Hosting, Security, and RBAC Architecture

## Security baseline
- auth
- RBAC
- 2FA-ready
- HTTPS/TLS
- reverse proxy
- rate limits
- IP allowlist
- audit logs
- secrets isolation
- no unauthenticated trading controls
- admin-only dangerous controls

## Layered architecture
1. Edge ingress (TLS, reverse proxy, WAF/rate policy)
2. Auth/session service
3. RBAC + approval middleware
4. API services
5. Audit and security telemetry

## Secrets policy
- Server-side secret handling only.
- No credential exposure in UI payloads.
