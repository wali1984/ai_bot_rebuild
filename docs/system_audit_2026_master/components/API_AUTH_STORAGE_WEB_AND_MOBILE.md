# API, Authentication, Storage, Web, and Mobile

## Reverse-engineering baseline

**Snapshot date:** 2026-07-16, America/New_York

**Scope:** FastAPI assembly and routes, middleware, authentication and authorization, state-changing HTTP and WebSocket surfaces, worker concurrency, Redis/SQLite/file persistence, React/Vite delivery, Swift clients, Cloudflare ingress, observability, tests, CI, and rebuild/change-impact requirements.

**Change policy:** This document records the system as found. No runtime, strategy, risk, training, exchange, order, or client code was changed while producing it.

**Secret handling:** Secret values, bearer credentials, passwords, exchange credentials, cookie contents, JWTs, and tunnel tokens are intentionally omitted.

This is a low-level current-state document, not a claim that every current behavior is desirable. Where source comments, tests, generated schema, and deployed behavior disagree, the disagreement is recorded explicitly.

## 1. Evidence hierarchy and count semantics

The following evidence classes must not be conflated:

1. **Mounted runtime truth:** the route graph returned by `create_app()`, its generated OpenAPI document, and direct probes of the deployed listeners.
2. **Deployed process truth:** active systemd units, process arguments, listening sockets, environment-selected backends, and current Redis/filesystem state.
3. **Reachable source truth:** code imported and registered by `v2/backend/app/main.py`.
4. **Dormant source truth:** decorators and modules present in the repository but not registered in the current application factory.
5. **Static atlas truth:** repository-wide definitions and references, including client references and unmounted code. It is an impact index, not an endpoint count.

At this snapshot, the mounted application reports:

| Measure | Count | Meaning |
|---|---:|---|
| OpenAPI path templates | 189 | Unique HTTP path templates in the generated schema |
| OpenAPI operations | 193 | 158 `GET`, 27 `POST`, 4 `PUT`, 0 `PATCH`, and 4 `DELETE` |
| OpenAPI state-changing operations | 35 | All `POST`, `PUT`, and `DELETE` operations; some compute only, but all require mutation review |
| Starlette `APIRoute` objects | 229 | Mounted HTTP route objects, including routes omitted from OpenAPI or represented differently there |
| Starlette `APIWebSocketRoute` objects | 7 | Mounted WebSocket routes; OpenAPI does not describe them |
| Other Starlette `Route` objects | 4 | Framework/static routes outside `APIRoute` |
| Starlette `Mount` objects | 2 | Conditional static mounts in the observed application graph |
| Total Starlette route objects | 242 | All categories above |
| Static atlas API definitions/references | 997 | Repository definitions plus client/code references; **not** 997 mounted endpoints |

The generated OpenAPI document contains no `securitySchemes`, no global `security` declaration, and no operation-level `security` requirements. FastAPI renders the custom authentication inputs as optional `authorization` headers and optional `alphaforge_session` cookies. Runtime dependencies still reject unauthorized requests on protected routes, but generated clients, API gateways, security scanners, and human readers cannot infer the protection model from the schema.

Primary assembly source: `v2/backend/app/main.py:26-308`. Static count source: `docs/system_audit_2026_master/atlas/ATLAS_SUMMARY.md`.

## 2. Deployed request topology

The observed local deployment is:

```text
External client
    |
    | Cloudflare Tunnel
    | remote hostname/path routing is not stored locally
    v
+-----------------------------+
| cloudflared system service  |
+-----------------------------+
       |                 |
       | origin choice is controlled outside this repository
       v                 v
+----------------+   +------------------------------------+
| Vite preview   |   | Uvicorn/FastAPI                    |
| 0.0.0.0:5173   |   | 127.0.0.1:8000                    |
| built React UI |   | 4 worker processes                 |
| /api -> :8000  |   | API, WebSockets, optional SPA      |
| /ws  -> :8000  |   | and operator-runtime static mount  |
+----------------+   +------------------------------------+
                             |
              +--------------+------------------+
              |              |                  |
              v              v                  v
          Redis DB 0     JSON/files        optional SQL/
          shared state   and artifacts     SQLite stores
```

Active relevant units at the snapshot:

- `ai-bot-v2-public-website-backend.service` runs Uvicorn on `127.0.0.1:8000` with four workers, proxy headers trusted only from `127.0.0.1`, no reload, and a one-second keep-alive timeout.
- `ai-bot-v2-frontend-vite.service` runs Vite preview on `0.0.0.0:5173` and points its API proxy at `127.0.0.1:8000`.
- `cloudflared.service` is active and supplies external ingress.

The backend unit currently receives its working directory and `PYTHONPATH` from systemd drop-ins that point at the mutable repository checkout. A backend restart can therefore change deployed behavior to whatever is in the working tree at restart time. The Vite service serves a previously produced `dist` tree until a frontend build is run; backend and frontend can consequently be on different source revisions.

The backend unit description calls the service read-only. That description is false as an operational contract: mounted handlers can write Redis, replace JSON files, append audit artifacts, start subprocesses, reset paper state, and mutate the runtime live-execution state.

## 3. FastAPI application construction

### 3.1 Factory sequence

`create_app()` in `v2/backend/app/main.py:299-308` performs this sequence:

1. Construct a `FastAPI` application with Swagger UI at `/api/docs`.
2. Register routers from the tuple in `v2/backend/app/main.py:92-142`.
3. Register middleware using `v2/backend/app/main.py:67-89`.
4. Register conditional SPA/static delivery using `v2/backend/app/main.py:173-266`.
5. Attach a lifespan hook that changes AnyIO's default thread-pool limiter to 120 tokens per worker (`v2/backend/app/main.py:269-296`).

The top-level health handler is exposed through both `/health` and `/api/health` (`v2/backend/app/main.py:145-170`). V1 route modules are generally included under `/api/v1`. The authentication/RBAC router already contains `/api` in its own prefix and is mounted directly. V2 and market-stream routers are mounted according to their declared prefixes.

If the frontend distribution directory exists, the backend can mount `/assets`, optionally mount `/operator_runtime`, cache the SPA index, and answer a catch-all with that index. In the observed deployment, a separate Vite preview service is also active, so there are two distinct web-serving implementations with different path behavior.

### 3.2 Import-time side effect

The module documentation says application import performs no I/O. That is not true for the complete import graph. `v2/backend/app/auth/security.py:45-83` loads a process secret or creates a local secret file during import when a configured secret is absent. With four workers starting concurrently, first-start creation is a race unless the secret is supplied deterministically. The observed secret file had restrictive mode `0600`; its value was not inspected or recorded.

Rebuild rule: production startup must receive an explicit secret through a managed credential mechanism. Importing a module must not create identity material or depend on a race-prone shared file.

### 3.3 Thread-pool multiplication

The 120-token AnyIO limit is per process. Four workers make as many as 480 blocking thread-pool operations eligible to run concurrently, before accounting for subprocesses and work outside AnyIO. This is a capacity multiplier, not a global server limit. Database pools, filesystem contention, Redis connection limits, CPU saturation, and upstream rate limits must be sized against the multiplied value.

## 4. Middleware: installed order versus enforced behavior

`v2/backend/app/api/middleware/__init__.py:27-39` defines this outer-to-inner order:

| Order | Middleware | Current enforcement |
|---:|---|---|
| 1 | CORS | Enforces a local-development origin allowlist; credentials are allowed and all methods/headers are accepted. See `v2/backend/app/api/middleware/cors.py:8-24`. |
| 2 | Request ID | Scaffold delegates to the next application; it does not provide the named production contract. |
| 3 | IP allowlist | Scaffold delegates; no effective allowlist is established here. |
| 4 | Rate limit | Scaffold delegates; no effective request throttling is established here. |
| 5 | Step-up MFA | Scaffold delegates; route-level code is the only observed explicit step-up enforcement. |
| 6 | RBAC | Scaffold delegates; FastAPI dependencies and one legacy header check perform the actual authorization. |
| 7 | Idempotency | Scaffold delegates; duplicate mutation protection is not provided globally. |
| 8 | Lineage | Scaffold delegates; request/data lineage is not added or verified globally. |
| 9 | Approval | Scaffold delegates; live/admin approval semantics exist only in individual handlers. |
| 10 | Live block guard | Enforces only the exact `/api/v1/live` prefix. See `v2/backend/app/api/middleware/live_block_guard.py:34-57`. |
| 11 | Database error translator | Scaffold delegates; no comprehensive cross-repository translation contract is established here. |

The live block guard does **not** cover `/api/v1/live-gate`, `/api/v2`, admin controls, pipeline controls, or paper mutation routes. This is important because `/api/v1/live-gate/enable` can write shared runtime execution state. Prefix naming, not a capability marker, currently determines guard coverage.

The middleware-order contract test is stale. `v2/backend/tests/contract/test_middleware_order.py:23-57` expects ten layers and omits CORS, while the factory installs eleven. The focused test result was two failures and one pass.

Rebuild rule: every middleware name must either enforce a tested invariant or be removed from the security model. Security reviews must not count a pass-through class as a control.

## 5. Authentication and authorization

### 5.1 Identity stores and roles

The backend role enum is:

```text
guest < viewer < trader < admin < superadmin
```

It is defined in `v2/backend/app/auth/security.py:28-36`. User validation and the local/SQL backend selector live in `v2/backend/app/auth/users.py:26-180`.

The default non-production user backend is a JSON file with bcrypt password hashes. Production is intended to fail closed unless a SQL backend is configured. Password-complexity enforcement is production-dependent (`v2/backend/app/auth/users.py:184-214`). `safe_user()` emits public user fields under an object whose identifier key is `id`, not `user_id` (`v2/backend/app/auth/users.py:290-306`).

The frontend has a different presentation-role model in `v2/frontend/src/auth/rbac.ts:4-40`; it normalizes `superadmin` into a UI concept named `live_approver`. The frontend session shell can also take a role from a query parameter and store it in `sessionStorage` (`v2/frontend/src/auth/session.ts:19-70`). Those values control presentation only. They are not, and must never become, an authorization boundary.

### 5.2 JWT contract

The backend implements an HS256 JWT contract in `v2/backend/app/auth/security.py:519-647`. The token includes at least:

| Claim | Meaning |
|---|---|
| `iss` | Configured issuer; checked during verification |
| `aud` | Configured audience; checked during verification |
| `sub` | User identity |
| `role` | Role captured when the token was issued |
| `trader` | Trader/scoping metadata |
| `session_version` | Version compared with the current user record |
| `jti` | Token identifier used for revocation |
| `iat` | Issue time; validated |
| `exp` | Expiration; validated |

Signature, issuer, audience, expiration, issue time, and revocation are checked. `require_auth` then reloads the active user and compares `session_version`, so disabling a user or changing session version can invalidate an otherwise cryptographically valid token (`v2/backend/app/auth/security.py:679-696`).

When both transports are present, an `Authorization: Bearer ...` token takes precedence over the cookie (`v2/backend/app/auth/security.py:650-660`). `optional_auth` catches invalid authentication and returns anonymous identity (`v2/backend/app/auth/security.py:699-719`). An endpoint using `optional_auth` therefore treats an absent token and an invalid token equivalently unless the handler adds a distinction.

### 5.3 Browser session contract

The browser flow is:

```text
POST /api/auth/login
    -> load user store
    -> bcrypt verification in bounded worker thread
    -> issue JWT
    -> set HttpOnly alphaforge_session cookie
    -> also return raw access_token in JSON
```

The route implementation is `v2/backend/app/api/auth_rbac.py:192-221`. The React client sends requests with credentials and relies on the cookie (`v2/frontend/src/api/auth.ts:135-234`, `v2/frontend/src/hooks/useAuth.tsx:54-64`); it does not intentionally persist the login response token. One legacy Binance page reads `localStorage.af_token` (`v2/frontend/src/pages/binance/index.tsx:384`), which is inconsistent with the main session design.

Cookie behavior is secure in production or when explicitly configured, and the default SameSite mode is `lax` (`v2/backend/app/auth/security.py:263-290`). No explicit CSRF token verification was found. `v2/frontend/src/auth/session.ts:3-16` carries a `csrfToken` field that is always `null`. SameSite cookies reduce some cross-site request risk but are not a full CSRF contract, especially if origin, subdomain, redirect, or future cookie policy changes.

The login response returning the bearer token is necessary for current mobile/CLI-style clients, but it expands the exposure surface for browser callers, logs, debugging tools, and extensions. A rebuild should define separate browser-session and native-token flows or otherwise make transport policy explicit.

### 5.4 Session lifecycle

- `POST /api/auth/logout` uses optional authentication. If a valid token is present it records revocation, then clears the cookie (`v2/backend/app/api/auth_rbac.py:253-267`).
- `POST /api/auth/refresh` requires authentication, issues a replacement token, then revokes the prior token (`v2/backend/app/api/auth_rbac.py:270-291`).
- `GET /api/auth/me` returns `{"user": <safe_user>, "session_security": ...}`, not a flat user object (`v2/backend/app/api/auth_rbac.py:294-296`).
- `POST /api/auth/register` is public and creates an active viewer account before issuing a session (`v2/backend/app/api/auth_rbac.py:299-331`).
- Password change checks the current password and revokes the current session lineage (`v2/backend/app/api/auth_rbac.py:448-468`).

The current session-security health response reports a local-file backend, no durable session store, no durable user/session/revocation guarantees, MFA disabled, and `production_ready=false`. `session_security_status()` currently hard-codes `durable_session_store=False`, so its production-ready expression cannot become true under the current implementation even if other configuration is corrected (`v2/backend/app/auth/security.py:422-507`).

Revocation can use a local JSON file or SQL (`v2/backend/app/auth/security.py:332-420`). Local replacement is atomic at the single-file level, but locking is process-local and cannot serialize four workers (`v2/backend/app/auth/security.py:543-589`).

### 5.5 Step-up authentication

TOTP step-up is enforced only in production; the helper succeeds unconditionally in non-production (`v2/backend/app/auth/security.py:311-329`). Among the mounted admin-user mutations, activation explicitly accepts and verifies `X-AlphaForge-Step-Up-Code`. Admin user creation, general update, deletion, and trader-account upsert require the admin dependency but do not explicitly require step-up (`v2/backend/app/api/auth_rbac.py:479-639`).

The entire live-gate mutation router requires `superadmin`, but its routes do not add the explicit TOTP dependency. Typed confirmation phrases and audit identifiers are workflow checks, not proof of a second factor.

### 5.6 Authorization exception: pipeline header role

`POST /api/v2/pipeline/run` uses `require_min_role("operator")` from `v2/backend/app/api/v2/_common.py:99-121`. That helper trusts an `X-Role` request header; it does not validate the signed JWT/session identity described above. A caller able to reach the endpoint can supply the expected role header. If `dry_run=false`, the service queues shared Redis state (`v2/backend/app/services/pipeline_control/service.py:475-553`). This is a distinct and unsafe authorization system embedded inside the same API.

## 6. Complete mounted state-changing HTTP inventory

This table enumerates every non-`GET` operation in the generated OpenAPI schema at the snapshot. “Mutation” includes session state, file/Redis/SQL state, process creation, and paper/runtime controls. `POST /api/v2/orders/preview` computes only, but remains in the inventory because it is a non-idempotent method and accepts an order-shaped payload.

| # | Method and path | Runtime gate | Side effect and contract caveat |
|---:|---|---|---|
| 1 | `POST /api/v1/live-gate/evaluate` | `superadmin` | Rebuilds and writes live-gate public/worklog output artifacts; does not itself enable execution. |
| 2 | `POST /api/v1/live-gate/arm` | `superadmin` | Computes whether enable is available and returns an arm response; currently no durable arm state. |
| 3 | `POST /api/v1/live-gate/accept-risk-profile` | `superadmin` plus typed confirmation/body evidence | Replaces acceptance artifacts, appends audit data, and rewrites flow outputs. |
| 4 | `POST /api/v1/live-gate/accept-live-symbols` | `superadmin` plus typed confirmation/body evidence | Validates current paper evidence, writes symbol acceptance/audit artifacts, and rewrites flow outputs. |
| 5 | `POST /api/v1/live-gate/final-approval` | `superadmin` plus typed confirmation and matching prior audit IDs | Writes final approval/audit artifacts; no explicit TOTP dependency. |
| 6 | `POST /api/v1/live-gate/accept-failover-exchange` | `superadmin` plus typed confirmation/evidence | Writes failover-exchange acceptance and audit artifacts; asserts no live transport enable. |
| 7 | `POST /api/v1/live-gate/accept-failover-symbols` | `superadmin` plus typed confirmation/evidence | Writes failover-symbol acceptance and audit artifacts. |
| 8 | `POST /api/v1/live-gate/failover-final-approval` | `superadmin` plus typed confirmation and matching prior audit IDs | Writes failover final-approval/audit artifacts; still reports order submission disabled. |
| 9 | `POST /api/v1/live-gate/enable` | `superadmin`, typed confirmation, exact acceptance/audit linkage, conservative-profile checks, no blockers | Calls `write_runtime_execution_state()`, which can write allowlisted Redis runtime keys plus public/worklog JSON state. This route is outside the `/api/v1/live` middleware guard. If `V2_RELEASE_MODE` is not `LIVE_CANARY_APPROVED`, the writer disarms the resulting runtime state. The snapshot release state was non-live. |
| 10 | `POST /api/auth/login` | Public credentials | Performs password verification, sets session cookie, and returns a raw access token. |
| 11 | `POST /api/auth/logout` | Optional auth | Revokes a valid presented token if possible and clears the cookie. An invalid token is treated as anonymous. |
| 12 | `POST /api/auth/refresh` | Authenticated | Issues a new token and revokes the previous token. |
| 13 | `POST /api/auth/register` | Public | Creates an active viewer and issues a session. Public registration is an intentional exposed account-creation path. |
| 14 | `POST /api/accounts/me/exchange-accounts` | Authenticated trader account context | Writes exchange-account metadata; credential-handling and repository backend policy are security-critical. |
| 15 | `DELETE /api/accounts/me/exchange-accounts/{account_id}` | Authenticated owner | Removes linked exchange-account metadata. |
| 16 | `PUT /api/accounts/me/watchlist` | Authenticated | Replaces the caller's watchlist. |
| 17 | `POST /api/accounts/me/change-password` | Authenticated plus current password | Replaces the password hash and invalidates session lineage. |
| 18 | `POST /api/admin/users` | `admin` | Creates a user. No explicit route-level step-up. |
| 19 | `PUT /api/admin/users/{user_id}` | `admin` | Changes user fields/role/session-relevant state. No explicit route-level step-up. |
| 20 | `DELETE /api/admin/users/{user_id}` | `admin` | Deletes a user. No explicit route-level step-up. |
| 21 | `POST /api/admin/users/{user_id}/activation` | `admin` plus explicit step-up code | Activates/deactivates a user and changes effective session validity. |
| 22 | `PUT /api/admin/trader-accounts/{paper_account_id}` | `admin` | Upserts account mapping/metadata. No explicit route-level step-up. |
| 23 | `POST /api/v2/admin/controls/{action_id}` | `admin` | Currently always raises `403`; it constructs an audit ID but does not persist the audit promised by its documentation. It is a non-functional control placeholder. |
| 24 | `POST /api/v2/admin/paper/session-reset` | `admin` plus danger flag and reason | Deletes six Redis keys, overwrites the paper lifecycle file, and appends Redis audit state. Destructive, with no global idempotency or explicit TOTP step-up. |
| 25 | `POST /api/v2/orders/preview` | Optional auth | Computes an order preview; no observed persistence. Invalid auth collapses to anonymous. |
| 26 | `POST /api/v2/orders/paper` | Authenticated and scoped | Submits a paper order into the selected file/SQL repository. This is not a live exchange order. |
| 27 | `POST /api/v2/orders/paper/{order_id}/fill` | Authenticated and scoped | Changes paper-order fill state. |
| 28 | `POST /api/v2/orders/paper/{order_id}/cancel` | Authenticated and scoped | Changes paper-order cancellation state. |
| 29 | `POST /api/v2/backtest/run` | Optional auth | Writes pending job state to Redis and launches a fire-and-forget subprocess. Anonymous callers can consume host resources if ingress permits. |
| 30 | `POST /api/v2/alerts` | Authenticated and trader/paper scoped | Creates an alert in local JSON or SQL. External delivery is disabled in the current contract. |
| 31 | `PUT /api/v2/alerts/{alert_id}` | Authenticated owner/scope | Replaces alert state in local JSON or SQL. |
| 32 | `DELETE /api/v2/alerts/{alert_id}` | Authenticated owner/scope | Deletes alert state in local JSON or SQL. |
| 33 | `POST /api/v2/pipeline/run` | Caller-supplied `X-Role` header through legacy helper | With `dry_run=false`, writes a request/audit and queues a Redis stream. This endpoint is not protected by signed session identity. |
| 34 | `POST /api/v2/mobile/push/register` | Authenticated | Best-effort Redis hash write for a device token; Redis errors are swallowed, so success/failure durability is not strongly reported. |
| 35 | `DELETE /api/v2/mobile/push/{device_token}` | Authenticated | Best-effort Redis hash deletion; Redis errors are swallowed. |

Primary route sources:

- Live gate: `v2/backend/app/api/v1/live_gate.py:877-1551`; runtime writer: `v2/backend/app/services/live_gate/runtime_execution_state.py:19-306`.
- Auth/admin: `v2/backend/app/api/auth_rbac.py:192-639`.
- Admin, order, paper, and backtest contracts: `v2/backend/app/api/v2/admin.py:1233-1455` and `v2/backend/app/api/v2/market_contracts.py:8795-11283`.
- Alerts: `v2/backend/app/api/v2/alerts_contracts.py:73-534`.
- Pipeline: `v2/backend/app/api/v2/pipeline.py` and `v2/backend/app/services/pipeline_control/service.py:475-553`.
- Mobile push: `v2/backend/app/api/v2/mobile.py:2582-2630`.

### 6.1 Dormant state-changing source

`v2/backend/app/api/v1/paper_fill_gate.py:187-230` defines `POST /api/v1/paper-fill-gate/run-burndown`, which starts a CLI process and writes artifacts. Its router is not registered by the current factory, so it is not present in the generated OpenAPI schema and is not externally mounted through this application. Adding the module to the router tuple would expose a public process-spawning mutation unless authentication is added first.

### 6.2 Live-gate documentation mismatch

The module docstring in `v2/backend/app/api/v1/live_gate.py:1-7` says the handlers do not write Redis. That is stale: `/enable` calls the runtime writer, and that writer updates Redis plus files. Source comments must not be used as a live-execution safety control.

## 7. WebSocket surfaces

Seven WebSocket routes are mounted. They include root and V2 aliases for market data, paper activity, and resource streams, plus the enterprise realtime endpoint. Relevant sources are `v2/backend/app/api/v2/market_contracts.py:5957-5962,15183-15268` and `v2/backend/app/api/v2/realtime.py:737-853`.

| Mounted path | Route name | Schema visibility |
|---|---|---|
| `/api/v2/ws/market-data` | `api_v2_market_data_stream` | Not represented by OpenAPI |
| `/api/v2/ws/paper-activity` | `api_v2_paper_activity_stream` | Not represented by OpenAPI |
| `/api/v2/ws/resource` | `api_v2_readonly_resource_stream` | Not represented by OpenAPI |
| `/api/v2/realtime/ws` | `realtime_websocket` | Not represented by OpenAPI |
| `/ws/market-data` | `root_market_data_stream` | Not represented by OpenAPI |
| `/ws/paper-activity` | `root_paper_activity_stream` | Not represented by OpenAPI |
| `/ws/resource` | `root_readonly_resource_stream` | Not represented by OpenAPI |

The observed handlers accept the socket without applying the HTTP JWT/cookie dependency. Capacity controls exist, but identity authentication at the handshake was not found. Protected resource retrieval inside a stream may forward headers/cookies when available, yet the connection itself is not an authenticated principal contract.

The iOS application WebSocket client appends a bearer credential as a `token` query parameter (`v2/mobile/Sources/AIBotV2/Networking/WebSocketClient.swift:96-103`). The backend does not consume that query parameter as authentication. Consequences:

- The token does not authenticate the socket.
- The credential is placed in a URL, increasing exposure through logs, telemetry, crash reports, proxies, and debugging tools.
- Native-client expectations and server behavior are contractually inconsistent.

WebSocket connection counts, history buffers, and related capacity state are process-local. With four Uvicorn workers, a configured limit is effectively applied independently four times unless Redis or another shared coordinator enforces it.

Rebuild rule: define one handshake protocol, preferably an authorization header or short-lived single-use socket ticket; validate it server-side; bind authorization to channel subscriptions; never place long-lived bearer tokens in query strings; and test the protocol through the real ingress proxy.

## 8. Four-worker concurrency model

Uvicorn uses four independent Python processes. They share Redis and the filesystem but do not share Python memory or `threading.Lock` objects.

| State mechanism | Four-worker behavior | Failure mode |
|---|---|---|
| Module/global dictionaries and lists | One copy per worker | A later request can land on another worker and observe different history, cache, metrics, or capacity state. |
| `threading.Lock` in user/revocation/repository objects | Serializes only threads using that exact lock in one process/object | Cross-worker and often cross-instance read-modify-write races remain. |
| Atomic temporary-file replacement | Prevents a reader from seeing a partially written file | Does not prevent lost updates when workers read the same old version and replace it in different orders. |
| Import-created auth secret file | Workers can attempt first-start creation together | Divergent in-memory secrets or startup race if the file/configuration is absent. |
| Redis | Shared across workers | Provides shared visibility, but only operations/scripts designed atomically prevent races. Eviction can remove any key under the current policy. |
| WebSocket counters/caches | Per worker | Effective limits multiply and clients see worker-local state. |
| System-metrics history | Per worker | History depends on which worker answers. |
| AnyIO limiter | 120 tokens per worker | Up to 480 eligible blocking operations, subject to host limits. |

`UserStore` creates object-local locks and rewrites the JSON document through a temporary file (`v2/backend/app/auth/users.py:309-330`). Revocation has the same class of whole-file mutation. Atomic rename is integrity protection, not transaction isolation.

Any change from four workers to one may hide races while reducing capacity; any increase multiplies them. Worker count is therefore part of the data-consistency contract and must appear in load/concurrency tests.

## 9. Persistence and current data ownership

### 9.1 Redis snapshot

The observed Redis DB 0 state on 2026-07-16 was approximately:

| Property | Observed value | Operational meaning |
|---|---:|---|
| Keys | 1,112,280 | Large shared keyspace with mixed responsibilities |
| Keys with expiry | 877,610 | Most, but not all, records expire |
| Memory | 31.18 GiB used of 32 GiB max | Little headroom at the snapshot |
| Eviction policy | `allkeys-lru` | **Any** key, including control/audit/truth state without TTL, can be evicted |
| AOF | Disabled | No append-only durability |
| RDB schedule | `save 900 1` | Snapshot durability only; writes after the latest successful snapshot can be lost |
| Snapshot state | Save in progress; prior status successful | Point-in-time observation, not a durability guarantee |

The static atlas identifies 1,983 Redis key patterns across the repository. Pattern count is not live-key count, but it demonstrates that Redis acts simultaneously as cache, stream/queue, heartbeat registry, audit sink, job store, runtime-control store, and presentation data source.

The combination of near-capacity memory, `allkeys-lru`, and non-AOF persistence means a value that looks durable in code may be evicted or lost after a crash. Redis-backed authorization, runtime gates, paper state, audits, and job lifecycle must each declare whether they are cache, recoverable projection, queue, or source of truth. Those classes require different eviction, TTL, backup, and replay policies.

### 9.2 File and SQL stores

Observed local persistence includes:

| Data | Current mechanism | Concurrency/durability notes |
|---|---|---|
| User records | JSON by default; optional SQL | Whole-document read/replace under process-local locking; SQL store can auto-create schema. |
| JWT revocations | JSON by default; optional SQL | Whole-document replacement; process-local lock; production health reports non-durable. |
| Trader-account metadata | JSON by default; optional SQL | Local production writes are intended to fail closed; repository selection is environment-driven. |
| Alerts | JSON or SQL | Full local collection mutation; external delivery disabled. |
| Paper orders/state | File and/or SQL repository paths plus Redis projections | Ownership varies by endpoint; reset deletes Redis keys and replaces a lifecycle file. |
| Live-gate acceptances | Public/worklog JSON artifacts | Atomic replacement per file, but multi-file workflow is not one transaction. |
| Runtime live-execution state | Allowlisted Redis keys plus public/worklog JSON | A partial failure can produce disagreement between media unless all writes and reconciliation are audited. |
| Pipeline requests | Redis stream/audit/latest-request keys | Shared, but authorization uses an unsigned role header. |
| Backtest jobs | Redis plus subprocess | Parent request success does not imply subprocess completion. |
| Mobile push registration | Redis hash, best effort | Exceptions are swallowed; caller cannot rely on durable acknowledgement. |

Current file observations, without reading secret values:

- `v2/.env.local` is mode `0664` and contains credential material. It is too broadly readable/writable for a secret-bearing file.
- Local auth users, revocation, and trader-account JSON files were also mode `0664`.
- The process secret file was mode `0600`.
- `v2_paper_trading.db` existed as a zero-byte mode-`0644` file at the snapshot; its presence is not evidence of an initialized database.

### 9.3 Schema management gap

The Alembic directory has only `.gitkeep`. `v2/backend/migrations/README.md:1-23` describes a migration harness with zero migrations, and `v2/backend/migrations/env.py:1-20` has no populated application metadata. Meanwhile optional auth, alert, and trader repositories can create their own tables. This produces environment-specific schema creation outside a reviewed migration history.

Rebuild rule: one owner must define each table; migrations must be versioned, applied before service start, and reversible/tested. Application code must not silently invent production schema.

## 10. React/Vite web client and static delivery

### 10.1 Build and route graph

`v2/frontend/package.json:6-27` defines the frontend build as TypeScript project build, Vite build, and pruning. `v2/frontend/src/main.tsx:1-49` mounts React in strict mode and registers the service worker. `v2/frontend/src/App.tsx:20-29` wraps the application in authentication and realtime providers, and `v2/frontend/src/router.tsx:12-43` builds lazy route shells from the route registry.

`v2/frontend/vite.config.ts:7-116` deliberately disables Vite's normal public-directory copy and copies only curated entries:

```text
api/
brand/
favicon files
icons/
manifest files
service-worker.js
```

It proxies only:

```text
/api  -> backend HTTP
/ws   -> backend WebSocket
```

It does not proxy `/operator_runtime` or arbitrary root-level `v2_*` artifact paths. The frontend public tree was about 12 GiB while the built `dist` tree was about 3.2 MiB, consistent with selective copy rather than full publication.

### 10.2 Two static-serving paths

There are two possible ways to serve the UI:

1. Vite preview on port 5173, which uses the proxy and curated build behavior above.
2. FastAPI on port 8000, which can mount built assets and an operator-runtime directory and can answer a SPA catch-all.

They are not interchangeable. A local probe of an operator-runtime JSON path returned `application/json` through port 8000 but returned the Vite HTML fallback through port 5173. Therefore one of these must be true in an externally working environment:

- Cloudflare path rules route operator-runtime paths directly to the backend;
- a different external origin serves them;
- the affected UI paths do not work externally; or
- an unrecorded layer rewrites the requests.

The Cloudflare route configuration is not locally available, so this cannot be reconstructed from the repository alone.

### 10.3 Realtime client behavior

`v2/frontend/src/lib/realtime/resourceClient.ts:65-229` keeps a last-known-good payload for at most ten minutes in session storage, fetches bootstrap data with browser credentials, and constructs WebSocket URLs. The realtime provider performs reconnect/fallback behavior on an approximately 15-second cadence (`v2/frontend/src/lib/realtime/RealtimeProvider.tsx:51-224`).

This creates three possible data paths for a visible page:

```text
WebSocket resource -> HTTP fallback -> session last-known-good
```

Every screen-level field must declare which path supplied it and preserve its source timestamp. A cached presentation value must not be relabeled with a new `generated_at`, and transport receipt time must not replace `event_time`, `available_at`, `feature_cutoff`, `decision_time`, or `execution_time`.

### 10.4 Service worker

Production entry code registers `service-worker.js` through `v2/frontend/src/pwa/registerServiceWorker.ts:1-18`. The runtime service worker in the public tree caches static `GET` resources and uses network-first navigation behavior; it does not intentionally cache mutation/API traffic. A separate TypeScript `service_worker.ts` says service workers are disabled, but it is not the registered production artifact.

Playwright sets `serviceWorkers: "block"` (`v2/frontend/playwright.config.ts:21-24`), so current browser tests do not validate the production service-worker path, its upgrade behavior, or stale-asset recovery.

### 10.5 Browser authentication gaps

- Main auth calls use `credentials: include`, which matches the cookie contract.
- The browser does not intentionally retain the returned bearer token.
- A legacy page still reads a local-storage token name, creating a second, likely empty token convention.
- Query/session-storage roles affect page shells only and can be user-selected.
- The frontend's CSRF field remains null.
- A local integration test uses cookie name `session`, while the backend uses `alphaforge_session`; that test cannot prove real backend authentication.

## 11. Swift mobile, watch, core, and CLI clients

### 11.1 Package boundaries

`v2/mobile/Package.swift:1-90` uses Swift 5.9. Core and CLI targets are cross-platform; iOS and watch targets are conditional, with iOS 17 and watchOS 10 deployment targets. `v2/mobile/project.yml` supplies the Apple project definition.

The important distinction is:

| Client layer | Token storage | Network model |
|---|---|---|
| iOS application | Keychain | Actor-based `APIClient`, bearer header, strict Codable decoding |
| Shared Core/CLI | JSON token file | Shared API models/client and command-line use |
| Watch | Synchronized dashboard/positions/alerts | No observed direct trade-action transport in the watch sync center |

### 11.2 iOS token and API behavior

`v2/mobile/Sources/AIBotV2/Networking/APIClient.swift:3-93` uses bearer authorization, 15/30-second request timing, `GET`/`POST`/`DELETE`, and strict decoding. `v2/mobile/Sources/AIBotV2/Networking/APIEndpoints.swift:3-128` catalogs API, static operator, and WebSocket paths.

The iOS app persists the token with `v2/mobile/Sources/AIBotV2/Auth/AuthManager.swift:4-45` and `KeychainHelper.swift:40-55`. The Keychain item uses an after-first-unlock, device-only accessibility class, which prevents migration to another device backup but makes it available after the first device unlock.

The initial iOS login model now expects backend user key `id`. Session restore remains incompatible: the app decodes `/api/auth/me` as a flat `{id,email,role,...}` user object, while the backend returns `{user: {...}, session_security: {...}}`. A relaunch/restore decode failure causes the app to delete the stored token (`v2/mobile/Sources/AIBotV2/Auth/AuthManager.swift:80-130`).

### 11.3 Core/CLI incompatibility and storage risk

The shared Core authentication manager expects `user_id` and a flat `/me` response (`v2/mobile/Sources/AIBotV2Core/AuthManager.swift:68-105`). The backend emits `id` and wraps `/me`. Core/CLI login and restore are therefore contractually incompatible with the current backend unless another adapter path exists.

`v2/mobile/Sources/AIBotV2Core/TokenStore.swift:3-64` stores the bearer token in a plaintext JSON file. It does not enforce restrictive file permissions. Its comment says Apple delegates to Keychain, but the Core singleton itself is file-backed. On CLI/macOS/Linux usage, token confidentiality depends on directory defaults and host permissions rather than a credential store.

The shared default base URL is localhost port 5173 (`v2/mobile/Sources/AIBotV2Core/TokenStore.swift:67-76`), whereas the iOS application model has a public HTTPS default (`v2/mobile/Sources/AIBotV2/Models/APIModels.swift:1661-1667`). Build target and configuration source therefore determine the server, and must be included in release provenance.

### 11.4 WebSocket contract failure

As described in Section 7, the shared Swift socket puts the token in a query parameter, while the server does not authenticate it. This is both a functional mismatch and a secret-exposure pattern.

### 11.5 Mobile test boundary

Only one Swift test source file was found. `AIBOT_SPM_EXCLUDE_APP_TARGETS=1 swift test --package-path v2/mobile` passed 32 Core tests on Linux, but explicitly excluded the iOS/watch application targets. It did not compile the iOS `AuthManager`/Keychain path or exercise login, `/me`, or WebSocket compatibility against the real FastAPI app. A passing Core suite is not evidence that the iOS session flow works.

## 12. Cloudflare external state

The Cloudflare tunnel is a material, non-repository component of the system:

- `cloudflared.service` is active.
- No corresponding `/etc/cloudflared` or user-home tunnel configuration was found locally.
- The systemd unit embeds a tunnel bearer credential directly in `ExecStart`; it is consequently present in unit metadata and process arguments. The value is intentionally omitted here.
- Hostname, DNS, path split, access policy, TLS mode, origin selection, and failover configuration reside in the Cloudflare control plane and were not exportable from local files.

Immediate security requirement: rotate the exposed tunnel credential, remove it from command-line arguments, and supply it through a systemd credential or a root-restricted credential file supported by the deployment design.

Rebuild requirement: export a sanitized, versioned ingress specification containing:

- every hostname and DNS record;
- every path-to-origin rule, especially `/api`, `/ws`, `/operator_runtime`, root `v2_*` artifacts, assets, and SPA fallback;
- Cloudflare Access/authentication policy;
- TLS mode and origin certificate expectations;
- WebSocket enablement and timeouts;
- caching/bypass behavior for API, JSON runtime artifacts, and service-worker files;
- forwarded headers and the trusted-proxy chain;
- tunnel ownership, credential rotation, and recovery steps.

Uvicorn trusts proxy headers only from `127.0.0.1`. The exact cloudflared/Vite/backend hop sequence must be tested, because a change in origin routing can change client IP, scheme, host, cookie, redirect, and audit behavior.

## 13. Observability, logs, tests, and CI

### 13.1 Runtime observability

`v2/backend/app/api/v2/system_metrics.py:1-6,195-269` exposes read-only host/GPU/Redis observations. Its history ring is Python process memory, so four workers can return different histories. A separate closed-loop component can render Prometheus text, but the active FastAPI factory does not establish a comprehensive standard metrics/export/tracing pipeline.

`v2/backend/app/cli/v2_system_observability_status_publisher.py:1-12,28-63` publishes status JSON and a Redis heartbeat. It explicitly does not alert or restart services. Operational logs are split between the systemd journal and append files under the repository worklog tree. No end-to-end Sentry/OpenTelemetry-style request trace was found in the active API path.

Minimum missing correlation contract:

```text
request_id
authenticated_subject
authorization_decision
route and operation_id
worker/process identity
source payload IDs
Redis/file/SQL mutation IDs
subprocess/job ID
event_time / available_at / decision_time / execution_time
result and latency
```

Sensitive headers, cookies, query tokens, passwords, and credential fields must be redacted before any log or trace export.

### 13.2 Test inventory and observed results

Repository file counts at the snapshot were 1,446 backend `test_*.py` files, 56 frontend test files, and one Swift test file. These are inventory counts, not equivalent coverage units.

Focused observed results:

| Command scope | Result | Meaning |
|---|---|---|
| Backend middleware-order contract | 2 failed, 1 passed | Test expects ten middleware layers and omits installed CORS. |
| Frontend TypeScript typecheck from `v2/frontend` | Passed | Static typing passes for the current frontend checkout. |
| Swift Core tests with app targets excluded | 32 passed | Does not validate iOS/watch compilation or real API compatibility. |
| Root-level accidental npm typecheck | Failed with missing root `package.json` | The frontend command must run from `v2/frontend`; this is not a product defect. |

### 13.3 CI coverage

Only two GitHub workflows were found, both Apple-oriented:

- `.github/workflows/nervyx-ios-macos-validation.yml:9-17,60-140` runs on mobile-related paths and performs Swift Core/simulator validation.
- `.github/workflows/ios-simulator-screenshots.yml:3-19` is manually triggered for screenshot validation.

No GitHub workflow was found that makes backend tests, frontend typecheck/build/Playwright, OpenAPI drift, migration validation, secret scanning, or deployment manifest checks mandatory for repository changes.

`v2/Makefile:12-89` defines local CI-like targets. `v2/ops/ci/secrets_scan.sh:14-24` exits successfully when `gitleaks` is absent. `gitleaks` was absent in the observed environment, so the advertised secret scan is fail-open.

Playwright blocks service workers, and several browser tests mock authentication. The local integration cookie name differs from the backend cookie name. Existing tests therefore do not prove the production browser auth, service-worker, Cloudflare path-routing, or mobile session contracts.

## 14. Contract ledger

These contracts must be treated as versioned interfaces when changing or rebuilding the system.

### 14.1 HTTP/auth contract

| Contract | Current value | Consumers |
|---|---|---|
| API documentation | `/api/docs`, generated OpenAPI | Operators, generated clients, tests |
| Browser cookie | `alphaforge_session`, HttpOnly, secure in production/config, SameSite lax default | React auth provider, backend dependencies, ingress |
| Native auth | Bearer token in `Authorization` header | iOS, Core/CLI HTTP client |
| Token precedence | Bearer before cookie | All mixed browser/tool callers |
| Login body | Credential payload | React, iOS, Core/CLI |
| Login response | Includes `access_token` plus user data | Native clients; browser ignores token intentionally |
| `/api/auth/me` response | Wrapper with `user` and `session_security` | React compatible; current Swift restore models incompatible |
| Public user ID key | `id` | React/iOS current login; Core expects different name |
| Optional auth | Invalid and absent token both become anonymous | Preview, backtest, logout and any future optional route |
| OpenAPI security | Undeclared | Generated clients cannot derive authentication |

### 14.2 Static/realtime contract

| Contract | Current value | Risk |
|---|---|---|
| Vite API proxy | `/api` only | Other root JSON paths do not reach backend through local Vite |
| Vite WebSocket proxy | `/ws` only | Non-`/ws` socket aliases may require external route rules |
| Operator runtime | Backend can mount; Vite does not proxy/copy it as a whole | External correctness depends on Cloudflare/unrecorded routing |
| Browser realtime fallback | Socket -> HTTP -> ten-minute session LKG | Stale presentation requires explicit timestamps/state |
| Native socket auth | Token query parameter | Server ignores it; token exposure risk |
| Service worker | Registered production JS; blocked in Playwright | Production cache lifecycle is not covered by browser tests |

### 14.3 Data/time contract

API schemas and UI adapters must keep these fields semantically separate:

| Field | Required meaning |
|---|---|
| `event_time` | Time the market/business event occurred |
| `ingested_at` | Time this system received the event |
| `available_at` | Earliest time the complete datum was usable |
| `generated_at` | Time the payload/projection was produced |
| `feature_cutoff` | Latest source event included in a feature set |
| `decision_time` | Time a model/strategy decision was made |
| `execution_time` | Time an execution action occurred |

An API cache, WebSocket relay, service worker, or UI projection must not overwrite source timestamps with receipt/render time. A rebuild must enforce `available_at <= decision_time`, must exclude unfinished higher-timeframe candles, and must preserve MASA/PPO cutoff ordering wherever those objects cross this component boundary.

## 15. Change-impact matrix

Use this matrix before even a small change. The listed downstream checks are the minimum, not an exhaustive substitute for repository search.

| Proposed change | Directly affected areas | Required checks before merge/deploy |
|---|---|---|
| Rename an API path/prefix | FastAPI router, Vite proxy, Cloudflare path rules, React endpoint registry, Swift endpoints, tests, static atlas | Generate OpenAPI diff; search all clients; probe both ports and public hostname; test SPA fallback and WebSockets. |
| Change login or `/me` JSON | `auth_rbac.py`, React auth types/provider, iOS `AuthManager`, Core `AuthManager`, CLI, fixtures | Contract tests against real app for browser+iOS+Core; token/cookie negative tests; migration/version plan. |
| Change cookie name/flags/domain | Backend security, React credential mode, Cloudflare scheme/host, integration tests, logout/refresh | Cross-origin and CSRF tests; public-host login/logout/refresh; secure-cookie behavior behind proxy. |
| Change JWT claims/secret/issuer/audience/TTL | Token creation/verification, revocation store, mobile/Core clients, active sessions, auth health | Rotation/overlap plan; clock-skew tests; revocation and session-version tests; no token logging. |
| Change role names/hierarchy | Backend dependencies, frontend RBAC shells, pipeline legacy helper, user records, mobile display, admin tools | Authorization matrix for every mutating route; eliminate header-only role path; migration for stored roles. |
| Add or reorder middleware | `main.py`, middleware package, CORS/preflight, exception behavior, route auth | Fix exact-order contract; security-control tests; latency/load tests; confirm outer/inner semantics. |
| Change worker count | systemd, in-memory caches/counters, JSON locks, thread-pool multiplication, DB/Redis pools | Multi-process race tests; capacity test; shared-state audit; connection-limit recalculation. |
| Change JSON store code | Users, revocations, alerts, trader accounts, paper/live artifacts | Cross-process lost-update tests; crash recovery; permissions; schema/version validation; backup/restore. |
| Enable SQL backend | Repository selectors, schema, Alembic, connection pool, service startup | Create reviewed migrations; migrate/verify data; rollback; transaction isolation; four-worker load. |
| Change a Redis key/TTL/serializer | Publishers, API readers, UI realtime, timers, alerts, audit/recovery tooling | Producer/consumer index; dual-read/write migration; memory/eviction impact; backup/replay; stale-key cleanup. |
| Change Redis eviction/durability | Every Redis consumer and timer | Classify keys; isolate durable state; capacity test; RDB/AOF recovery drill; alert thresholds. |
| Change frontend public/build copy list | Vite config, service worker, operator paths, `dist`, Cloudflare caching | Build manifest diff; direct URL probes; offline/update tests; public-host cache purge plan. |
| Change WebSocket route/auth | Backend socket handlers, Vite proxy, Cloudflare WS policy, React realtime, Swift client | Authenticated handshake tests; subscription authorization; reconnect/expiry; no query secrets; capacity across workers. |
| Change live-gate handler/runtime writer | Live-gate artifacts, Redis allowlist, worklog/public outputs, release mode, execution consumers | Requires explicit operator approval before code edit; fail-closed tests; atomicity/reconciliation; audit IDs; prove no unintended order path. |
| Change paper reset/order repository | Paper Redis/file/SQL state, lifecycle UI, audit, simulations | Requires explicit task scope; state-machine tests; idempotency; recovery snapshot; confirm no live order path. |
| Change Cloudflare tunnel/origin | Public HTTP/WS/static/auth behavior, trusted proxy, cookies, client IP, caching | Export config first; staged hostname tests; rollback; credential rotation; test all path classes. |
| Change Swift model | iOS, Core/CLI, watch sync, backend schema | Compile all Apple targets; real contract fixture; backward-compatible decoding; Keychain/file migration. |

### 15.1 Function-level review checklist

For any modified API/auth/storage/web/mobile function:

- Identify every caller with `rg`, including lazy imports, router registration, timers, scripts, React registries, Swift endpoint constants, and tests.
- Identify every request/response model and every serialized key that crosses the function boundary.
- Determine whether the function reads or writes Redis, SQL, JSON, public artifacts, worklogs, cookies, headers, subprocess state, or in-memory globals.
- Determine whether the state is worker-local or shared and whether the operation is atomic across four workers.
- Record authorization dependency, role, ownership/scope check, step-up requirement, CSRF posture, idempotency posture, and rate-limit posture.
- Preserve `event_time`, `ingested_at`, `available_at`, `generated_at`, `feature_cutoff`, `decision_time`, and `execution_time` semantics.
- For any order-shaped or live-control function, trace the path to the position state machine and exchange adapter before editing. No live execution behavior may change without explicit operator approval.
- Update OpenAPI/route-count snapshots, contract tests, client types/models, deployment manifests, and operator runbooks together.
- Test negative cases: missing auth, invalid token, wrong role, wrong owner, stale session version, revoked JTI, malformed body, duplicate request, backend unavailable, Redis eviction/error, partial file/SQL failure, and worker race.
- Verify secret redaction and file permissions; never put tokens in URLs, process arguments, artifacts, or logs.

## 16. Rebuild requirements

A faithful copy of the current system requires the following artifacts and decisions. A safer replacement must additionally close the listed gaps.

### 16.1 Reproducible application definition

1. Pin the source revision used by both backend and frontend services; do not run production from a mutable dirty checkout.
2. Generate and archive OpenAPI plus a separate WebSocket contract for every release.
3. Generate a mounted-route manifest that records router source, prefix composition, method, auth dependency, scope/ownership rule, mutation class, persistence targets, and clients.
4. Treat dormant decorated routes as non-deployed until explicit registration review.
5. Remove import-time secret creation and supply deterministic managed credentials before workers start.

### 16.2 Unified security model

1. Replace the unsigned `X-Role` pipeline check with the signed session/JWT identity system.
2. Declare auth schemes and per-operation security in OpenAPI.
3. Implement and test CSRF protection for cookie-authenticated mutations.
4. Implement real IP allowlisting, throttling, idempotency, approval, lineage, and database error controls, or remove their scaffold names from the security story.
5. Authenticate and authorize WebSocket handshakes/subscriptions.
6. Require explicit step-up policy for destructive admin and live-control mutations.
7. Decide whether public registration and anonymous backtest spawning are intended; otherwise gate them.
8. Separate browser cookie sessions from native token issuance or document one intentional combined flow.
9. Make session health capable of reporting and achieving a real durable production-ready state.

### 16.3 Transactional state and concurrency

1. Move mutable identity, revocation, alert, trader, paper, and approval state requiring consistency into a transactional shared store.
2. Add reviewed Alembic migrations and prohibit application-side production schema invention.
3. Use optimistic versions, transactions, or distributed locks where cross-worker coordination is required.
4. Make live runtime state a single versioned transaction or implement an explicit reconciliation journal across Redis and files.
5. Classify every Redis key family as cache, projection, queue/stream, lease/heartbeat, audit, or source of truth.
6. Separate non-evictable control/durable state from evictable caches; set retention, memory alerts, backup, restore, and replay contracts.
7. Validate worker/thread/pool capacity together and test with multiple processes.

### 16.4 Web and ingress reproducibility

1. Choose one canonical static-serving topology and eliminate ambiguous Vite-versus-FastAPI path behavior.
2. Version the exact build manifest and map every public runtime artifact path.
3. Export Cloudflare DNS, hostname, path routing, Access, cache, TLS, and WebSocket configuration in a secret-safe form.
4. Rotate the current tunnel credential and move it out of process arguments.
5. Add public-host synthetic tests for HTML, assets, `/api`, auth cookie lifecycle, `/ws`, `/operator_runtime`, and root artifact paths.
6. Test the actual service worker in at least one browser suite and validate upgrade/rollback behavior.

### 16.5 Client compatibility

1. Generate or validate React and Swift models from one versioned API contract.
2. Fix `/me` wrapper and `id`/`user_id` mismatches across iOS and Core/CLI.
3. Replace Core plaintext token storage with OS credential storage or at minimum restrictive permissions and an explicit threat model.
4. Replace query-string WebSocket tokens with the server-supported authenticated handshake.
5. Compile and test iOS/watch targets in CI, not only Core with app targets excluded.
6. Add real-server contract tests for login, refresh, logout, restore, revocation, role changes, WebSocket expiry/reconnect, and public ingress behavior.

### 16.6 Observability and delivery controls

1. Add structured request/mutation/job correlation across all workers and persistence media.
2. Export health, latency, error, Redis pressure/eviction, worker saturation, WebSocket, auth rejection, and queue/subprocess lifecycle metrics.
3. Alert on production-readiness degradation, Redis capacity, failed snapshots, mutation divergence, authentication-store fallback, and failed publishers.
4. Add backend, frontend, OpenAPI drift, migration, multi-worker concurrency, service-worker, secret scan, and deployment-manifest workflows to CI.
5. Make secret scanning fail closed when its scanner is absent.
6. Prohibit deployment when focused security/contract tests fail.

## 17. High-priority current risks

| Priority | Risk | Why it matters |
|---:|---|---|
| P0 | Cloudflare tunnel credential is present in service/process arguments | Rotate immediately; it can grant ingress control and is exposed beyond a restricted credential file. |
| P0 | `/api/v2/pipeline/run` trusts caller-supplied `X-Role` | A reachable unauthenticated caller can request non-dry-run Redis queue mutations. |
| P0 | Live-gate enable is outside the live-block prefix and writes runtime state | Current release mode disarms it, but the safety boundary depends on route dependencies/body workflow and release configuration rather than the global guard. |
| P1 | Redis is near its memory ceiling with `allkeys-lru` and AOF disabled | Control, audit, job, and truth-like keys can be evicted or lost after the last snapshot. |
| P1 | WebSockets are accepted without the intended identity contract | Data/channel access and capacity are not bound to an authenticated principal; Swift token use is ineffective and unsafe. |
| P1 | Four workers mutate JSON under process-local locks | User, revocation, alert, and metadata updates can be lost even when each file replacement is atomic. |
| P1 | OpenAPI declares no authentication | Generated clients and security tooling cannot see actual protection requirements. |
| P1 | Nine named middleware controls are scaffolds | Operators and reviewers can overestimate enforcement. |
| P1 | Swift login/session models disagree with backend response wrappers/keys | Native restore and Core/CLI auth fail despite passing isolated Core tests. |
| P1 | Cloudflare origin/path routing is not reconstructible locally | A rebuild cannot reproduce public static/API/WebSocket behavior from repository/system files alone. |
| P2 | Cookie mutations have no explicit CSRF verification | SameSite is the principal mitigation and can be invalidated by topology/policy changes. |
| P2 | SQL stores can create schema outside Alembic | Environments can drift with no deterministic upgrade/rollback history. |
| P2 | CI omits backend/frontend/deployment enforcement and secret scan fails open | Regressions seen in focused tests are not mandatory merge blockers. |

## 18. Known limits of this snapshot

- No secret value was read into this document; credential validity and external account ownership were not tested.
- Cloudflare control-plane configuration was not available locally, so public hostname/path behavior remains an external dependency.
- Redis counts and memory are point-in-time values and will change continuously.
- The static atlas count includes definitions/references and cannot replace dynamic route enumeration.
- Local probes and focused tests do not substitute for a staged public-host exercise through Cloudflare.
- Linux Swift tests excluded Apple application targets; iOS/watch conclusions are source-contract findings, not simulator execution results in this audit.
- The document describes current API/runtime behavior but does not authorize changes to live execution, order submission, strategy, PPO, MASA, or risk logic.

## 19. Secret-safe verification commands

The following commands reproduce the core non-secret checks when run from the repository root. Do not add commands that print environment files, tokens, cookies, Authorization headers, process arguments containing credentials, or secret-file contents.

```bash
PYTHONPATH=v2/backend .venv/bin/python - <<'PY'
from collections import Counter
from app.main import create_app

app = create_app()
schema = app.openapi()
methods = Counter()
for item in schema["paths"].values():
    for method in ("get", "post", "put", "patch", "delete"):
        if method in item:
            methods[method.upper()] += 1
print("paths", len(schema["paths"]))
print("operations", sum(methods.values()))
print("methods", dict(methods))
print("security_schemes", schema.get("components", {}).get("securitySchemes", {}))
PY

PYTHONPATH=v2/backend .venv/bin/pytest -q \
  v2/backend/tests/contract/test_middleware_order.py

(cd v2/frontend && npm run typecheck -- --pretty false)

AIBOT_SPM_EXCLUDE_APP_TARGETS=1 swift test --package-path v2/mobile

ss -ltnp | rg ':(8000|5173)'

git status --short
```

For deployed verification, use sanitized systemd properties and Redis statistics rather than dumping complete unit environments or command lines. Record only configuration names, counts, modes, and redacted paths needed for reproducibility.
