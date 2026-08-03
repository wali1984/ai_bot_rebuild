# Final Web, Backend, and iOS Product Audit — Preflight

Timestamp: 2026-07-21T23:07:28Z (2026-07-21T19:07:28-04:00)

## Quantified repository state

- Branch: `codex/pipeline-trust-refresh`
- HEAD: `f06277824efacb58ac5f83f1d42eca4a56adabe8`
- Upstream: `origin/codex/pipeline-trust-refresh`
- Ahead / behind: 0 / 0
- Remote: `https://github.com/wali1984/ai_bot_rebuild.git`
- Pull request: #1, draft, open, base `master`, 687 commits, merge state `UNSTABLE`
- Pre-existing dirty paths: 155
  - Modified: 93
  - Deleted: 1
  - Untracked: 61
  - Publisher/native-ingestor hold: 35
  - Other concurrent or owner-unproven hold: 120
- Dirty categories: docs 13; scripts 2; tools 3; backend production 46; backend tests 59; mobile 3; `claude_worklog` 27; other 2.
- Exact exclusion set: [FINAL_PRODUCT_AUDIT_HOLD_LIST_20260721T230728Z.md](./FINAL_PRODUCT_AUDIT_HOLD_LIST_20260721T230728Z.md)

## Edit boundary

Safe independent areas, subject to a fresh `git status` before each edit:

- New files beneath `claude_worklog/codex/FINAL_PRODUCT_AUDIT_*`.
- Clean tracked files beneath `v2/frontend`.
- Clean tracked API-projection files beneath `v2/backend/app/api`, but only for a proven projection defect and never to alter engine behavior.
- Clean targeted frontend/backend tests.
- Clean `codemagic.yaml` and root `.github/workflows` files during their dedicated build-integration slice.

Held:

- Every one of the 155 pre-existing dirty paths.
- All 23 service/timer boundaries and 38 Redis patterns listed in the hold file.
- All publisher, native-ingestor, trainer, strategy, risk, allocator, paper-lifecycle, and provenance assumptions represented by those paths.
- The three untracked iOS paths: `DerivativesViewModel.swift`, `MarketsViewModel.swift`, and `MarketSymbolDetailView.swift`.

No `git add -A` is permitted. Audit commits must stage exact new/clean paths only.

## Process and port evidence

- Redis server processes: 1
- Frontend Vite preview Node processes on 5173: 1
- Backend Uvicorn master processes: 1
- Backend Uvicorn worker processes: 4
- Active Swift/Xcode/Playwright/Codemagic processes: 0
- Listening ports proved: 5173, 8000, 6379
- Frontend root: HTTP 200, `text/html`
- Backend root: HTTP 200, `text/html; charset=utf-8`
- Backend docs: HTTP 200
- Redis: `PONG`

No process or service was restarted.

## Authentication and realtime evidence

- Auth health probes: 1 HTTP 200
- Positive login probes: 1/1 passed after correctly parsing the configured quoted credentials
- Authenticated role: `trader`
- Authenticated user active: true
- Unauthenticated `/api/auth/me`: HTTP 401
- Auth production-readiness defects: local-file user store, local-file revocation store, no production database backend, MFA step-up unconfigured
- WebSocket connections: 4/4 valid endpoints passed
  - Enterprise realtime bootstrap: 94,865-byte frame, 217 ms
  - Market data: 48,829-byte frame, 26 ms
  - Paper activity: 8,424-byte frame, 36 ms
  - Read-only resource: 803-byte frame, 21 ms

One intentionally corrected discovery probe to nonexistent `/api/v2/ws` returned 404; the mounted enterprise path is `/api/v2/realtime/ws`.

## iOS environment and build-configuration evidence

- App default base URL: `https://dashboard.wajidali.us`
- Public app root probe: HTTP 200
- Public auth-health probe: HTTP 200 JSON
- Public live-gate probe: blocked, no live route or mutation
- Cross-platform CLI/core fallback: `http://127.0.0.1:5173`
- Swift toolchain present: Swift 6.1.2 on Linux
- Bundle identifier: `com.wali1984.aibot-v2`
- Scheme: `AIBotV2`
- Marketing version: 1.0.0
- Current build number: 8
- Previous recorded uploaded build: 4
- Required minimum: 5
- Static build-number guard: 1/1 passed
- Codemagic workflows parsed: 2
  - iOS release: manual, `mac_mini_m2`, App Store signing, integration name `ASC_API_KEY`, 4 scripts, 3 artifact paths, 0 test scripts, 0 cache definitions
  - Linux CLI: push + pull request, 3 scripts, tests present, 1 artifact path, 0 cache definitions
- Codemagic CLI/configured API environment: unavailable locally; repository association and latest external archive cannot yet be proved.

## GitHub evidence

- Root workflows active on GitHub: 2
- Recent branch runs inspected: 20
- Recent branch runs passed: 0
- Recent branch runs failed: 20
- HEAD run: `29862625205`
- HEAD job: `iOS/watchOS simulator build evidence`
- HEAD Swift tests: 35 passed / 1 failed / 36 executed
- Exact failure: the visible-copy test rejects the honest `Paper only` string in `DataTruthView.swift`.
- Simulator/build steps skipped after the test failure: 6
- Failure log retrieval: direct GitHub Actions job-log endpoint succeeded; bundled inspector was incompatible with the installed `gh` version and its unsupported `--json` flag.

The failing assertion conflicts with this mission's requirement to label paper-only state honestly. It is an open iOS/CI contract defect; it was inspected but not edited in preflight.

## Reused audit evidence

- Prior audit/fix commits identified on 2026-07-21: 37
- Files touched across the broader audit range:
  - Frontend: 102
  - Mobile: 12
  - Backend API: 14
- Recent final-field families already committed: public shell, iOS, trader/portfolio, dashboard/trade terminal, markets, deep market data, ingestors/providers, signal explainability, AI/trainer, admin/RBAC, replay/backtests, backend projection, and held-component exposure.
- Retained screenshots found for those passes: 0
- Retained route count: not recorded
- Retained individual-field count: not recorded

Those audit passes will not be rerun as new audits. Their fixes are inputs to the single allowed final regression, where route, field-comparison, screenshot, endpoint, build, and residual-defect counts will be recorded.

## Existing fixes that require final regression only

- Public/global shell: `740bbc0f`, `71a933eb`, `2b784503`
- Trading/portfolio/dashboard: `29d65302`, `a05835f0`, `94b05b19`
- Markets/charts/deep market data: `e047fbcb`, `eb230a26`, `1a043369`
- Ingestors/providers: `71953dd5`, `39c30913`, `dd7d63c7`
- Trainer/AI: `6a4c4c47`, `52e14a61`, `f46aa2e4`
- Admin/system/RBAC/replay: `80ca39ff`, `f30d0fbe`, `5394cfbf`, `6e7083a2`, `2278c230`, `b3af790e`, `b64a9c00`, `2b934436`, `2b58efec`, `4c5f7484`, `50f9575e`, `8e758919`, `ebaefd4b`, `8a46cc00`, `bc21795c`, `528cfafe`, `baa7cbf9`
- iOS: `b484474f`, `ebc8ae0f`
- Backend projections: `b4bd0c8f`, `9a097c04`, `e96462f4`

## Open defects and blockers

1. GitHub iOS validation: 1 failing test blocks 6 simulator/build steps.
2. Auth: 4 production-hardening gaps reported by the live health contract.
3. Codemagic iOS release workflow: 0 test scripts and 0 cache definitions.
4. Codemagic external association/archive/signing result: not locally observable.
5. iOS source: 3 untracked owner-held files prevent a trustworthy clean-tree build claim.
6. Evidence retention: 0 screenshots and no retained exact route/field counts from prior passes.
7. Working tree: 155 pre-existing dirty paths remain excluded.

## Live-gate proof

- `live_gate`: `blocked_human_only`
- `live_trading_enabled`: false
- `live_blocked`: true
- `operator_approved`: false
- Live symbols: 0
- Execution live symbols: 0
- `release_mode`: `NON_LIVE`
- `live_ready`: false
- `live_submit_allowed`: false
- `routes_to_live`: false
- `places_real_order`: false
- `order_submitted`: false
- `test_order_submitted`: false
- `leverage_mutated`: false
- `margin_mutated`: false
- Readiness blockers: 2

Preflight exchange mutations: 0. Service restarts: 0. Redis writes: 0. Live-gate mutations: 0.
