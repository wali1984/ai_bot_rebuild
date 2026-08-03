# Final Web, Backend, and iOS Product Audit — Refreshed P0 Preflight

Timestamp: `2026-07-23T04:13:13Z` (`2026-07-23T00:13:13-04:00`)

This is a bounded refresh of P0. It reuses the proven route/page-family work
and does not regenerate the system atlas or rerun a completed visual audit.

## Evidence counts

| Evidence | Count |
|---|---:|
| Concurrent agents | 2 maximum; 1 primary + 1 read-only specialist |
| Dirty paths frozen | 159 |
| Earlier held paths still dirty | 155 / 155 |
| Newly classified dirty paths | 4 |
| Bounded runtime URL targets | 26 |
| Backend targets | 19 |
| Managed frontend/proxy targets | 6 |
| Duplicate-preview targets | 1 |
| Bounded WebSocket connections | 4 / 4 passed |
| Managed website services | 2 / 2 active; 0 restarts |
| AI-bot service unit files | 130 |
| Loaded services | 113 |
| Loaded active / inactive / activating / failed | 68 / 43 / 2 / 0 |
| Supervisor components | 50 = 37 OK + 12 held + 1 not installed |
| Redis commands | 1 `PING`; 0 key scans |
| OpenAPI paths / operations | 194 / 198 |
| Codemagic workflows inspected | 2 |
| Product defects proved by P0 | 6 |
| Screenshots captured in P0 | 0 |
| Builds run in P0 | 0 |
| Files/services/Redis/runtime state changed during discovery | 0 |

## Repository and ownership state

- Branch: `codex/pipeline-trust-refresh`
- HEAD: `23139acdd60f412691b5fdb05ead1e5a7a012c6a`
- Upstream: `origin/codex/pipeline-trust-refresh`
- Ahead / behind: 9 / 0
- Working tree: 96 modified, one deleted, 62 untracked; 159 total
- Refreshed exclusion set:
  [`FINAL_PRODUCT_AUDIT_HOLD_LIST_20260723T041313Z.md`](./FINAL_PRODUCT_AUDIT_HOLD_LIST_20260723T041313Z.md)
- Task-list SHA-256 at inspection:
  `2a2f76282f1801161005fff42c03392cbc260af615b5c162eac0a8039ab7eb7b`
- Recent product-audit commits at HEAD: nine commits from `ab18cf6363`
  through `23139acdd6`.
- Commissioned trainer runtime release: `974caa6c26`; evidence/docs commits:
  `1272d1653b` and `a8715a7254`. These are pushed on
  `codex/trainer-commission-integration-20260722` and are not silently merged
  into this dirty branch.

## Runtime proof

### Managed web/backend

- Frontend service: active/running, main PID `2527044`, listener PID `2527061`,
  `NRestarts=0`, port 5173.
- Backend service: active/running, main PID `2369730`, four Uvicorn workers,
  `NRestarts=0`, port 8000.
- Redis listens on loopback port 6379 and returned `PONG`.
- Frontend `/`: HTTP 200.
- Backend `/`, `/health`, `/api/health`, `/docs`, and `/openapi.json`: 5/5 HTTP
  200.
- Four bounded WebSocket probes returned their first frame through direct and
  frontend-proxied realtime/trainer endpoints: 4/4 passed.
- No iOS, Xcode, simulator, or mobile app process was running.

### Duplicate runtime

An unmanaged Vite preview remains on port 4174. Its five-process tree is owned
by a transient VS Code scope rather than the managed frontend unit. Its HTML is
byte-identical to port 5173 (2,433 bytes; SHA-256
`42b7bfeeabdb86111e1a2c77cbef368a03cdc2f349fea6038e146038fabe9d4e`).
It was not stopped because P0 is read-only.

### Service classification

The supervisor's 50 components classify as 37 `OK`, 12
`SKIP_DELIBERATELY_STOPPED`, and one `SKIP_NOT_INSTALLED`, with zero restart in
the captured sweep. The 12 holds are continuous offline trainer, trainer
checkpoint evidence, cascade context, adaptive capital productivity, edge
replay, continuous edge guardian, strategy supply, agent supervisor,
worker-porting orchestrator, parallel scheduler, Codex watchdog, and the
production-replacement guard. The missing unit is the out-of-sample evidence
producer.

The commissioned profiled feature publisher and CUDA trainer are separately
active on immutable code SHA `974caa6c26`; this does not prove routeable
predictions or paper candidate supply. Current paper truth still reports zero
exploration candidates and guardian-halted entry admission.

## Authentication and API truth

- `/api/auth/health`: HTTP 200, but reports local-file stores,
  `production_ready=false`, partial session security, and degraded data
  quality.
- Unauthenticated `/api/auth/me` and `/api/v2/mobile/admin/summary`: 2/2 HTTP
  401.
- The retained 24-hour trader/admin tokens are expired. The local one-time
  password artifact did not authenticate any of four active accounts; current
  positive authentication is therefore **not proved**. No password, user,
  secret, or auth-store state was changed.
- OpenAPI exposes 194 paths/198 operations but declares zero security schemes
  or per-operation security entries, despite working runtime 401 enforcement.

## Live/order/leverage/margin proof

The canonical `/api/v2/live-gate/status` response proved:

- `live_gate=blocked_human_only`
- `live_blocked=true`
- `live_submit_allowed=false`
- `operator_approved=false`
- `live_symbols=[]`
- `execution_live_symbols=[]`
- `order_submitted=false`
- `test_order_submitted=false`
- `leverage_mutated=false`
- `margin_mutated=false`
- `places_real_order=false`
- `routes_to_live=false`
- `conflict_check=no_conflict_release_mode_blocked`

The risk contract independently reports all seven exchange-mutation flags
false. The live-canary contract reports `dry_run=true`, `live_enabled=false`,
zero live symbols, no real-order attempt/submission, no leverage change, no
margin-mode change, and no exchange-order write.

## P0 defect register

1. **P0-D001 — stale live-symbol projection:** the frontend-visible
   `live_gate_runtime_state.json` marks its source 3,742,221 seconds stale but
   still promotes six June-era symbols (`BNBUSDT`, `BTCUSDT`, `ETHUSDT`,
   `PAXGUSDT`, `XAUTUSDT`, `ZECUSDT`) while the canonical live-gate endpoint
   correctly returns empty lists. Safety remains blocked; display truth is
   wrong.
2. **P0-D002 — contradictory Redis health:** raw loopback Redis returned
   `PONG`, while `/api/v2/realtime/health` reports
   `redis_available=false` with `redis_check=cached_nonblocking`.
3. **P0-D003 — duplicate frontend:** unmanaged port-4174 Vite preview duplicates
   the managed port-5173 service.
4. **P0-D004 — OpenAPI auth omission:** runtime rejects protected requests, but
   the generated schema declares no security schemes or operation security.
5. **P0-D005 — authentication readiness:** auth is degraded/non-production and
   a fresh positive login cannot currently be reproduced from retained local
   operator artifacts.
6. **P0-D006 — Codemagic artifact mismatch:** the Linux workflow builds debug
   but publishes `.build/release/aibot`; the configured artifact is absent while
   the debug binary exists. The iOS workflow has no test step, and native
   archive/signing remains unproved locally.

No defect was fixed in P0. Each belongs to a later scoped family; none permits
changing a held engine, live authority, or operator account.

## iOS/Codemagic configuration

- Native iOS base URL: `https://dashboard.wajidali.us`, persisted in Keychain.
- Core/CLI base URL: `http://127.0.0.1:5173`.
- WebSocket schemes derive correctly from HTTP/HTTPS.
- iOS scheme: `AIBotV2`.
- Bundle ID: `com.wali1984.aibot-v2`.
- Codemagic integration name: `ASC_API_KEY`.
- iOS workflow: manual, three artifact paths, zero test scripts.
- Linux workflow: push and pull request for all branches, core tests present,
  but its release artifact does not match its debug build command.

## Sequencing decision

The operator's RTX 5080/Ryzen 9950X/128-GiB tuning and full web/iOS truth audit
are recorded as a regular follow-on task. Hardware changes, latency tuning,
page-family edits, and repeated visual sweeps remain deferred until the active
core configuration is complete and tested. Existing 284/284 screenshot-family
evidence will be reused; no already-proved audit will be rerun except the final
regression.

Immediate core next slice: determine whether the held legacy trainer-checkpoint
evidence publisher can consume the commissioned non-promotable candidates
without falsely promoting or serving them. Release remains prohibited until
the code, contract tests, and authority flags prove that boundary.
