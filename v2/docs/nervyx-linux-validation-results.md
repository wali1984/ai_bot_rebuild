# NERVYX Linux Validation Results

- Status: IN PROGRESS / FAILED GATES PRESENT.
- Host date: 2026-06-22.
- Scope: Linux-feasible web, backend, and Swift package checks only. This is not native iOS/watchOS/TestFlight validation.

## Latest Current Evidence

These are the current unfiltered results from the active lane after the web fixture and presentation cleanup:

### Position Pricing / AI Reasoning Continuation

This subsection covers the 2026-06-22 continuation for paper position entry/mark/close prices and position decision reasoning. It is focused evidence only and does not close the full NERVYX gate.

| Area | Command | Collected | Passed | Failed | Errors | Skipped / did not run | Duration | Result |
|---|---|---:|---:|---:|---:|---:|---|---|
| Backend syntax | `../.venv/bin/python -m py_compile backend/app/api/v2/market_contracts.py backend/app/api/v2/mobile.py` | n/a | n/a | 0 | 0 | 0 | <1s | PASS |
| Backend focused mark/reasoning tests | `../.venv/bin/python -m pytest backend/tests/unit/api/test_paper_mark_price_freshness.py -q` | 22 | 22 | 0 | 0 | 0 | 0.32s | PASS |
| Backend focused mark/reasoning tests current | `../.venv/bin/python -m pytest backend/tests/unit/api/test_paper_mark_price_freshness.py -q` | 30 | 30 | 0 | 0 | 0 | 0.32s | PASS |
| Backend read-only resource adapter tests | `../.venv/bin/python -m pytest backend/tests/unit/api/test_readonly_market_stream_parser.py -k "readonly_resource_direct_payload_routes_paper_status_and_activity or readonly_resource_websocket" -q` | 64 selected/deselected | 35 | 0 | 0 | 29 deselected | 0.32s | PASS |
| Position HTTP/WebSocket realtime probe | `python3 scripts/nervyx_position_realtime_probe.py --host 127.0.0.1:5173 --output artifacts/nervyx-position-realtime-probe.json --sample-size 3 --frames 2 --interval-ms 750` | 8 transport/path checks | 8 | 0 | 0 | 0 | 23.6s | PASS: 0 issues |
| Swift package build | `swift build` | n/a | n/a | 0 | 0 | 0 | 1.78s | PASS |
| Swift package tests | `swift test` | 10 XCTest + 0 Swift Testing | 10 | 0 | 0 | 0 | 0.132s XCTest | PASS |
| Swift package tests current | `swift test` | 16 XCTest + 0 Swift Testing | 16 | 0 | 0 | 0 | 0.131s XCTest | PASS |
| Frontend typecheck | `npm run typecheck` | n/a | n/a | 0 | 0 | 0 | 6.1s | PASS |
| Frontend build | `npm run build` | n/a | n/a | 0 | 0 | 0 | 12.6s | PASS with existing Vite chunk-size warning |
| Playwright focused portfolio/history | `npx playwright test tests/e2e/trader_nav_cleanliness.spec.ts -g "portfolio route\|portfolio history" --project=chromium` | 2 | 2 | 0 | 0 | 0 | 1.8s | PASS |
| Playwright focused realtime/position retention | `npx playwright test tests/e2e/paper_positions_refresh_persistence.spec.ts tests/e2e/trade_terminal_realtime_contract.spec.ts --project=chromium` | 8 | 8 | 0 | 0 | 0 | 328ms | PASS |

Validated in this slice:

- Missing mark prices remain `null`/unavailable; no backend or Swift compact model coerces them to zero.
- Position mark price is populated from realtime/public mark sources when a positive current mark exists; stale marks carry age and stale state.
- Position entry price uses a positive recorded entry/fill source and carries `entry_price_source`.
- Closed trade entry/exit prices skip zero and use positive recorded fallback fields only; otherwise they remain unavailable.
- Position and historical trade rows expose AI reasoning from matching signal/prediction ids where available, with ledger-derived evidence as fallback; unrelated latest signals are rejected when row ids do not match.
- Web portfolio and paper-trading tables render compact AI reasoning/basis without implying live execution.
- iOS `PositionsView`, paper preview, watch sync, and watch positions row preserve optional price fields and display unavailable states.
- `/api/v2/ws/resource?path=/api/v2/paper/activity` now uses the existing read-only paper activity builder directly. The first probe exposed the missing adapter as a stale/unavailable generic-resource frame while the dedicated `/api/v2/ws/paper-activity` stream was healthy; after the read-only adapter fix and service restart, the repeatable artifact passed with 0 issues.
- Current localhost probe row counts: paper status HTTP/WS returned 14 open and 200 closed rows; paper activity HTTP/WS returned 14 open rows; account positions HTTP/WS returned 14 open rows; mobile positions HTTP returned 14 open, 50 closed, 200 historical rows; mobile positions WS returned 13 open, 50 closed, 200 historical rows. Sampled rows passed positive price, source, freshness, and reasoning checks.

| Area | Command | Collected | Passed | Failed | Errors | Skipped / did not run | Duration | Result |
|---|---|---:|---:|---:|---:|---:|---|---|
| Frontend typecheck | `npm run typecheck` | n/a | n/a | 0 | 0 | 0 | 5.8s | PASS |
| Frontend build | `npm run build` | n/a | n/a | 0 | 0 | 0 | 17.2s combined with typecheck rerun | PASS with existing Vite chunk-size warning |
| Frontend lint | `npm run lint --if-present` | 0 | 0 | 0 | 0 | 0 | <1s | NO SCRIPT DEFINED |
| Frontend unit tests | package script inventory | 0 | 0 | 0 | 0 | 0 | n/a | NO UNIT TEST SCRIPT DEFINED; frontend tests are Playwright specs |
| Forbidden public execution copy search | `rg -n "Live trading platform|Live execution|Trading live|Paper only|simulated line|Adaptive Market Intelligence · Live trading platform" frontend/src -S` | n/a | n/a | 0 | 0 | 0 | <1s | PASS: no source matches |
| Playwright Chromium full suite | `PLAYWRIGHT_NO_WEBSERVER=1 PLAYWRIGHT_BASE_URL=http://127.0.0.1:5173 npx playwright test --project=chromium --reporter=json > ../artifacts/nervyx-playwright-chromium-5173-final-current.json` | 367 | 367 expected | 0 unexpected | 0 | 0 skipped / 0 flaky | 276.10s | PASS |
| Swift package build | `swift build` | n/a | n/a | 0 | 0 | 0 | 0.18s | PASS |
| Swift package tests | `swift test` | 10 XCTest + 0 Swift Testing | 10 | 0 | 0 | 0 | 0.332s XCTest | PASS |
| Backend pytest full suite | `../.venv/bin/python -m pytest backend/tests --junitxml=artifacts/nervyx-backend-pytest-current.xml` | 5074 | 4847 | 209 | 6 | 12 skipped | 548.51s | FAIL; process exited with code 139 after summary |
| macOS/Xcode availability | `xcodebuild -version` | n/a | n/a | n/a | n/a | n/a | <1s | BLOCKED: `xcodebuild` not found |

| Area | Command | Collected | Passed | Failed | Errors | Skipped / did not run | Duration | Result |
|---|---|---:|---:|---:|---:|---:|---|---|
| Frontend typecheck | `npm run typecheck` | n/a | n/a | 0 | 0 | 0 | ~6s | PASS |
| Frontend build | `npm run build` | n/a | n/a | 0 | 0 | 0 | ~18s | PASS with existing Vite chunk-size warning |
| Frontend lint | `npm run lint --if-present` | 0 | 0 | 0 | 0 | 0 | <1s | NO SCRIPT DEFINED |
| Frontend unit tests | `npm test --if-present` | 0 | 0 | 0 | 0 | 0 | <1s | NO SCRIPT DEFINED |
| Playwright Chromium list | `npx playwright test --project=chromium --list` | 367 | n/a | 0 | 0 | 0 | ~1s | PASS |
| Playwright Chromium full suite | `npx playwright test --project=chromium` | 367 | 226 | 109 | 0 | 32 did not run | 6.8m | FAIL |
| Playwright Chromium full suite after telemetry fix | `PLAYWRIGHT_NO_WEBSERVER=1 PLAYWRIGHT_BASE_URL=http://127.0.0.1:5173 npx playwright test --project=chromium --reporter=json > ../artifacts/nervyx-playwright-chromium-5173-after-telemetry.json` | 367 | 244 | 91 | 0 | 32 did not run | 379s | FAIL |
| Playwright Chromium full suite after route/empty-state fixes | `PLAYWRIGHT_NO_WEBSERVER=1 PLAYWRIGHT_BASE_URL=http://127.0.0.1:5173 npx playwright test --project=chromium --reporter=json > ../artifacts/nervyx-playwright-chromium-5173-after-route-invariant.json` | 367 | 246 | 89 | 0 | 32 did not run | 380s | FAIL |
| Playwright Chromium full suite after auth-aware nav smoke fixes | `PLAYWRIGHT_NO_WEBSERVER=1 PLAYWRIGHT_BASE_URL=http://127.0.0.1:5173 npx playwright test --project=chromium --reporter=json > ../artifacts/nervyx-playwright-chromium-5173-after-auth-nav-smoke.json` | 367 | 291 | 44 | 0 | 32 did not run | 367s | FAIL |
| Playwright Chromium full suite after default-deny fix | `PLAYWRIGHT_NO_WEBSERVER=1 PLAYWRIGHT_BASE_URL=http://127.0.0.1:5173 npx playwright test --project=chromium --reporter=json > ../artifacts/nervyx-playwright-chromium-5173-after-default-deny.json` | n/a | n/a | n/a | n/a | n/a | ~12s | INTERRUPTED by user; artifact is zero bytes and is not evidence |
| Playwright Chromium full suite after trader-nav cleanup | `PLAYWRIGHT_NO_WEBSERVER=1 PLAYWRIGHT_BASE_URL=http://127.0.0.1:5173 npx playwright test --project=chromium --reporter=json > ../artifacts/nervyx-playwright-chromium-5173-after-trader-nav-cleanliness.json` | 367 | 317 | 19 | 0 | 31 skipped | 390s | FAIL |
| Playwright token-drift focused debug | `npx playwright test --project=chromium tests/e2e/nervyx_theme_token_drift.spec.ts` | 1 | 1 | 0 | 0 | 0 | 333ms | PASS after test correction; not final suite evidence |
| Adaptive telemetry focused current-bundle debug | `PLAYWRIGHT_NO_WEBSERVER=1 PLAYWRIGHT_BASE_URL=http://127.0.0.1:5174 npx playwright test --project=chromium tests/e2e/adaptive_capital_telemetry_panel.spec.ts` | 19 | 19 | 0 | 0 | 0 | 2.3s | PASS after presentation-only matrix empty-state fix; not final suite evidence |
| Derivatives liquidation focused current-bundle debug | `PLAYWRIGHT_NO_WEBSERVER=1 PLAYWRIGHT_BASE_URL=http://127.0.0.1:5174 npx playwright test --project=chromium tests/e2e/trader_signal_selector_controls.spec.ts -g "derivatives liquidation and long-short tabs render streamed rows"` | 1 | 1 | 0 | 0 | 0 | 1.2s | PASS; not final suite evidence |
| Topbar alignment focused current-bundle debug | `PLAYWRIGHT_NO_WEBSERVER=1 PLAYWRIGHT_BASE_URL=http://127.0.0.1:5174 npx playwright test --project=chromium tests/e2e/trader_nav_cleanliness.spec.ts -g "topbar primary navigation stays aligned without module-chip wrapping"` | 1 | 1 | 0 | 0 | 0 | 1.9s | PASS; not final suite evidence |
| Adaptive telemetry focused localhost debug | `PLAYWRIGHT_NO_WEBSERVER=1 PLAYWRIGHT_BASE_URL=http://127.0.0.1:5173 npx playwright test --project=chromium tests/e2e/adaptive_capital_telemetry_panel.spec.ts` | 19 | 19 | 0 | 0 | 0 | 2.5s | PASS on backend-hosted localhost surface after frontend rebuild; not final suite evidence |
| Derivatives liquidation focused localhost debug | `PLAYWRIGHT_NO_WEBSERVER=1 PLAYWRIGHT_BASE_URL=http://127.0.0.1:5173 npx playwright test --project=chromium tests/e2e/trader_signal_selector_controls.spec.ts -g "derivatives liquidation and long-short tabs render streamed rows"` | 1 | 1 | 0 | 0 | 0 | 5.9s | PASS on backend-hosted localhost surface; not final suite evidence |
| Topbar alignment focused localhost debug | `PLAYWRIGHT_NO_WEBSERVER=1 PLAYWRIGHT_BASE_URL=http://127.0.0.1:5173 npx playwright test --project=chromium tests/e2e/trader_nav_cleanliness.spec.ts -g "topbar primary navigation stays aligned without module-chip wrapping"` | 1 | 1 | 0 | 0 | 0 | 3.4s | PASS on backend-hosted localhost surface; not final suite evidence |
| Market/portfolio/backtests focused localhost debug | `PLAYWRIGHT_NO_WEBSERVER=1 PLAYWRIGHT_BASE_URL=http://127.0.0.1:5173 npx playwright test --project=chromium tests/e2e/market_public_fallback.spec.ts tests/e2e/trader_nav_cleanliness.spec.ts -g "recovers overview|portfolio source copy|legacy replay route redirects"` | 3 | 3 | 0 | 0 | 0 | 3.3s | PASS; not final suite evidence |
| Routing invariants focused debug | `npx playwright test --project=chromium tests/e2e/routing_invariants.spec.ts` | 12 | 12 | 0 | 0 | 0 | 425ms | PASS; preserves admin signal-explainability route for role audit |
| Auth-aware nav smoke and trader-first focused debug | `PLAYWRIGHT_NO_WEBSERVER=1 PLAYWRIGHT_BASE_URL=http://127.0.0.1:5173 npx playwright test --project=chromium tests/e2e/nav_smoke.spec.ts tests/e2e/trader_first_redesign.spec.ts` | 43 | 43 | 0 | 0 | 0 | 10.9s | PASS after backend-auth fixtures; not final suite evidence |
| Default-deny dangerous-control focused debug | `PLAYWRIGHT_NO_WEBSERVER=1 PLAYWRIGHT_BASE_URL=http://127.0.0.1:5173 npx playwright test --project=chromium tests/e2e/default_deny_inventory.spec.ts` | 5 | 5 | 0 | 0 | 0 | 1.7s | PASS after risk-control presentation panel and rebuild; not final suite evidence |
| Trader nav cleanliness focused debug | `PLAYWRIGHT_NO_WEBSERVER=1 PLAYWRIGHT_BASE_URL=http://127.0.0.1:5173 npx playwright test --project=chromium tests/e2e/trader_nav_cleanliness.spec.ts` | 39 | 39 | 0 | 0 | 0 | 13.7s | PASS after backend-auth fixtures, realtime wait cleanup, and public/trader copy corrections; not final suite evidence |
| Swift package build | `swift build` | n/a | n/a | 0 | 0 | 0 | 0.21s | PASS |
| Swift package tests | `swift test` | 10 XCTest + 0 Swift Testing | 10 | 0 | 0 | 0 | 0.126s XCTest | PASS |
| Backend pytest full suite | `../.venv/bin/pytest backend` | 5054 | 4827 | 209 | 6 | 12 skipped | 10:39 | FAIL; process exited with code 139 after summary |
| Backend pytest full suite current | `../.venv/bin/python -m pytest backend/tests --junitxml=artifacts/nervyx-backend-pytest-current.xml` | 5074 | 4847 | 209 | 6 | 12 skipped | 548.51s | FAIL; process exited with code 139 after summary |
| macOS/Xcode availability | `xcodebuild -version` | n/a | n/a | n/a | n/a | n/a | <1s | BLOCKED: `xcodebuild` not found |

## Localhost 5173 Note

During the focused frontend rerun, `127.0.0.1:5173` was occupied by the backend process:

`/home/wali/Desktop/AI BOT REBUILD/.venv/bin/python3 -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 5173 ...`

The default Playwright config reuses an existing server on port 5173, so the first rerun exercised that existing backend-hosted surface before the frontend rebuild and did not pick up the current frontend source edit. Current-bundle focused checks were first run against `vite preview` on `127.0.0.1:5174` with `PLAYWRIGHT_NO_WEBSERVER=1`. After `npm run build`, the same focused checks also passed against the backend-hosted `127.0.0.1:5173` surface.

## Playwright Failure Inventory

The latest completed full Chromium suite artifact is `artifacts/nervyx-playwright-chromium-5173-final-current.json`. It passed with 367 expected, 0 unexpected, 0 skipped, and 0 flaky results after the final execution-copy cleanup and frontend rebuild.

Historical failing artifact `artifacts/nervyx-playwright-chromium-5173-after-trader-nav-cleanliness.json` failed in these broad areas before the current fixture/presentation cleanup:

- Runtime-alpha trader-surface visibility: 6 failures waiting for direct canonical URL handling.
- Mission-control readiness banner: 4 failures waiting for `mission-control-readiness-banner`.
- Enterprise admin cockpit rendering: 2 failures.
- Stale-state alerts: 2 failures.
- Operator proof dashboard historical 30d: 1 failure.
- ProChart realtime contract: 1 failure.
- Trade terminal redesign: 1 failure.
- Phase 13A visual gate and screenshot-all-pages: 1 failure each.

Cleared since the earlier full-suite baseline:

- Adaptive capital telemetry route rendering no longer appears in the current full-suite failure distribution.
- Market public fallback copy no longer appears in the current full-suite failure distribution.
- Derivatives liquidation and long/short streamed rows no longer appear in the current full-suite failure distribution.
- Routing invariants pass after keeping `/admin/signal-explainability` renderable for admin coverage.
- Full admin route smoke coverage, trader-first shell checks, default-deny dangerous-control inventory, and trader navigation cleanliness no longer appear in the latest full-suite failure distribution.

## Backend Failure Inventory

Current artifact: `artifacts/nervyx-backend-pytest-current.xml`.

Current full backend result: 5074 collected, 4847 passed, 209 failed, 6 errors, 12 skipped, 1 warning, 548.51s. The pytest process exited with code 139 after printing the summary.

Current setup errors:

- `backend.tests.integration.cli.test_v2_feature_snapshot_builder::*`: six tests error during setup because `v2/backend/tests/fixtures/feature_snapshots/sample_legacy_feature_payload.json` is missing.

Current representative failures include:

- Alternative data symbol candidate frontend wiring label coverage.
- Feature pipeline native service file discovery and full observation builder metadata/dimension expectations.
- Liquidation WSS systemd unit path coverage.
- Native RL/MASA/PPO trainer runtime lineage/replay/checkpoint expectations.
- Paper fill, paper ledger, paper position acceptance, policy architecture, and paper outcome memory expectations.
- Website data alignment and control plane expectations.
- Composition/domain/service import-boundary and forbidden-token tests across orchestrator, paper mode, paper execution ledger, replay, risk gateway, shadow readiness, and trainer prediction output.
- Feature snapshot model/trainer input contract expectations.
- Symbol universe fixture discovery, uploaded Coinank list, normalization, overrides, state machine, and config-version expectations.
- Runtime alpha decision-chain expectations.

The backend full suite failed in many areas, including:

- Alternative data symbol candidate frontend wiring.
- Feature pipeline / feature snapshot builder and full observation builder.
- Liquidation WSS/runtime coverage.
- Native RL/MASA/PPO trainer-related tests.
- Paper ledger, paper position acceptance, paper outcome memory, and policy architecture tests.
- Website data alignment and control plane tests.
- Composition/domain/service import-boundary and forbidden-token tests across orchestrator, paper mode, replay, risk gateway, shadow readiness, and trainer prediction output.
- Feature snapshot model/trainer input contract tests.
- Symbol universe discovery/normalization/state-machine tests.
- Runtime alpha decision-chain tests.

These failures are not explained away and keep the NERVYX ONE goal in progress.

## 2026-06-23 Brand Asset / Truthful Metadata Continuation

Scope: approved `/rebranding` asset wiring, public metadata copy, landing-logo usage, and mobile visible label cleanup. This is presentation-only work; it does not change order routing, execution, risk, strategy, PPO, MASA, trainer calculations, publisher contracts, Redis producers, database records, or API field meanings.

| Area | Command | Collected | Passed | Failed | Errors | Skipped / did not run | Duration | Result |
|---|---|---:|---:|---:|---:|---:|---|---|
| Brand asset checksum proof | `sha256sum ... rebranding/frontend/mobile brand assets` | n/a | n/a | 0 | 0 | 0 | <1s | PASS: header, login, landing, favicon, social banner, and iOS asset-catalog copies match approved checksums where copied directly |
| Forbidden live-execution copy scan | `rg -n "live trading execution|live market execution|live execution|Live execution|Live trading platform|Trading live|live trading workflow|Sign In to NerVyx|case \\.paper: return \\"Live\\"" frontend/src frontend/index.html frontend/public/manifest.webmanifest mobile/Sources -S` | n/a | n/a | 0 | 0 | 0 | <1s | PASS: no matches |
| Frontend typecheck | `npm run typecheck` | n/a | n/a | 0 | 0 | 0 | 5.9s | PASS |
| Swift package build | `swift build` | n/a | n/a | 0 | 0 | 0 | 0.20s | PASS |
| Swift package tests | `swift test` | 10 XCTest + 0 Swift Testing | 10 | 0 | 0 | 0 | 0.129s XCTest | PASS |
| Diff whitespace check | `git diff --check -- ...` | n/a | n/a | 0 | 0 | 0 | <1s | PASS |
| Frontend build first attempt | `npm run build` | n/a | n/a | 0 | 1 | 0 | 9.9s | FAIL: Vite hit a transient publisher race on `frontend/public/.../all_symbol_all_timeframe_cuda_prediction_status.json.tmp`; the `.tmp` file was gone immediately after the failure |
| Frontend build rerun | `npm run build` | n/a | n/a | 0 | 0 | 0 | 12.7s | PASS with existing Vite chunk-size warning |

The first `npm run build` failure is not counted as a code failure after the immediate rerun passed, but it remains a build-environment risk because live runtime publishers can race Vite's public-directory copy. Native iOS/watchOS and TestFlight validation remain blocked on macOS/Xcode/App Store Connect access.

## 2026-06-23 Truthful Status Copy Continuation

Scope: presentation-only cleanup for source-visible labels that used "live platform" or "live trading" as a generic product status. The UI now separates realtime market/data stream language from execution permission language (`Execution restricted`, `Order routing approved`, `Live order routing remains blocked`, `Realtime data`). This pass did not change backend truth fields, gate booleans, order-routing behavior, exchange execution, risk, strategy, PPO, MASA, trainer calculations, publisher contracts, Redis producers, database records, or API field meanings.

| Area | Command | Collected | Passed | Failed | Errors | Skipped / did not run | Duration | Result |
|---|---|---:|---:|---:|---:|---:|---|---|
| Targeted source copy scan | `rg -n "Live platform\|LIVE PLATFORM\|Live Trading\|Live trading\|live trading\|Trading live\|Live execution\|live execution\|live market execution" frontend/src mobile/Sources -S` | n/a | n/a | 0 | 0 | 0 | <1s | PASS: no source/mobile visible-copy matches |
| Frontend typecheck | `npm run typecheck` | n/a | n/a | 0 | 0 | 0 | 5.5s | PASS |
| Frontend build | `npm run build` | n/a | n/a | 0 | 0 | 0 | 11.4s | PASS with existing Vite chunk-size warning |
| Swift package build | `swift build` | n/a | n/a | 0 | 0 | 0 | 0.17s | PASS |
| Swift package tests | `swift test` | 10 XCTest + 0 Swift Testing | 10 | 0 | 0 | 0 | 0.126s XCTest | PASS |
| Paper position price/mark/reasoning focused backend test | `../.venv/bin/pytest backend/tests/unit/api/test_paper_mark_price_freshness.py -q` | 22 | 22 | 0 | 0 | 0 | 0.30s | PASS |
| Diff whitespace check | `git diff --check -- ...` | n/a | n/a | 0 | 0 | 0 | <1s | PASS |

Notes:

- A broader repository scan still finds old wording in generated `frontend/dist`, historical `frontend/public` runtime artifacts, and a mobile unit-test forbidden-string fixture. Those are not current source-visible copy. Generated artifacts remain part of the lane inventory and must be handled under the broader cleanup/classification gate.
- Direct `pytest` and `python3 -m pytest` failed in this shell because the global entrypoint/module is unavailable; the project virtualenv entrypoint `../.venv/bin/pytest` was used and passed.
- The NERVYX ONE goal remains `IN PROGRESS`. This update does not satisfy native iOS/watchOS validation, TestFlight, full backend pytest, full role-route rendering, lane isolation, or 100% field-level data parity.

## 2026-06-23 Shared Theme / Token Parity Continuation

Scope: strengthened the shared NERVYX theme/token parity proof. The generator now emits Swift theme/module dictionaries from the same `/rebranding/nervyx-one-brand-tokens.json` source as the web CSS/TS manifest, keeps public presentation descriptions free of `Paper/live` wording, and preserves the Ops Terminal admin/superadmin restriction as presentation-only gating. This pass did not change order routing, execution, risk, strategy, PPO, MASA, trainer calculations, publisher contracts, Redis producers, database records, or API field meanings.

| Area | Command | Collected | Passed | Failed | Errors | Skipped / did not run | Duration | Result |
|---|---|---:|---:|---:|---:|---:|---|---|
| Token generation | `npm run brand:tokens` | n/a | n/a | 0 | 0 | 0 | <1s | PASS: regenerated web CSS/TS/manifest and Swift generated token/manifest outputs from checksum `36bf9013c0a13604cadc6ffa3429a875249359f36755bb1b9bf13f6baf49f2d7` |
| Value-level drift check | `npm run brand:tokens:check` | n/a | n/a | 0 | 0 | 0 | <1s | PASS: web manifest, web tokens, CSS variables, Swift token constants, Swift theme access, and module dictionaries match the same source token version |
| Focused Playwright theme drift spec | `npx playwright test tests/e2e/nervyx_theme_token_drift.spec.ts --reporter=list` | 1 | 1 | 0 | 0 | 0 | 0.268s | PASS |
| Frontend typecheck | `npm run typecheck` | n/a | n/a | 0 | 0 | 0 | 5.8s | PASS |
| Frontend build | `npm run build` | n/a | n/a | 0 | 0 | 0 | 12.4s | PASS with existing Vite chunk-size warning |
| Swift package tests | `swift test` | 11 XCTest + 0 Swift Testing | 11 | 0 | 0 | 0 | 0.331s XCTest | PASS |
| Source-visible phrase scan | `rg -n "Paper/live\|paper/live\|Live trading platform\|Live Trading\|Live platform\|simulated\|NO DATA\|DATA UNAVAILABLE" ...` | n/a | n/a | 0 | 0 | 0 | <1s | PASS for generated brand/theme outputs; remaining hits are a sanitizer guard in `NervyxBrand.swift` and technical `simulated_overlay` field names in `ai-brain` |
| Diff whitespace check | `git diff --check -- ... theme/token files ...` | n/a | n/a | 0 | 0 | 0 | <1s | PASS |

Notes:

- Swift Linux tests still cannot validate the native iOS/watchOS app targets because `Package.swift` excludes `AIBotV2` and `AIBotV2Watch` on Linux; macOS/Xcode validation remains required.
- This proves token-source parity and generated output drift for the shared theme system. It does not yet prove full visual coverage for every chart/table under every theme, Dynamic Type, increased contrast, Reduce Motion, or full authenticated role-route rendering.

## 2026-06-23 OpenAPI Compatibility Continuation

Scope: added and ran a read-only OpenAPI compatibility capture/report tool. It archives the merge base into a temp directory, captures current OpenAPI from `app.main.create_app().openapi()`, and attempts a separately labelled shimmed baseline capture for missing modules inside the archived merge-base tree. This pass did not change API route handlers, endpoint semantics, permission checks, order routing, execution, risk, strategy, PPO, MASA, trainer calculations, publisher contracts, Redis producers, database records, or API field meanings.

| Area | Command | Collected | Passed | Failed | Errors | Skipped / did not run | Duration | Result |
|---|---|---:|---:|---:|---:|---:|---|---|
| OpenAPI capture/diff | `../.venv/bin/python scripts/nervyx_openapi_compatibility.py` | current 118 operations; shimmed baseline 65 operations | n/a | 0 | 0 | 0 | 1.8s | PARTIAL: current capture passed; raw baseline failed; shimmed baseline passed; 0 removed operations, 0 removed fields, 0 type changes, 0 security metadata changes against captured baseline |
| OpenAPI JSON validation | `python3 -m json.tool ...` | 5 JSON artifacts | 5 | 0 | 0 | 0 | <1s | PASS |
| OpenAPI artifact summary check | `python3 - <<'PY' ... artifacts/nervyx-openapi-compatibility-summary.json ...` | n/a | n/a | 0 | 0 | 0 | <1s | PASS: status `PARTIAL_SHIMMED_BASE_UNPROVEN`, raw baseline capture false, shimmed baseline capture true |
| Diff whitespace check | `git diff --check -- scripts/nervyx_openapi_compatibility.py docs/nervyx-openapi-*.json docs/nervyx-openapi-compatibility-report.md artifacts/nervyx-openapi-*` | n/a | n/a | 0 | 0 | 0 | <1s | PASS |

Artifacts:

- `docs/nervyx-openapi-before.json`
- `docs/nervyx-openapi-after.json`
- `docs/nervyx-openapi-compatibility-report.md`
- `artifacts/nervyx-openapi-before-static-routes.json`
- `artifacts/nervyx-openapi-after-static-routes.json`
- `artifacts/nervyx-openapi-compatibility-summary.json`

Notes:

- OpenAPI compatibility remains `UNPROVEN` as a completion gate. The merge-base tree imports route/support modules that are absent in the same tree, so raw baseline capture fails. The shimmed baseline is useful evidence that no captured baseline operation/field/type was removed, but it cannot prove compatibility for routers replaced by empty temp APIRouter stubs.
- Static route fallback also found 0 removed route keys, but static decorator evidence is weaker than OpenAPI and does not prove permission compatibility.

## 2026-06-23 Native Apple Validation Lane Continuation

Scope: prepared a macOS/Xcode CI validation lane for the native iOS/watchOS surfaces while preserving the blocked status on this Linux host. This pass did not change signing, Apple accounts, entitlements, App Store Connect state, TestFlight state, order routing, execution, risk, strategy, PPO, MASA, trainer calculations, publisher contracts, Redis producers, database records, or API field meanings.

| Area | Command | Collected | Passed | Failed | Errors | Skipped / did not run | Duration | Result |
|---|---|---:|---:|---:|---:|---:|---|---|
| macOS workflow added | `.github/workflows/nervyx-ios-macos-validation.yml` | n/a | n/a | 0 | 0 | 0 | n/a | PREPARED: macOS runner lane with Xcode evidence, XcodeGen, build-number guard, Swift build/test, iPhone simulator-class builds, iOS SwiftPM app product build, watchOS SwiftPM product build, and artifact upload |
| Workflow YAML parse | `python3 - <<'PY' import yaml ...` | 1 workflow | 1 | 0 | 0 | 0 | <1s | PASS |
| Workflow structure check | `python3 - <<'PY' ... required snippets ...` | 7 required snippets | 7 | 0 | 0 | 0 | <1s | PASS |
| Static TestFlight build-number guard | `python3 scripts/check_ios_app_store_build_number.py` | n/a | n/a | 0 | 0 | 0 | <1s | PASS: `current=6 previous=4` |
| Swift package tests | `swift test` | 11 XCTest + 0 Swift Testing | 11 | 0 | 0 | 0 | 0.13s XCTest | PASS |
| macOS/Xcode availability | `xcodebuild -version` | n/a | n/a | n/a | n/a | n/a | <1s | BLOCKED: `xcodebuild` not found |
| Diff whitespace check | `git diff --check -- .github/workflows/nervyx-ios-macos-validation.yml docs/nervyx-ios-macos-validation.md docs/nervyx-watchos-validation.md docs/nervyx-testflight-readiness.md ...` | n/a | n/a | 0 | 0 | 0 | <1s | PASS |

Notes:

- Native iOS validation remains `BLOCKED - MACOS/XCODE REQUIRED` until this workflow or an equivalent Mac host actually runs and produces artifacts.
- watchOS validation remains `BLOCKED - MACOS/XCODE REQUIRED`. The workflow builds the SwiftPM `AIBotV2WatchApp` product for watchOS simulator, but a full XcodeGen watch app install/launch path is still unproven because `mobile/project.yml` currently defines the iOS app/core targets only.
- TestFlight remains `BLOCKED`. No archive upload or App Store Connect processing was attempted.

## 2026-06-23 watchOS XcodeGen Target Continuation

Scope: reduced the native watchOS validation gap by adding a committed watchOS XcodeGen target and making the macOS workflow build it with signing disabled. This pass did not change signing, Apple accounts, entitlements, App Store Connect state, TestFlight state, order routing, execution, risk, strategy, PPO, MASA, trainer calculations, publisher contracts, Redis producers, database records, or API field meanings.

| Area | Command | Collected | Passed | Failed | Errors | Skipped / did not run | Duration | Result |
|---|---|---:|---:|---:|---:|---:|---|---|
| Project/workflow static proof | `rg -n "AIBotV2Watch\|WATCH_XCODEGEN_SCHEME\|INFOPLIST_KEY_WKWatchOnly\|com\\.wali1984\\.aibot-v2\\.watch\|watchOS XcodeGen" ...` | n/a | n/a | 0 | 0 | 0 | <1s | PASS: watchOS XcodeGen target and workflow build snippets present |
| YAML/project structure check | `python3 - <<'PY' ... yaml.safe_load workflow/project ...` | 1 workflow + 1 project | 2 | 0 | 0 | 0 | <1s | PASS: `yaml-project-ok` |
| Static TestFlight build-number guard | `npm run ios:app-store-build:check` | n/a | n/a | 0 | 0 | 0 | <1s | PASS: `current=6 previous=4` |
| Swift package tests | `swift test` | 12 XCTest + 0 Swift Testing | 12 | 0 | 0 | 0 | 0.13s XCTest | PASS |
| macOS/Xcode availability | `xcodebuild -version 2>&1 || true` | n/a | n/a | n/a | n/a | n/a | <1s | BLOCKED: `xcodebuild` not found on Linux |
| Diff whitespace check | `git diff --check -- ...watch workflow/project/docs/test files...` | n/a | n/a | 0 | 0 | 0 | <1s | PASS |

Notes:

- `mobile/project.yml` now declares `AIBotV2Watch` as a watchOS application target with bundle identifier `com.wali1984.aibot-v2.watch`, generated Info.plist, display name `NERVYX ONE`, and `WKWatchOnly`.
- `.github/workflows/nervyx-ios-macos-validation.yml` now builds `AIBotV2Watch` for `generic/platform=watchOS Simulator` with `CODE_SIGNING_ALLOWED=NO` after generating the Xcode project.
- `mobile/Tests/AIBotV2Tests/AIBotV2CoreTests.swift` now includes a Linux-runnable guard that proves the workflow and project contain the watchOS target build without signing-team mutation or TestFlight upload tooling.
- Native iOS validation remains `BLOCKED - MACOS/XCODE REQUIRED`.
- Native watchOS validation remains `BLOCKED - MACOS/XCODE REQUIRED`.
- TestFlight remains `BLOCKED`. No archive upload or App Store Connect processing was attempted.

## 2026-06-23 Position Price / Reasoning / App Surface Continuation

Scope: added read-only open/closed/historical position evidence to the mobile contract, iOS positions screen, watch sync payload, and website `/positions` surface. Closed rows now carry real entry/exit price provenance and AI reasoning from the existing prediction/signal evidence path. Open rows continue to carry realtime mark price, mark age, stale/missing indicators, and reasoning. This pass did not change order routing, exchange execution, risk calculations, strategy selection, PPO, MASA, trainer calculations, signal generation semantics, publisher semantics, Redis producer contracts, database records, or API field meanings.

| Area | Command | Collected | Passed | Failed | Errors | Skipped / did not run | Duration | Result |
|---|---|---:|---:|---:|---:|---:|---|---|
| Focused backend position pricing/reasoning tests | `../.venv/bin/pytest backend/tests/unit/api/test_paper_mark_price_freshness.py -q` | 23 | 23 | 0 | 0 | 0 | 0.31s | PASS |
| Swift package tests | `swift test` | 13 XCTest + 0 Swift Testing | 13 | 0 | 0 | 0 | 0.23s XCTest | PASS |
| Frontend typecheck | `npm run --prefix frontend typecheck` | n/a | n/a | 0 | 0 | 0 | 6.1s | PASS |
| Frontend build | `npm run --prefix frontend build` | n/a | n/a | 0 | 0 | 0 | 13.0s | PASS with existing Vite chunk-size warning |
| Frontend lint if present | `npm run --prefix frontend lint --if-present` | n/a | n/a | 0 | 0 | 0 | <1s | PASS: no lint script configured |
| Python compile | `../.venv/bin/python -m py_compile backend/app/api/v2/mobile.py` | 1 file | 1 | 0 | 0 | 0 | <1s | PASS |
| Root typecheck attempt | `npm run typecheck` | n/a | n/a | 1 | 0 | 0 | <1s | EXPECTED FAIL: root package has no `typecheck` script; frontend package script was run and passed |
| Diff whitespace check | `git diff --check -- ...position contract/app/web files...` | n/a | n/a | 0 | 0 | 0 | <1s | PASS |

Files covered by this slice:

- `backend/app/api/v2/mobile.py`
- `backend/tests/unit/api/test_paper_mark_price_freshness.py`
- `frontend/src/pages/positions/index.tsx`
- `mobile/Sources/AIBotV2/Models/APIModels.swift`
- `mobile/Sources/AIBotV2Core/Models.swift`
- `mobile/Sources/AIBotV2/ViewModels/PositionsViewModel.swift`
- `mobile/Sources/AIBotV2/Views/Positions/PositionsView.swift`
- `mobile/Sources/AIBotV2/Watch/WatchSyncCenter.swift`
- `mobile/Tests/AIBotV2Tests/AIBotV2CoreTests.swift`

Notes:

- `/api/v2/mobile/positions` now returns `positions`, `closed_positions`, `historical_positions`, `position_pricing`, `warnings`, and `summary.closed_count`.
- Closed position rows reject zero exit prices and preserve the first valid close/exit price source, including `paper_exit_price` when `exit_price` is zero.
- Website `/positions` now has Open, Closed, and Historical evidence tabs. Closed/historical rows stream from `/api/v2/paper/status` through `useRealtimeResource`, while open rows remain connected to the existing trade-terminal realtime account path.
- iOS `PositionsView` now has Open, Closed, and Historical segmented controls; each row opens a detail view with prices, provenance, realtime mark status, close reason, and AI reasoning.
- watchOS synchronization now sends open rows first and falls back to closed rows when there are no open rows, including exit price/status/reason fields in the compact payload.
- Native iOS/watchOS simulator validation is still `BLOCKED - MACOS/XCODE REQUIRED`; Linux Swift tests are not native app launch validation.

## 2026-06-23 Shared Theme System Current Refresh

Scope: refreshed the generated web/Swift theme outputs from `/rebranding/nervyx-one-brand-tokens.json`, preserved the three-theme access model, removed generated public `Paper/live` wording from the execute module, and aligned web/PWA/social metadata with `Adaptive Market Intelligence with operator-gated execution controls.` This pass did not change order routing, exchange execution, risk calculations, strategy selection, PPO, MASA, trainer calculations, signal generation semantics, publisher semantics, Redis producer contracts, database records, or API field meanings.

| Area | Command | Collected | Passed | Failed | Errors | Skipped / did not run | Duration | Result |
|---|---|---:|---:|---:|---:|---:|---|---|
| Token generation | `npm run brand:tokens` | n/a | n/a | 0 | 0 | 0 | <1s | PASS: deterministic web/Swift outputs regenerated from checksum `36bf9013c0a13604cadc6ffa3429a875249359f36755bb1b9bf13f6baf49f2d7` |
| Token drift check | `npm run brand:tokens:check` | n/a | n/a | 0 | 0 | 0 | <1s | PASS |
| Theme drift Playwright spec | `npm run --prefix frontend test:e2e -- nervyx_theme_token_drift.spec.ts` | 1 | 1 | 0 | 0 | 0 | 0.27s | PASS |
| Branding/theme Playwright spec | `npm run --prefix frontend test:e2e -- nervyx_branding.spec.ts` | 3 | 3 | 0 | 0 | 0 | 1.7s | PASS after static `dist` rebuild made port `5173` serve the updated manifest |
| Frontend typecheck | `npm run --prefix frontend typecheck` | n/a | n/a | 0 | 0 | 0 | 6.4s | PASS |
| Frontend build | `npm run --prefix frontend build` | n/a | n/a | 0 | 0 | 0 | 13.0s | PASS with existing Vite chunk-size warning |
| Swift package tests | `swift test` from `mobile/` | 13 XCTest + 0 Swift Testing | 13 | 0 | 0 | 0 | 0.24s XCTest | PASS |
| Forbidden public phrase scan | `rg -n "Paper/live\|paper/live\|Live trading platform\|Live execution\|Trading live\|Paper only\|simulated" ...` | n/a | n/a | 0 | 0 | 0 | <1s | PASS for touched metadata and generated theme outputs |
| Diff whitespace/doc format checks | `git diff --check -- ...` and Python trailing-whitespace check | n/a | n/a | 0 | 0 | 0 | <1s | PASS |

Notes:

- `docs/nervyx-theme-system-final.md` now records the token source, generated outputs, theme access, Linux validation, and remaining visual/native gaps.
- Midnight Neural and Polar Signal are public/trader themes; Ops Terminal remains admin/superadmin-only presentation and does not grant authorization.
- Full chart/table visual coverage under every theme, increased contrast, Reduce Motion, Dynamic Type, VoiceOver, iPhone simulator, watchOS simulator, and TestFlight validation remain pending or blocked.

## 2026-06-23 Data Surface Inventory Baseline

Scope: added a read-only data-surface inventory generator for the data-preservation gate. The script parses current OpenAPI docs, frontend `useRealtimeResource` subscriptions, frontend TypeScript interfaces, Swift Codable models, and sampled public runtime snapshot JSON files. It does not import backend services, contact Redis, call exchanges, mutate runtime state, change API semantics, or touch execution/risk/strategy/trainer logic.

| Area | Command | Collected | Passed | Failed | Errors | Skipped / did not run | Duration | Result |
|---|---|---:|---:|---:|---:|---:|---|---|
| Python compile | `../.venv/bin/python -m py_compile scripts/nervyx_data_surface_inventory.py` | 1 | 1 | 0 | 0 | 0 | <1s | PASS |
| Data-surface inventory | `../.venv/bin/python scripts/nervyx_data_surface_inventory.py` | 118 OpenAPI operation responses, 91 OpenAPI component fields, 112 realtime resource subscriptions, 482 frontend interfaces, 5268 frontend interface fields, 76 Swift Codable models, 472 Swift fields, 500 runtime snapshot samples, 12247 sampled runtime top-level fields | n/a | 0 | 0 | 0 | <1s | PASS: wrote `artifacts/nervyx-data-surface-inventory.json` and summary |
| JSON validation | `python3 -m json.tool artifacts/nervyx-data-surface-inventory*.json` | 2 artifacts | 2 | 0 | 0 | 0 | <1s | PASS |

Notes:

- `docs/nervyx-data-parity-matrix.md` now points to the repeatable inventory artifacts and records the current counts.
- Data preservation remains `UNPROVEN`: each field still needs permission, unit, null behavior, freshness threshold, destination, formatter, and test-status classification.
- Rendered value validation remains pending because this pass did not execute live WebSocket frames, role-authenticated routes, iOS UI, watchOS UI, or per-field zero/null/stale scenarios.

## 2026-06-23 Positions Pricing And Reasoning Presentation

Scope: presentation/read-only changes only. No PPO, MASA, trainer calculations, strategy selection, signal generation semantics, publisher semantics, orchestrator decisions, risk calculations, live-gate state transitions, order routing, exchange execution, Redis producer contracts, database trading records, or API field meanings were changed.

| Area | Command | Collected | Passed | Failed | Errors | Skipped / did not run | Duration | Result |
|---|---|---:|---:|---:|---:|---:|---|---|
| Frontend typecheck | `npm run --prefix frontend typecheck` | TypeScript project | n/a | 0 | 0 | 0 | 5.6s | PASS |
| Frontend build | `npm run --prefix frontend build` | Vite production build | n/a | 0 | 0 | 0 | 12.7s | PASS with existing chunk-size warning |
| Focused Playwright | `npm run --prefix frontend test:e2e -- paper_positions_refresh_persistence.spec.ts` | 5 Chromium tests | 5 | 0 | 0 | 0 | 0.4s | PASS |
| Backend price adapter tests | `../.venv/bin/python -m pytest backend/tests/unit/api/test_paper_mark_price_freshness.py` | 23 pytest tests | 23 | 0 | 0 | 0 | 0.32s | PASS |
| Swift package tests | `swift test` from `mobile/` | 14 XCTest + 0 Swift Testing | 14 | 0 | 0 | 0 | 0.23s XCTest | PASS |
| Forbidden touched-copy scan | `rg -n "LIVE MODE\|Live Trading\|Live platform\|Live trading platform\|Paper only\|NO DATA" ...` | touched position files | 0 matches | 0 | 0 | 0 | <1s | PASS |

Notes:

- `/admin/paper-trading` no longer labels the surface `LIVE MODE`; it now separates `MARKET DATA LIVE` from `EXECUTION RESTRICTED`.
- Web presentation adapters now reject non-positive entry, close/exit, and mark prices as unavailable instead of rendering them as real prices.
- iOS `PositionsView` now renders non-positive entry, close/exit, and mark prices as `Unavailable`.
- `/admin/paper-trading` open positions and history are now card-based evidence panels with AI Basis blocks sourced from `decision_reasoning`, `signal_id`, and `prediction_id`.
- Full field-level live WebSocket validation across every route and native simulator validation remain pending.

## 2026-06-23 Lane / OpenAPI / Data-Surface Evidence Refresh

Scope: documentation/evidence refresh only. This pass regenerated the lane-isolation inventory, protected-lane hashes, OpenAPI compatibility artifacts, and data-surface inventory from the current dirty tree. It did not change order routing, exchange execution, risk calculations, strategy selection, PPO, MASA, trainer calculations, signal generation semantics, publisher semantics, Redis producer contracts, database trading records, or API field meanings.

| Area | Command | Collected | Passed | Failed | Errors | Skipped / did not run | Duration | Result |
|---|---|---:|---:|---:|---:|---:|---|---|
| Lane inventory script compile | `../.venv/bin/python -m py_compile scripts/nervyx_lane_isolation_inventory.py scripts/nervyx_openapi_compatibility.py scripts/nervyx_data_surface_inventory.py` | 3 scripts | 3 | 0 | 0 | 0 | <1s | PASS |
| Lane isolation inventory | `../.venv/bin/python scripts/nervyx_lane_isolation_inventory.py` | 470788 changed-path records; 155 base protected hashes; 324 current protected hashes; 180 protected diffs | n/a | 0 | 0 | 0 | 4.1s | PASS as evidence generation; LANE ISOLATION remains UNPROVEN |
| OpenAPI compatibility refresh | `../.venv/bin/python scripts/nervyx_openapi_compatibility.py` | current 118 operations; shimmed baseline 65 operations; 0 removed operations; 0 removed fields; 0 type changes; 0 security metadata changes | n/a | 0 | 0 | 0 | 1.9s | PARTIAL: status `PARTIAL_SHIMMED_BASE_UNPROVEN` |
| Data-surface inventory refresh | `../.venv/bin/python scripts/nervyx_data_surface_inventory.py` | 118 OpenAPI operation responses, 91 component fields, 112 realtime resource subscriptions, 482 frontend interfaces, 5268 frontend interface fields, 76 Swift Codable models, 472 Swift fields, 500 runtime snapshot samples, 12247 sampled runtime top-level fields | n/a | 0 | 0 | 0 | <1s | PASS as inventory generation; DATA PRESERVATION remains UNPROVEN |
| JSON validation | `python3 -m json.tool ...summary/diff artifacts...` | 4 artifacts | 4 | 0 | 0 | 0 | <1s | PASS |
| Hash/checksum proof | `sha256sum docs/nervyx-protected-lanes-base.sha256 docs/nervyx-protected-lanes-current.sha256 artifacts/nervyx-protected-lane-hash-diff.json artifacts/nervyx-protected-lane-modified-diffs.patch artifacts/nervyx-changed-file-inventory.jsonl.gz artifacts/nervyx-openapi-compatibility-summary.json artifacts/nervyx-data-surface-inventory-summary.json` | 7 artifacts | 7 | 0 | 0 | 0 | <1s | PASS |
| Diff whitespace check | `git diff --check -- ...lane/openapi/data docs and artifacts...` | refreshed evidence files | n/a | 0 | 0 | 0 | <1s | PASS |

Current refreshed evidence:

- Branch: `codex/pipeline-trust-refresh`
- HEAD: `5b0a4997dae6ab50b1f3aba3327ad9959e126247`
- Rebrand merge base: `680ddfb12d2810d950f7a465a39a4fb8a77ec205`
- Changed-path inventory checksum: `57d39ba06743436428b8195cb733e785c11eed4bd33434e1b5f0cece1be5e79d`
- Protected base hash file checksum: `ec6d130a54648aa7f56beaf00819833ad2fe811a184b16a93f6d5fc7a366fbc9`
- Protected current hash file checksum: `1761227974c70e512b9f7dc61b5f83513a84434c06e6c2297e78064cf9fce41a`
- Protected diff artifact checksum: `136343449835d8a3d57bb7ff0a0f55dedc20b0624a86f4e72fdf8823121813e8`
- Modified protected diff patch checksum: `6a0e7315c7c1e9a614ccd41db7a746c5f60de328d831f0e9aae21c76bed045fc`

Blocking facts:

- Lane isolation remains `UNPROVEN`: protected diffs are `169 added` and `11 modified`, with review classes `API_SURFACE_REQUIRES_REVIEW`, `CLI_OR_PUBLISHER_REQUIRES_REVIEW`, `DECISION_COMPOSITION_REQUIRES_REVIEW`, and `SERVICE_LOGIC_REQUIRES_REVIEW`.
- OpenAPI compatibility remains `PARTIAL_SHIMMED_BASE_UNPROVEN` because the raw merge-base OpenAPI capture fails and the baseline needs shims.
- Data preservation remains `IN_PROGRESS_NOT_FULL_PARITY` because inventory exists, but field-level permission/unit/null/freshness/destination/formatter/test classification is not yet 100%.
- Native iOS/watchOS and TestFlight validation remain blocked by the missing macOS/Xcode/App Store Connect lane.

## 2026-06-23 Role Audit And Position Price Fallback Continuation

Scope: fixed remaining rendered legacy/live wording in operator evidence surfaces, hardened admin shell access for system/admin routes, refreshed the role-route audit artifact, and tightened read-only position price presentation so zero entry/exit/mark prices cannot mask positive fallback prices. Added inline iOS position reasoning summaries sourced from existing `decision_reasoning`, `signal_id`, and `prediction_id` fields. This pass did not change order routing, exchange execution, risk calculations, strategy selection, PPO, MASA, trainer calculations, signal generation semantics, publisher semantics, Redis producer contracts, database trading records, or API field meanings.

| Area | Command | Collected | Passed | Failed | Errors | Skipped / did not run | Duration | Result |
|---|---|---:|---:|---:|---:|---:|---|---|
| Frontend typecheck | `npm run --prefix frontend typecheck` | TypeScript project | n/a | 0 | 0 | 0 | 5-7s | PASS |
| Frontend build | `npm run --prefix frontend build` | Vite production build | n/a | 0 | 0 | 0 | 12.3s | PASS with existing Vite chunk-size warning |
| Direct old-copy route probe | `node - <<'NODE' ... chromium routes ... NODE` | 5 routes | 5 | 0 | 0 | 0 | 8.3s | PASS: no matches for old live/control-plane/paper/no-data wording on probed routes |
| Backend test path attempt | `PYTHONPATH=/home/wali/Desktop/AI\ BOT\ REBUILD/v2/backend pytest backend/tests/unit/api/test_paper_mark_price_freshness.py -q` | n/a | n/a | 1 | 0 | 0 | <1s | FAILED: `pytest` not on PATH |
| Backend focused test before source fix | `../.venv/bin/python -m pytest backend/tests/unit/api/test_paper_mark_price_freshness.py -q` | 24 | 23 | 1 | 0 | 0 | 0.34s | FAILED: recovered `paper_exit_price` was relabeled as `exit_price` |
| Backend focused test after source fix | `../.venv/bin/python -m pytest backend/tests/unit/api/test_paper_mark_price_freshness.py -q` | 24 | 24 | 0 | 0 | 0 | 0.34s | PASS |
| Swift package tests | `swift test` from `mobile/` | 14 XCTest + 0 Swift Testing | 14 | 0 | 0 | 0 | 0.13s XCTest | PASS |
| Stale role audit run | `npm run --prefix frontend test:e2e -- nervyx_role_route_audit.spec.ts --project=chromium` | 1 Chromium test | 0 | 0 | 0 | 1 interrupted | 8.9m | INTERRUPTED because it started before the latest bundle rebuild |
| Clean role audit run | `npm run --prefix frontend test:e2e -- nervyx_role_route_audit.spec.ts --project=chromium` | 1 Chromium test | 1 | 0 | 0 | 0 | 9.2m | PASS |
| Role audit JSON validation | `python3 -m json.tool artifacts/nervyx-role-route-audit.json` | 1 artifact | 1 | 0 | 0 | 0 | <1s | PASS |

Current role-route audit artifact:

- `artifacts/nervyx-role-route-audit.json`
- Generated at: `2026-06-23T04:49:08.310Z`
- Rows: `360`
- Screenshots: `360`
- Status: `IN_PROGRESS_PARTIAL_FIXTURE_AUDIT`
- Final gate proof: `false`
- Auth fixture kind: `playwright_api_auth_me_fixture_not_backend_login`
- Old branding rows: `0`
- Unauthorized content leakage rows: `0`
- WebSocket rows: `241`
- Rows with frames: `209`
- Failed-request rows: `127`
- Console-error rows: `84`
- Horizontal-overflow rows: `5`
- Clipped-text rows: `124`

Notes:

- The role audit is cleaner, but it remains partial because it does not prove real backend-authenticated login sessions for guest/viewer/trader/admin/superadmin.
- Position price adapters now choose the first positive entry, exit/close, and mark price. A literal `0` is treated as unavailable unless the contract explicitly provides a valid positive fallback.
- The source for recovered close prices is now preserved, including `paper_exit_price` when `exit_price` is zero.
- iOS position rows now show the AI decision reason/risk/signal summary inline; the detail view continues to show the full AI reasoning card.
- Native iOS/watchOS simulator validation and TestFlight remain `BLOCKED - MACOS/XCODE REQUIRED`.

## 2026-06-23 Backend-Authenticated Role Audit

Scope: added backend-authenticated mode to the NERVYX role-route audit and a local isolated audit runner. The runner creates a temporary auth store, seeds audit-only users for viewer/trader/admin/superadmin, verifies guest as a backend `401`, launches an isolated FastAPI backend, serves the built SPA through that backend, and runs the full role-route audit without `?role=` or `/api/auth/me` route fixtures. This pass did not modify the real auth store and did not change order routing, exchange execution, risk calculations, strategy selection, PPO, MASA, trainer calculations, signal generation semantics, publisher semantics, Redis producer contracts, database trading records, or API field meanings.

| Area | Command | Collected | Passed | Failed | Errors | Skipped / did not run | Duration | Result |
|---|---|---:|---:|---:|---:|---:|---|---|
| Runner syntax check | `node --check scripts/nervyx_backend_auth_role_route_audit.mjs` | 1 script | 1 | 0 | 0 | 0 | <1s | PASS |
| Frontend typecheck | `npm run --prefix frontend typecheck` | TypeScript project | n/a | 0 | 0 | 0 | 6.2s | PASS |
| First backend launch attempt | `node scripts/nervyx_backend_auth_role_route_audit.mjs` | n/a | 0 | 1 | 0 | 0 | ~60s | FAILED: Uvicorn target used `app.main:app`; backend exposes `create_app()` |
| Vite-backed audit attempt | `node scripts/nervyx_backend_auth_role_route_audit.mjs` | n/a | 0 | 1 | 0 | 0 | ~42s | FAILED: host inotify watcher limit `ENOSPC` from Vite dev server |
| Backend-SPA authenticated route audit | `node scripts/nervyx_backend_auth_role_route_audit.mjs` | 1 Playwright Chromium test, 360 route-role rows | 1 | 0 | 0 | 0 | 5.6m | PASS |
| Artifact summary read | `node - <<'NODE' ... artifacts/nervyx-role-route-audit-backend-auth.json ... NODE` | 1 artifact | 1 | 0 | 0 | 0 | <1s | PASS |

Current backend-authenticated role-route audit artifact:

- `artifacts/nervyx-role-route-audit-backend-auth.json`
- Generated at: `2026-06-23T14:17:03.925Z`
- Rows: `360`
- Screenshots: `360`
- Status: `IN_PROGRESS_BACKEND_AUTH_ROUTE_AUDIT`
- Final goal proof: `false`
- Auth fixture kind: `backend_login_cookie_session_isolated_user_store`
- Auth backend login gate proven: `true`
- Guest proof: `/api/auth/me` returned `401`
- Viewer/trader/admin/superadmin proof: `POST /api/auth/login` returned `200`, then `/api/auth/me` returned the expected role
- Old branding rows: `0`
- Unauthorized content leakage rows: `0`
- WebSocket rows: `239`
- Rows with frames: `221`
- Failed-request rows: `91`
- Console-error rows: `72`
- Horizontal-overflow rows: `5`
- Clipped-text rows: `130`

Notes:

- The prior fixture-backed role audit remains available at `artifacts/nervyx-role-route-audit.json`, but backend-authenticated proof now lives in `artifacts/nervyx-role-route-audit-backend-auth.json`.
- Backend-authenticated role coverage is improved, but the overall NERVYX ONE goal remains `IN PROGRESS`.
- Runtime WebSocket activity still does not prove field-level validity. The rendered-field validation matrix must still classify each displayed value for raw value, timestamp, freshness, valid zero/null/missing/stale behavior, and fallback use.
- Native iOS/watchOS simulator validation and TestFlight remain `BLOCKED - MACOS/XCODE REQUIRED`.

## 2026-06-23 Backend-Authenticated Role Audit Classification Refresh

Scope: refined the backend-authenticated role-route audit classification so
navigation-cancelled requests and deliberate guest-auth challenges are recorded
separately from real failed requests and real console errors. This pass did not
modify live execution behavior, strategy logic, PPO, MASA, trainer calculations,
risk logic, order routing, exchange execution, Redis producer contracts,
database trading records, or API field meanings.

| Area | Command | Collected | Passed | Failed | Errors | Skipped / did not run | Duration | Result |
|---|---|---:|---:|---:|---:|---:|---|---|
| Frontend typecheck | `npm run --prefix frontend typecheck` | TypeScript project | n/a | 0 | 0 | 0 | 6.4s | PASS |
| Runner syntax check | `node --check scripts/nervyx_backend_auth_role_route_audit.mjs` | 1 script | 1 | 0 | 0 | 0 | <1s | PASS |
| Backend-SPA authenticated route audit | `node scripts/nervyx_backend_auth_role_route_audit.mjs` | 1 Playwright Chromium test, 360 route-role rows | 1 | 0 | 0 | 0 | 5.5m | PASS |
| Backend-auth artifact JSON validation | `python3 -m json.tool artifacts/nervyx-role-route-audit-backend-auth.json` | 1 artifact | 1 | 0 | 0 | 0 | <1s | PASS |

Current refined backend-authenticated role-route audit artifact:

- `artifacts/nervyx-role-route-audit-backend-auth.json`
- Generated at: `2026-06-23T14:27:41.244Z`
- Rows: `360`
- Screenshots: `360`
- Status: `IN_PROGRESS_BACKEND_AUTH_ROUTE_AUDIT`
- Final gate proof: `false`
- Auth fixture kind: `backend_login_cookie_session_isolated_user_store`
- Auth backend login gate proven: `true`
- Guest proof: `/api/auth/me` returned `401`
- Viewer/trader/admin/superadmin proof: `POST /api/auth/login` returned `200`, then `/api/auth/me` returned the expected role
- Old branding rows: `0`
- Unauthorized content leakage rows: `0`
- WebSocket rows: `239`
- Rows with frames: `228`
- Failed-request rows: `0`
- Failed request count: `0`
- Navigation-aborted request rows: `80`
- Navigation-aborted request count: `281`
- Console-error rows: `0`
- Console error count: `0`
- Expected guest-auth console challenge rows: `72`
- Expected guest-auth console challenge count: `73`
- Horizontal-overflow rows: `5`
- Clipped-text rows: `130`

Notes:

- Navigation-aborted requests are recorded separately because they are route-transition cancellations during the audit, not backend request failures.
- Guest-auth console challenges are expected because the guest role intentionally proves unauthenticated `/api/auth/me` returns `401`.
- The remaining web audit defects are presentation and field-validity work: `5` overflow rows, `130` clipped-text rows, and unresolved per-field stale/missing/zero/null validation.
- Native iOS/watchOS simulator validation, TestFlight, full field parity, full-suite testing, OpenAPI compatibility proof, and protected-lane isolation remain incomplete or blocked.

## 2026-06-23 Backend-Authenticated Role Audit Layout Refresh

Scope: scoped web presentation changes only. This pass added report-center wrapping/layout styles and tightened operator-evidence metric wrapping so long values do not create horizontal overflow. It did not modify live execution behavior, strategy logic, PPO, MASA, trainer calculations, risk logic, order routing, exchange execution, Redis producer contracts, database trading records, or API field meanings.

| Area | Command | Collected | Passed | Failed | Errors | Skipped / did not run | Duration | Result |
|---|---|---:|---:|---:|---:|---:|---|---|
| Frontend typecheck | `npm run --prefix frontend typecheck` | TypeScript project | n/a | 0 | 0 | 0 | 6.0s | PASS |
| Runner syntax check | `node --check scripts/nervyx_backend_auth_role_route_audit.mjs` | 1 script | 1 | 0 | 0 | 0 | <1s | PASS |
| Backend-auth artifact JSON validation | `python3 -m json.tool artifacts/nervyx-role-route-audit-backend-auth.json` | 1 artifact | 1 | 0 | 0 | 0 | <1s | PASS |
| Frontend build | `npm run --prefix frontend build` | Vite production build | n/a | 0 | 0 | 0 | 12.8s | PASS with existing Vite chunk-size warning |
| Backend-SPA authenticated route audit | `node scripts/nervyx_backend_auth_role_route_audit.mjs` | 1 Playwright Chromium test, 360 route-role rows | 1 | 0 | 0 | 0 | 5.5m | PASS |

Current layout-refreshed backend-authenticated role-route audit artifact:

- `artifacts/nervyx-role-route-audit-backend-auth.json`
- Generated at: `2026-06-23T14:39:00.391Z`
- Rows: `360`
- Screenshots: `360`
- Status: `IN_PROGRESS_BACKEND_AUTH_ROUTE_AUDIT`
- Final gate proof: `false`
- Auth fixture kind: `backend_login_cookie_session_isolated_user_store`
- Auth backend login gate proven: `true`
- Guest proof: `/api/auth/me` returned `401`
- Viewer/trader/admin/superadmin proof: `POST /api/auth/login` returned `200`, then `/api/auth/me` returned the expected role
- Old branding rows: `0`
- Unauthorized content leakage rows: `0`
- WebSocket rows: `239`
- Rows with frames: `230`
- Failed-request rows: `0`
- Failed request count: `0`
- Navigation-aborted request rows: `82`
- Navigation-aborted request count: `298`
- Console-error rows: `0`
- Console error count: `0`
- Expected guest-auth console challenge rows: `72`
- Expected guest-auth console challenge count: `73`
- Horizontal-overflow rows: `0`
- Clipped-text rows: `132`

Notes:

- Horizontal overflow improved from `5` rows to `0` rows in the backend-authenticated audit.
- Residual clipped text remains and is concentrated in `/admin/evidence`, `/portfolio`, `/portfolio/executions`, and related legacy redirects.
- WebSocket activity still does not prove every displayed field is semantically valid. Rendered values still need route/role/component/field/source/timestamp/age/unit/zero/null/missing/stale/fallback classification.
- Native iOS/watchOS simulator validation, TestFlight, full field parity, full-suite testing, OpenAPI compatibility proof, and protected-lane isolation remain incomplete or blocked.

## 2026-06-23 Backend-Authenticated Role Audit Clipping Closure

Scope: scoped web presentation cleanup only. This pass fixed residual clipped
labels in card/table/status/source surfaces, including the trade intelligence
status pill. It did not modify live execution behavior, strategy logic, PPO,
MASA, trainer calculations, risk logic, live-gate transitions, order routing,
exchange execution, Redis producer contracts, database trading records, or API
field meanings.

| Area | Command | Collected | Passed | Failed | Errors | Skipped / did not run | Duration | Result |
|---|---|---:|---:|---:|---:|---:|---|---|
| Frontend typecheck | `npm run --prefix frontend typecheck` | TypeScript project | n/a | 0 | 0 | 0 | ~6s | PASS |
| Diff whitespace check | `git diff --check -- frontend/src/components/trade/TradeIntelligenceBar.tsx frontend/src/styles/layout.css frontend/src/styles.css frontend/src/styles/tables.css frontend/src/pages/positions/index.tsx frontend/src/pages/executions/index.tsx frontend/src/pages/history/index.tsx frontend/src/pages/risk-control/index.tsx frontend/src/pages/trainer-admin/index.tsx frontend/src/components/trading/AdaptiveCapitalTelemetryPanel.tsx frontend/src/components/data/SourceBadge.tsx frontend/tests/e2e/nervyx_role_route_audit.spec.ts` | scoped changed files | n/a | 0 | 0 | 0 | <1s | PASS |
| Frontend build | `npm run --prefix frontend build` | Vite production build | n/a | 0 | 0 | 0 | ~13s | PASS with existing Vite chunk-size warning |
| Backend-SPA authenticated route audit | `node scripts/nervyx_backend_auth_role_route_audit.mjs` | 1 Playwright Chromium test, 360 route-role rows | 1 | 0 | 0 | 0 | 5.6m | PASS |
| Backend-auth artifact JSON validation | `python3 -m json.tool artifacts/nervyx-role-route-audit-backend-auth.json` | 1 artifact | 1 | 0 | 0 | 0 | <1s | PASS |

Current clipping-closed backend-authenticated role-route audit artifact:

- `artifacts/nervyx-role-route-audit-backend-auth.json`
- Generated at: `2026-06-23T15:27:43.173Z`
- Rows: `360`
- Screenshots: `360`
- Status: `IN_PROGRESS_BACKEND_AUTH_ROUTE_AUDIT`
- Final gate proof: `false`
- Auth fixture kind: `backend_login_cookie_session_isolated_user_store`
- Auth backend login gate proven: `true`
- Guest proof: `/api/auth/me` returned `401`
- Viewer/trader/admin/superadmin proof: `POST /api/auth/login` returned `200`, then `/api/auth/me` returned the expected role
- Old branding rows: `0`
- Unauthorized content leakage rows: `0`
- WebSocket rows: `239`
- Rows with frames: `229`
- Failed-request rows: `0`
- Failed request count: `0`
- Navigation-aborted request rows: `92`
- Navigation-aborted request count: `333`
- Console-error rows: `0`
- Console error count: `0`
- Expected guest-auth console challenge rows: `72`
- Expected guest-auth console challenge count: `73`
- Horizontal-overflow rows: `0`
- Clipped-text rows: `0`

Notes:

- Residual presentation defects from the previous backend-auth audit are cleared in this artifact: clipped text moved from `132` rows to `24`, then `15`, then `0`.
- Paper position entry/close/mark price validation and AI reasoning click-through for active/open/closed/historical positions are captured as open rendered-field requirements in `docs/nervyx-rendered-field-validation.md`. Earlier focused backend/web/Swift checks cover a slice of that behavior, but full website/app field-level proof remains pending.
- WebSocket activity still does not prove every displayed field is semantically valid. Rendered values still need route/role/component/field/source/timestamp/age/unit/zero/null/missing/stale/fallback classification.
- Native iOS/watchOS simulator validation, TestFlight, full field parity, full-suite testing, OpenAPI compatibility proof, and protected-lane isolation remain incomplete or blocked.

## 2026-06-23 iOS Paper Position Preview Price/Reasoning Continuation

Scope: iOS presentation/read-only app slice only. This pass prevents the paper
execution summary preview from rendering a decoded non-positive mark price as an
available value, surfaces available signal/prediction reasoning on preview rows,
and links each preview row to the existing position detail reasoning view. It
does not modify live execution behavior, strategy logic, PPO, MASA, trainer
calculations, risk logic, live-gate transitions, order routing, exchange
execution, Redis producer contracts, database trading records, or API field
meanings.

| Area | Command | Collected | Passed | Failed | Errors | Skipped / did not run | Duration | Result |
|---|---|---:|---:|---:|---:|---:|---|---|
| Swift package build | `swift build` | SwiftPM package | n/a | 0 | 0 | 0 | 0.20s | PASS |
| Swift package tests | `swift test` | 15 XCTest + 0 Swift Testing | 15 | 15 | 0 | 0 | 0 | 0.131s XCTest | PASS |
| Source guard scan | `rg -n "pos\\.mark_price\\.map|paperPositionPriceText|paperPositionReasoningText|NavigationLink\\(destination: PositionDetailView\\(position: pos\\)" mobile/Sources/AIBotV2/Views/Paper/PaperTradingView.swift mobile/Tests/AIBotV2Tests/AIBotV2CoreTests.swift` | 2 files | n/a | 0 | 0 | 0 | <1s | PASS: old direct formatter absent from source and new guarded formatter/link/reasoning strings present |
| Backend focused paper price/reasoning tests | `/home/wali/Desktop/AI\ BOT\ REBUILD/.venv/bin/python -m pytest backend/tests/unit/api/test_paper_mark_price_freshness.py -q` | 24 | 24 | 0 | 0 | 0 | 0.33s | PASS |
| Diff whitespace check | `git diff --check -- mobile/Sources/AIBotV2/Views/Paper/PaperTradingView.swift mobile/Tests/AIBotV2Tests/AIBotV2CoreTests.swift` | 2 files | n/a | 0 | 0 | 0 | <1s | PASS |

Notes:

- This is not native iOS simulator validation. It proves SwiftPM/source behavior on Linux only.
- `PaperTradingView` now uses `paperPositionPriceText` for preview mark prices, so `0`, negative, null, and missing marks display as `Unavailable`.
- Paper preview rows now navigate to `PositionDetailView(position:)`, reusing the existing detailed AI reasoning card for actual `decision_reasoning` supplied by the backend/mobile compact response.
- Full app-wide card/panel expansion, native iPhone/watchOS screenshots, Dynamic Type/VoiceOver/no-clipping proof, and TestFlight readiness remain incomplete or blocked.

## 2026-06-23 Mobile Paper Summary Realtime Pricing Continuation

Scope: read-only mobile compact adapter and iOS presentation slice only. This
pass reuses the existing paper position enrichment logic for
`/api/v2/mobile/paper-summary` preview rows, adds optional Swift decoding for
the existing `PositionPricing` shape, and shows compact mark-pricing metrics in
the iPhone execution screen. It does not modify live execution behavior,
strategy logic, PPO, MASA, trainer calculations, risk logic, live-gate
transitions, order routing, exchange execution, Redis producer contracts,
database trading records, or existing API field meanings.

| Area | Command | Collected | Passed | Failed | Errors | Skipped / did not run | Duration | Result |
|---|---|---:|---:|---:|---:|---:|---|---|
| Backend syntax | `/home/wali/Desktop/AI\ BOT\ REBUILD/.venv/bin/python -m py_compile backend/app/api/v2/mobile.py backend/app/api/v2/market_contracts.py` | 2 files | 2 | 0 | 0 | 0 | <1s | PASS |
| Backend focused paper price/reasoning tests | `/home/wali/Desktop/AI\ BOT\ REBUILD/.venv/bin/python -m pytest backend/tests/unit/api/test_paper_mark_price_freshness.py -q` | 25 | 25 | 0 | 0 | 0 | 0.36s | PASS |
| Swift package build | `swift build` | SwiftPM package | n/a | 0 | 0 | 0 | 1.73s | PASS |
| Swift package tests | `swift test` | 16 XCTest + 0 Swift Testing | 16 | 0 | 0 | 0 | 0.129s XCTest | PASS |
| Diff whitespace check | `git diff --check -- backend/app/api/v2/mobile.py backend/tests/unit/api/test_paper_mark_price_freshness.py mobile/Sources/AIBotV2/Models/APIModels.swift mobile/Sources/AIBotV2Core/Models.swift mobile/Sources/AIBotV2/Views/Paper/PaperTradingView.swift mobile/Tests/AIBotV2Tests/AIBotV2CoreTests.swift` | 6 files | n/a | 0 | 0 | 0 | <1s | PASS |

Notes:

- `/api/v2/mobile/paper-summary` preview rows now use read-only realtime mark enrichment before compacting positions. The focused backend test proves a zero entry/mark input is replaced by positive sourced entry/mark values when available, and carries matching signal reasoning.
- `MobilePaperSummary.position_pricing` is optional for backward compatibility and reuses the existing Swift `PositionPricing` model.
- `PaperTradingView` now shows compact `MARKS`, `STALE`, and `MISSING` mark-pricing counts plus open notional and unrealized PnL from backend pricing metrics.
- This remains Linux SwiftPM/source validation only. Native iPhone/watchOS simulator rendering, accessibility, screenshots, and TestFlight processing remain blocked or incomplete.

## 2026-06-23 Lane Isolation Evidence Refresh

Scope: evidence refresh only. This pass reran the read-only lane inventory
script after the mobile paper-summary work so changed-file classification,
protected hashes, and protected diff artifacts reflect the current worktree. It
does not modify live execution behavior, strategy logic, PPO, MASA, trainer
calculations, risk logic, live-gate transitions, order routing, exchange
execution, Redis producer contracts, database trading records, or API field
meanings.

| Area | Command | Collected | Passed | Failed | Errors | Skipped / did not run | Duration | Result |
|---|---|---:|---:|---:|---:|---:|---|---|
| Lane inventory refresh | `/home/wali/Desktop/AI\ BOT\ REBUILD/.venv/bin/python scripts/nervyx_lane_isolation_inventory.py` | 471573 changed status records; 180 protected diffs | n/a | 0 | 0 | 0 | 4.2s | PASS as evidence generation; lane isolation remains UNPROVEN |
| JSON artifact validation | `python3 -m json.tool artifacts/nervyx-changed-file-classification-summary.json ...` | 2 JSON artifacts | 2 | 0 | 0 | 0 | <1s | PASS |
| Current-slice classification check | `python3 - <<'PY' ... artifacts/nervyx-changed-file-inventory.jsonl.gz ...` | 13 requested current-slice records | 13 | 0 | 0 | 0 | <1s | PASS |
| Lane artifact summary check | `node -e "... artifacts/nervyx-changed-file-classification-summary.json ... artifacts/nervyx-protected-lane-hash-diff.json ..."` | 2 artifacts | 2 | 0 | 0 | 0 | <1s | PASS |
| Diff whitespace check | `git diff --check -- docs/nervyx-lane-isolation-final.md docs/nervyx-changed-file-classification.md docs/nervyx-protected-lanes-base.sha256 docs/nervyx-protected-lanes-current.sha256 artifacts/nervyx-changed-file-classification-summary.json artifacts/nervyx-protected-lane-hash-diff.json artifacts/nervyx-protected-lane-modified-diffs.patch` | refreshed docs/artifacts | n/a | 0 | 0 | 0 | <1s | PASS |

Current refreshed lane evidence:

- Generated at: `2026-06-23T17:05:43.471651+00:00`
- Branch: `codex/pipeline-trust-refresh`
- HEAD: `5b0a4997dae6ab50b1f3aba3327ad9959e126247`
- Merge base: `680ddfb12d2810d950f7a465a39a4fb8a77ec205`
- Changed-file status records: `471573`
- Inventory checksum: `584e769afde0b5d658c2b66d744da9c405dc26122c1cffc9296b06e4ba806941`
- Protected diff count: `180`
- Protected status counts: `169 added`, `11 modified`
- Protected review counts: `3 API_SURFACE_REQUIRES_REVIEW`, `59 CLI_OR_PUBLISHER_REQUIRES_REVIEW`, `4 DECISION_COMPOSITION_REQUIRES_REVIEW`, `114 SERVICE_LOGIC_REQUIRES_REVIEW`

Current-slice classifications from the refreshed compressed inventory:

- `v2/backend/app/api/v2/mobile.py`: `READ_ONLY_API_ADAPTER`
- `v2/backend/tests/unit/api/test_paper_mark_price_freshness.py`: `TEST`
- `v2/mobile/Sources/AIBotV2/Models/APIModels.swift`: `IOS_PRESENTATION`
- `v2/mobile/Sources/AIBotV2Core/Models.swift`: `IOS_PRESENTATION`
- `v2/mobile/Sources/AIBotV2/Views/Paper/PaperTradingView.swift`: `IOS_PRESENTATION`, `REALTIME_TRANSPORT_ADAPTER`
- `v2/mobile/Tests/AIBotV2Tests/AIBotV2CoreTests.swift`: `IOS_PRESENTATION`, `TEST`

Notes:

- Lane isolation remains `UNPROVEN`. The refreshed protected hash artifacts still show 180 protected-lane diffs from the rebrand merge base, and those diffs must be individually identified, diffed, justified, and tested before isolation can be claimed.
- The current mobile paper-summary slice is classified as read-only API adapter / iOS presentation / realtime presentation adapter / test, not as a protected-lane exception by the inventory script.

## 2026-06-23 OpenAPI Compatibility Refresh

Scope: OpenAPI evidence refresh after the mobile paper-summary compact response
work. This pass regenerated before/after OpenAPI artifacts and static route
fallback inventories. It did not modify route handlers, endpoint behavior,
permissions, live execution behavior, strategy logic, PPO, MASA, trainer
calculations, risk logic, live-gate transitions, order routing, exchange
execution, Redis producer contracts, database trading records, or API field
meanings.

| Area | Command | Collected | Passed | Failed | Errors | Skipped / did not run | Duration | Result |
|---|---|---:|---:|---:|---:|---:|---|---|
| OpenAPI capture/diff | `/home/wali/Desktop/AI\ BOT\ REBUILD/.venv/bin/python scripts/nervyx_openapi_compatibility.py` | current 114 paths / 118 operations; shimmed baseline 65 paths / 65 operations | n/a | 0 | 0 | 0 | 1.9s | PARTIAL: current capture passed; raw baseline failed; shimmed baseline passed |
| OpenAPI JSON validation | `python3 -m json.tool docs/nervyx-openapi-before.json ... artifacts/nervyx-openapi-compatibility-summary.json` | 5 JSON artifacts | 5 | 0 | 0 | 0 | <1s | PASS |
| OpenAPI summary check | `node -e "... artifacts/nervyx-openapi-compatibility-summary.json ..."` | 1 summary | 1 | 0 | 0 | 0 | <1s | PASS |
| Diff whitespace check | `git diff --check -- scripts/nervyx_openapi_compatibility.py docs/nervyx-openapi-before.json docs/nervyx-openapi-after.json docs/nervyx-openapi-compatibility-report.md artifacts/nervyx-openapi-before-static-routes.json artifacts/nervyx-openapi-after-static-routes.json artifacts/nervyx-openapi-compatibility-summary.json` | OpenAPI docs/artifacts | n/a | 0 | 0 | 0 | <1s | PASS |

Current refreshed OpenAPI evidence:

- Generated at: `2026-06-23T17:08:34.107128Z`
- Status: `PARTIAL_SHIMMED_BASE_UNPROVEN`
- Current OpenAPI capture: `PASS`, `114` paths, `118` operations
- Baseline raw capture: `FAIL`
- Baseline shimmed capture: `PASS`, `65` paths, `65` operations
- Removed operations from captured baseline: `0`
- Removed component fields: `0`
- Component type changes: `0`
- Operation security changes: `0`
- Static fallback removed route keys: `0`

Notes:

- OpenAPI compatibility remains `UNPROVEN`. The archived merge-base still requires temporary shims for missing route/support modules, so the comparison is useful regression evidence but not complete compatibility proof.
- The current mobile compact response change is not fully represented as a typed OpenAPI schema because these mobile endpoints return dictionaries rather than explicit Pydantic response models.

## 2026-06-23 Paper Position Pricing/Reasoning Realtime Continuation

Scope: read-only API adapter, realtime resource transport, and iOS
presentation tests only. This pass fixes the observed paper position zero
entry/close/mark display path by selecting positive sourced quantity/price
aliases, attaching position reasoning from actual signal/adaptive-allocation or
closed-trade ledger fields already present in Redis, removing broad Redis
`SCAN` from request-time position reasoning, and limiting closed-trade
projection to the latest response window. It does not modify live execution
behavior, strategy logic, PPO, MASA, trainer calculations, risk logic,
live-gate transitions, order routing, exchange execution, Redis producer
contracts, database trading records, or existing API field meanings.

| Area | Command | Collected | Passed | Failed | Errors | Skipped / did not run | Duration | Result |
|---|---|---:|---:|---:|---:|---:|---|---|
| Backend syntax | `/home/wali/Desktop/AI\ BOT\ REBUILD/.venv/bin/python -m py_compile backend/app/api/v2/mobile.py backend/app/api/v2/market_contracts.py` | 2 files | 2 | 0 | 0 | 0 | <1s | PASS |
| Backend focused paper price/reasoning tests | `/home/wali/Desktop/AI\ BOT\ REBUILD/.venv/bin/python -m pytest backend/tests/unit/api/test_paper_mark_price_freshness.py -q` | 30 | 30 | 0 | 0 | 0 | 0.32s | PASS |
| Diff whitespace check | `git diff --check -- backend/app/api/v2/mobile.py backend/app/api/v2/market_contracts.py backend/tests/unit/api/test_paper_mark_price_freshness.py mobile/Sources/AIBotV2/Views/Paper/PaperTradingView.swift mobile/Tests/AIBotV2Tests/AIBotV2CoreTests.swift` | 5 files | n/a | 0 | 0 | 0 | <1s | PASS |
| Direct live Redis timing | direct Python call to `get_mobile_positions()` and `get_paper_status(None)` | live Redis payloads | n/a | 0 | 0 | 0 | `1.097s` mobile positions; `0.35s` paper status | PASS |
| Local service health | `curl -sS -w ... http://127.0.0.1:5173/health` | 1 endpoint | 1 | 0 | 0 | 0 | `0.036384s` | PASS |
| Local mobile positions HTTP | `curl -sS --max-time 10 -w ... http://127.0.0.1:5173/api/v2/mobile/positions` | 4 open, 50 closed preview, 200 historical | n/a | 0 | 0 | 0 | `0.851011s` | PASS |
| Local paper status HTTP | `curl -sS --max-time 10 -w ... http://127.0.0.1:5173/api/v2/paper/status` | 4 open, 200 closed trades | n/a | 0 | 0 | 0 | `2.293434s` | PASS |
| Resource WebSocket probes | Python `websockets` probe for `/api/v2/mobile/positions` and `/api/v2/paper/status` | 2 frames per path | 4 frames | 0 | 0 | 0 | 5.07s | PASS |
| Swift package build | `swift build` | SwiftPM package | n/a | 0 | 0 | 0 | 0.18s | PASS |
| Swift package tests | `swift test` | 16 XCTest + 0 Swift Testing | 16 | 0 | 0 | 0 | 0.14s XCTest | PASS |

Live validation details:

- `GET /api/v2/mobile/positions` first open row: `IDUSDT`, quantity `5320.422273988456`, entry price `0.03312343150713973` from `avg_entry_price`, mark price from `v2:market:coinapi:wsds:IDUSDT.microprice`, mark age `12.276s`, non-stale, and `decision_reasoning.reason` from `adaptive_allocation_from_confidence_edge_market_quality_and_risk_budget:b_grade_exploration_fraction_of_normal_adaptive_budget`.
- `GET /api/v2/mobile/positions` first closed row: `EPICUSDT`, entry price `0.44926831300784137`, exit price `0.4499`, close reason `TIER_1_ATR_VOLATILITY_STOP`, and closed-trade `decision_reasoning`.
- `GET /api/v2/paper/status` first open row: live mark source `v2:market:coinapi:wsds:IDUSDT.microprice`, mark age `0.02s`, `live_mark_price_count: 4`, `stale_mark_price_count: 0`, `missing_mark_price_count: 0`.
- Resource WebSocket `path=/api/v2/mobile/positions` delivered repeated frames with 4 open positions and 50 closed rows; `path=/api/v2/paper/status` delivered repeated frames with 4 open positions and 200 closed rows.
- Restart evidence: `systemctl --user restart ai-bot-v2-public-website-backend.service` timed out in `stop-sigterm`; the old main PID was killed through `systemctl --user kill --kill-who=main --signal=SIGKILL`, then the service was started cleanly. Post-restart main PID was `3089126`.

Notes:

- This is not full field-level rendered validation. The route/app matrix still needs every value classified for route, role, component, source, timestamp, age, zero/null/missing/stale/fallback semantics.
- Native iPhone/watchOS simulator validation and TestFlight remain blocked on macOS/Xcode.
- Real live execution remains blocked; the validated payloads still report `places_real_order: false` / `live_gate: blocked_human_only`.

## 2026-06-23 Lane/OpenAPI Evidence Refresh After Position Pricing

Scope: evidence refresh only after the paper position pricing/reasoning adapter
work. This pass regenerated lane-isolation hashes/classification and OpenAPI
compatibility artifacts so the proof files reflect the current worktree. It did
not modify live execution behavior, strategy logic, PPO, MASA, trainer
calculations, risk logic, live-gate transitions, order routing, exchange
execution, Redis producer contracts, database trading records, or API field
meanings.

| Area | Command | Collected | Passed | Failed | Errors | Skipped / did not run | Duration | Result |
|---|---|---:|---:|---:|---:|---:|---|---|
| Lane inventory refresh | `/home/wali/Desktop/AI\ BOT\ REBUILD/.venv/bin/python scripts/nervyx_lane_isolation_inventory.py` | 471581 changed status records; 180 protected diffs | n/a | 0 | 0 | 0 | 4.25s | PASS as evidence generation; lane isolation remains UNPROVEN |
| OpenAPI capture/diff | `/home/wali/Desktop/AI\ BOT\ REBUILD/.venv/bin/python scripts/nervyx_openapi_compatibility.py` | current 114 paths / 118 operations; shimmed baseline 65 paths / 65 operations | n/a | 0 | 0 | 0 | 1.87s | PARTIAL: current capture passed; raw baseline failed; shimmed baseline passed |
| JSON artifact validation | `python3 -m json.tool ...` | 7 JSON artifacts | 7 | 0 | 0 | 0 | <1s | PASS |
| Evidence summary check | `node -e "... lane/protected/openapi summaries ..."` | 3 summary artifacts | 3 | 0 | 0 | 0 | <1s | PASS |
| Diff whitespace check | `git diff --check -- scripts/nervyx_lane_isolation_inventory.py scripts/nervyx_openapi_compatibility.py ...` | refreshed docs/artifacts | n/a | 0 | 0 | 0 | <1s | PASS |

Current refreshed lane evidence:

- Generated at: `2026-06-23T17:40:13.189523+00:00`
- Branch: `codex/pipeline-trust-refresh`
- HEAD: `5b0a4997dae6ab50b1f3aba3327ad9959e126247`
- Merge base: `680ddfb12d2810d950f7a465a39a4fb8a77ec205`
- Changed-file status records: `471581`
- Inventory checksum: `a2ef94e33c84a95a8dfd65bbd1fd0bf2bfb5ce978030ba6f4016ab46f4278620`
- Classification counts: `DOCUMENTATION 120`, `GENERATED_ARTIFACT 471379`, `IOS_PRESENTATION 22`, `PREEXISTING_UNRELATED_CHANGE 572`, `PROTECTED_LANE_EXCEPTION 23`, `READ_ONLY_API_ADAPTER 2`, `REALTIME_TRANSPORT_ADAPTER 68`, `TEST 46`, `THEME_OR_TOKEN 3`, `WATCH_PRESENTATION 4`, `WEB_PRESENTATION 350`
- Protected diff count: `180`
- Protected status counts: `169 added`, `11 modified`
- Protected review counts: `3 API_SURFACE_REQUIRES_REVIEW`, `59 CLI_OR_PUBLISHER_REQUIRES_REVIEW`, `4 DECISION_COMPOSITION_REQUIRES_REVIEW`, `114 SERVICE_LOGIC_REQUIRES_REVIEW`

Current refreshed OpenAPI evidence:

- Generated at: `2026-06-23T17:40:26.442679Z`
- Status: `PARTIAL_SHIMMED_BASE_UNPROVEN`
- Current OpenAPI capture: `PASS`, `114` paths, `118` operations
- Baseline raw capture: `FAIL`
- Baseline shimmed capture: `PASS`, `65` paths, `65` operations
- Removed operations from captured baseline: `0`
- Removed component fields: `0`
- Component type changes: `0`
- Operation security changes: `0`
- Static fallback removed route keys: `0`

Notes:

- Lane isolation remains `UNPROVEN`. The protected hash artifacts still show 180 protected-lane diffs from the rebrand merge base, and completion still requires every protected diff to be identified, diffed, justified, and separately tested.
- OpenAPI compatibility remains `UNPROVEN`. The archived merge-base still requires temporary shims, so this is current regression evidence, not a complete compatibility proof.
- The overall NERVYX ONE goal remains `IN PROGRESS`.

## 2026-06-23 Brand Asset Verification Refresh

Scope: brand evidence refresh only. This pass read `/rebranding`, verified
selected checksum/dimension/metadata claims for web and iOS asset destinations,
and ran existing brand token drift checks. It did not modify `/rebranding`,
live execution behavior, strategy logic, PPO, MASA, trainer calculations, risk
logic, live-gate transitions, order routing, exchange execution, Redis producer
contracts, database trading records, or API field meanings.

| Area | Command | Collected | Passed | Failed | Errors | Skipped / did not run | Duration | Result |
|---|---|---:|---:|---:|---:|---:|---|---|
| Rebranding source inventory | `find /home/wali/Desktop/AI\ BOT\ REBUILD/rebranding -maxdepth 4 -type f` and root `sha256sum` | 26 root source files plus duplicated kit contents | n/a | 0 | 0 | 0 | <1s | PASS |
| Web/iOS checksum spot-check | `sha256sum /rebranding/nervyx-one-favicon.svg frontend/public/favicon.svg ...` | 9 source/destination files | 9 matching approved hashes | 0 | 0 | 0 | <1s | PASS |
| Icon/banner dimensions | `file /rebranding/nervyx-one-app-icon-1024.png ... AppIcon.appiconset/*.png` | AppIcon source, social banner, PWA icons, generated iOS icons | dimensions matched expected catalog sizes | 0 | 0 | 0 | <1s | PASS |
| Web metadata/source wiring | `sed -n ... frontend/index.html frontend/public/manifest.webmanifest frontend/src/pwa/manifest.ts` | favicon, manifest, Open Graph, Twitter card, Apple touch icon, PWA icon references | n/a | 0 | 0 | 0 | <1s | PASS as source inspection |
| iOS/watch source wiring | `sed -n ... AppIcon Contents.json Info.plist mobile/project.yml` | AppIcon catalog, display name, launch dictionary, watch target display name | n/a | 0 | 0 | 0 | <1s | PASS as source inspection; native render blocked |
| Web/Swift token drift | `node scripts/check-nervyx-brand-token-drift.mjs` | source checksum `36bf9013...f2d7` | 1 | 0 | 0 | 0 | <1s | PASS |
| Playwright token drift | `npx playwright test tests/e2e/nervyx_theme_token_drift.spec.ts --reporter=line` | 1 Chromium spec | 1 | 0 | 0 | 0 | 256ms | PASS |
| Swift package tests | `swift test` | 16 XCTest + 0 Swift Testing | 16 | 0 | 0 | 0 | 0.229s XCTest | PASS |

Current brand evidence:

- Source `/rebranding` remains read-only.
- `frontend/public/favicon.svg` checksum-matches `/rebranding/nervyx-one-favicon.svg`.
- `frontend/public/brand/nervyx-one-logo-horizontal-on-midnight.svg`, `nervyx-one-logo-horizontal-on-light.svg`, `nervyx-one-symbol-gradient.svg`, and `nervyx-one-social-banner.png` checksum-match approved `/rebranding` assets.
- iOS asset catalog SVGs for `NervyxMark`, `NervyxLogoOnLight`, and `NervyxLogoOnMidnight` checksum-match approved `/rebranding` assets.
- `frontend/index.html` references the approved favicon, PWA manifest, social banner, Apple touch icon, and operator-gated execution wording.
- `mobile/Sources/AIBotV2/Info.plist` configures `CFBundleDisplayName` as `NERVYX ONE`, `CFBundleIconName` as `AppIcon`, and `UILaunchScreen`.
- `mobile/project.yml` configures watchOS target identity as `NERVYX ONE` without signing mutation.
- Token drift checks prove web and Swift generated token outputs derive from `/rebranding/nervyx-one-brand-tokens.json`.

Notes:

- This is still not native iPhone/watchOS simulator validation. AppIcon, launch screen, watchOS brand rendering, notification presentation, Dynamic Type, VoiceOver, clipping, and crash checks remain blocked until macOS/Xcode validation runs.
- TestFlight remains blocked; no App Store Connect processed-build evidence was produced.

## 2026-06-23 Data Surface Inventory Expansion

Scope: read-only field-parity evidence generation. This pass extended and reran
`scripts/nervyx_data_surface_inventory.py` so the data-preservation gate now
captures backend route decorators, backend Redis/read-model key literals, and
Swift API endpoint constants in addition to OpenAPI, frontend realtime
resources, frontend interfaces, Swift Codable models, and sampled runtime JSON.
It did not contact Redis, call exchanges, mutate runtime state, or modify live
execution behavior, strategy logic, PPO, MASA, trainer calculations, risk
logic, live-gate transitions, order routing, exchange execution, Redis producer
contracts, database trading records, or API field meanings.

| Area | Command | Collected | Passed | Failed | Errors | Skipped / did not run | Duration | Result |
|---|---|---:|---:|---:|---:|---:|---|---|
| Inventory script syntax | `/home/wali/Desktop/AI\ BOT\ REBUILD/.venv/bin/python -m py_compile scripts/nervyx_data_surface_inventory.py` | 1 file | 1 | 0 | 0 | 0 | <1s | PASS |
| Data surface inventory | `/home/wali/Desktop/AI\ BOT\ REBUILD/.venv/bin/python scripts/nervyx_data_surface_inventory.py` | source/runtime inventory artifact | n/a | 0 | 0 | 0 | 0.19s | PASS as inventory generation; full parity remains unproven |
| JSON artifact validation | `python3 -m json.tool artifacts/nervyx-data-surface-inventory.json ...` | 2 JSON artifacts | 2 | 0 | 0 | 0 | <1s | PASS |
| Summary extraction | `node - <<'NODE' ... artifacts/nervyx-data-surface-inventory.json ...` | refreshed counts and categories | n/a | 0 | 0 | 0 | <1s | PASS |
| Diff whitespace check | `git diff --check -- scripts/nervyx_data_surface_inventory.py artifacts/nervyx-data-surface-inventory.json artifacts/nervyx-data-surface-inventory-summary.json docs/nervyx-data-parity-matrix.md docs/nervyx-linux-validation-results.md docs/nervyx-command-log.md` | script/docs/artifacts | n/a | 0 | 0 | 0 | <1s | PASS |

Current refreshed inventory:

- Generated at: `2026-06-23T17:47:18.158451+00:00`
- Status: `IN_PROGRESS_NOT_FULL_PARITY`
- OpenAPI operation responses: `118`
- OpenAPI component fields: `91`
- Backend route surfaces: `152`
- Backend route methods: `112 GET`, `26 POST`, `4 PUT`, `4 DELETE`, `6 WEBSOCKET`
- Backend Redis/read-model key literals: `1163`
- Backend read-model key categories: `57`
- Frontend realtime resource subscriptions: `112`
- Frontend TypeScript interfaces: `482`
- Frontend TypeScript interface fields: `5271`
- Swift Codable models: `76`
- Swift Codable fields: `474`
- Swift API endpoints: `26` (`23` HTTP, `3` WebSocket/resource stream)
- Runtime snapshot samples: `500`
- Runtime snapshot top-level fields: `12322`

Representative backend read-model categories:

- `market`: `285`
- `paper`: `175`
- `altdata`: `107`
- `features`: `101`
- `prediction`: `71`
- `trainer`: `71`
- `risk`: `52`
- `signals`: `41`
- `orchestrator`: `34`
- `liquidations`: `16`
- `portfolio`: `10`
- `audit`: `9`

Notes:

- Data preservation remains `UNPROVEN`. This inventory is broader than the earlier baseline, but it still does not classify every field by permission, source service, unit, null behavior, freshness threshold, destination, formatter, evidence/detail location, and test status.
- The inventory enumerates backend key literals; it does not yet expand every live Redis value field.
- Full rendered web and native iOS/watchOS parity remains pending.

## 2026-06-23 Truthful Status Model / Public Status Revalidation

Scope: read-only backend status normalization and public status presentation.
This pass added the required separate status dimensions for market data,
automation, execution, and account, then wired `/status` to render those backend
truth fields without implying live order execution. It did not modify live
execution behavior, strategy logic, PPO, MASA, trainer calculations, risk
logic, live-gate transitions, order routing, exchange execution, Redis producer
contracts, database trading records, or existing API field meanings.

| Area | Command | Collected | Passed | Failed | Errors | Skipped / did not run | Duration | Result |
|---|---|---:|---:|---:|---:|---:|---|---|
| Backend syntax | `python -m py_compile backend/app/api/v2/truthful_status.py backend/app/api/v2/status_contracts.py backend/app/api/v2/public_status.py` | 3 files | 3 | 0 | 0 | 0 | <1s | PASS |
| Focused backend status tests | `/home/wali/Desktop/AI\ BOT\ REBUILD/.venv/bin/python -m pytest -q backend/tests/integration/api/test_auth_rbac_and_status.py::test_public_status_exposes_no_forbidden_internal_fields backend/tests/integration/api/v2/test_landing_routes.py::test_c2_public_status_missing_redis_returns_safe_defaults backend/tests/integration/api/v2/test_landing_routes.py::test_c2_public_status_reads_redis_payload` | 3 tests | 3 | 0 | 0 | 0 | 0.85s | PASS |
| Default shell pytest attempt | `PYTHONPATH=backend pytest -q ...` | 0 tests | 0 | 0 | 1 command unavailable | 3 intended tests | <1s | BLOCKED by missing `pytest` on `/usr/bin/python`; rerun passed with repo venv |
| Frontend typecheck | `npm run typecheck` | TypeScript project references | n/a | 0 | 0 | 0 | 6.3s | PASS |
| Frontend build | `npm run build` | Vite production bundle | n/a | 0 | 0 | 0 | 17.7s | PASS; chunk-size warning only |
| Playwright on stale 5173 before restart | `npx playwright test tests/e2e/public_status_redesign.spec.ts --reporter=line` | 11 Chromium tests | 9 | 2 | 0 | 0 | 10.2s | FAIL; localhost 5173 was serving the old status bundle |
| Dev server attempt on 5174 | `npm run dev -- --host 127.0.0.1 --port 5174` | Vite dev server | n/a | 0 | 1 | n/a | <1s | BLOCKED by OS watcher `ENOSPC` |
| Playwright on built preview 5174 | `PLAYWRIGHT_NO_WEBSERVER=1 PLAYWRIGHT_BASE_URL=http://127.0.0.1:5174 npx playwright test tests/e2e/public_status_redesign.spec.ts --reporter=line` | 11 Chromium tests | 11 | 0 | 0 | 0 | 1.6s | PASS |
| Localhost service restart | `systemctl --user restart ai-bot-v2-public-website-backend.service` | `ai-bot-v2-public-website-backend.service` | active PID `3149377` | 0 | 0 | 0 | 11.9s | PASS |
| Localhost 5173 API probe | `curl -sS http://127.0.0.1:5173/api/v2/public/status | python3 -m json.tool` | status payload | n/a | 0 | 0 | 0 | <1s | PASS; `status_dimensions.execution=RESTRICTED`, `order_submission_enabled=false`, `places_real_order=false` |
| Playwright on actual 5173 after restart | `PLAYWRIGHT_NO_WEBSERVER=1 PLAYWRIGHT_BASE_URL=http://127.0.0.1:5173 npx playwright test tests/e2e/public_status_redesign.spec.ts --reporter=line` | 11 Chromium tests | 11 | 0 | 0 | 0 | 2.2s | PASS |
| Source forbidden-phrase scan | `rg -n "Live trading platform|Live execution|Trading live|...|Order Routing" frontend/src/pages/public-status frontend/tests/e2e/public_status_redesign.spec.ts backend/app/api/v2/status_contracts.py backend/app/api/v2/public_status.py backend/app/api/v2/truthful_status.py -S` | changed status surfaces | n/a | 0 | 0 | 0 | <1s | PASS; only negative test regex matched |
| Diff whitespace check | `git diff --check -- backend/app/api/v2/truthful_status.py ... frontend/tests/e2e/public_status_redesign.spec.ts` | changed status files | n/a | 0 | 0 | 0 | <1s | PASS |

Backend-truth status model now exposed by `/api/v2/status` and
`/api/v2/public/status`:

- `market_data`: `LIVE | DELAYED | STALE | OFFLINE`
- `automation`: `ACTIVE | PAUSED | DEGRADED | UNKNOWN`
- `execution`: `RESTRICTED | PAPER | LIVE_APPROVED | DISABLED`
- `account`: `CONNECTED | UNAVAILABLE | UNAUTHORIZED`
- Safety booleans remain explicit: `live_trading_enabled: false`,
  `order_submission_enabled: false`, `places_real_order: false`,
  `exchange_mutation_enabled: false`

Notes:

- The public `/status` UI renders market data separately from execution. It can
  show market data as live while execution remains restricted and order
  submission remains disabled.
- `localhost:5173` was restarted and revalidated after the production build so
  it no longer served the stale public-status bundle observed in the first
  Playwright run.
- Native iPhone/watchOS simulator validation and TestFlight remain blocked on
  macOS/Xcode.
- Real live execution remains blocked.

## 2026-06-23 Backend-Authenticated Role Audit Canonical Refresh

Scope: corrected the role-route audit contract so canonical admin coverage uses
the current `/admin/...` routes and legacy `/system/...` paths are audited as
redirects. This is audit/test evidence only; it does not change application
routing, auth, permissions, execution, risk, strategy, PPO, MASA, trainer
calculations, publisher contracts, Redis producers, database records, or API
field meanings.

| Area | Command | Collected | Passed | Failed | Errors | Skipped / did not run | Duration | Result |
|---|---|---:|---:|---:|---:|---:|---|---|
| Backend-auth role route audit | `node scripts/nervyx_backend_auth_role_route_audit.mjs` | 1 Playwright spec / 580 route-role rows | 1 spec | 0 | 0 | 0 | 8.7m | PASS: backend login gate proven; 133 rendered, 156 restricted, 291 redirected |
| Role audit artifact summary | `node - <<'NODE' ... artifacts/nervyx-role-route-audit-backend-auth.json ...` | 580 rows | n/a | 0 | 0 | 0 | <1s | PASS: admin rendered 24/24 admin canonical pages; superadmin rendered 24/24 admin pages plus `/admin/evidence` |
| Role audit JSON validation | `python3 -m json.tool artifacts/nervyx-role-route-audit-backend-auth.json ...` | 1 JSON artifact | 1 | 0 | 0 | 0 | <1s | PASS |

Artifact:

- `artifacts/nervyx-role-route-audit-backend-auth.json`
- Generated at: `2026-06-23T18:03:57.951Z`
- Artifact screenshot paths: `580`
- Screenshot directory: `artifacts/nervyx-role-route-audit-backend-auth-screenshots/` currently contains `690` files because prior captures are retained.

Evidence summary:

- Backend login-cookie sessions were proven for viewer, trader, admin, and superadmin; guest `/api/auth/me` returned `401`.
- `?role=` was not used as authorization proof.
- Admin rendered all 24 canonical admin pages and was restricted from the canonical superadmin page.
- Superadmin rendered all 24 canonical admin pages and the canonical superadmin page.
- Rows with WebSocket URLs: `314`; rows with frames: `297`.
- Rows with failed requests: `0`; real console errors: `0`.
- Horizontal overflow: `0`; clipped text: `0`; visible old branding: `0`; unauthorized leakage: `0`.

Remaining gaps:

- This evidence does not prove every displayed field is fresh, semantically valid, and non-stale.
- Stale/missing/fallback labels still require field-level accounting in `docs/nervyx-rendered-field-validation.md`.
- Native iOS/watchOS validation remains blocked on macOS/Xcode.
- Full NERVYX completion remains blocked by the unresolved field parity, backend full-suite, native Apple, TestFlight, and lane-isolation gates.

## 2026-06-23 Lane Isolation Current-State Refresh

Scope: regenerated lane-isolation evidence from the current worktree after the latest read-only position realtime/resource work. This pass only reads git metadata and file contents, then writes evidence docs/artifacts. It does not reset, clean, stash, contact exchanges, mutate Redis, alter live execution, or change trainer/PPO/MASA/strategy/risk/order-routing semantics.

| Area | Command | Collected | Passed | Failed | Errors | Skipped / did not run | Duration | Result |
|---|---|---:|---:|---:|---:|---:|---|---|
| Lane inventory refresh | `python3 scripts/nervyx_lane_isolation_inventory.py` | 471935 changed status records; 155 base protected hashes; 324 current protected hashes; 180 protected diffs | n/a | 0 | 0 | 0 | 4.18s | PASS as evidence generation; lane isolation remains UNPROVEN |
| Lane artifact validation | `python3 -m json.tool ... && gzip -t ... && sha256sum -c ...` | 2 JSON artifacts + compressed inventory + checksum file | 4 | 0 | 0 | 0 | <1s | PASS |
| Hash/count extraction | `wc -l ... && sha256sum ...` | protected hash files and modified protected diff patch | n/a | 0 | 0 | 0 | <1s | PASS |

Current refreshed evidence:

- Generated at: `2026-06-23T18:33:56.900044+00:00`
- Branch: `codex/pipeline-trust-refresh`
- HEAD: `5b0a4997dae6ab50b1f3aba3327ad9959e126247`
- Merge base with `codex/nervyx-one-rebrand`: `680ddfb12d2810d950f7a465a39a4fb8a77ec205`
- Changed status records: `471935`
- Inventory artifact: `artifacts/nervyx-changed-file-inventory.jsonl.gz`
- Inventory SHA-256: `0d8f9a284a8b9ff36dd77a3d0719c3eab4091c7eef3a7ae2c83a1263ccacb045`
- Protected base hashes: `155`
- Protected current hashes: `324`
- Protected hash diffs: `180` (`169` added, `11` modified)
- Protected review classes: `API_SURFACE_REQUIRES_REVIEW=3`, `CLI_OR_PUBLISHER_REQUIRES_REVIEW=59`, `DECISION_COMPOSITION_REQUIRES_REVIEW=4`, `SERVICE_LOGIC_REQUIRES_REVIEW=114`
- Base hash checksum: `ec6d130a54648aa7f56beaf00819833ad2fe811a184b16a93f6d5fc7a366fbc9`
- Current hash checksum: `5518d36a14314f2c0b5b53d208bc1073a81007a398478a5e5c31cc8288b99db9`
- Protected diff artifact checksum: `c4b2bdbbee2aab1523233b7e638316e7d4d5b804ecee291ad2e1ad71316f20e7`
- Modified protected patch checksum: `6a0e7315c7c1e9a614ccd41db7a746c5f60de328d831f0e9aae21c76bed045fc`

Classification counts:

- `DOCUMENTATION`: `131`
- `GENERATED_ARTIFACT`: `471721`
- `IOS_PRESENTATION`: `22`
- `PREEXISTING_UNRELATED_CHANGE`: `587`
- `PROTECTED_LANE_EXCEPTION`: `23`
- `READ_ONLY_API_ADAPTER`: `2`
- `REALTIME_TRANSPORT_ADAPTER`: `70`
- `TEST`: `51`
- `THEME_OR_TOKEN`: `3`
- `WATCH_PRESENTATION`: `4`
- `WEB_PRESENTATION`: `351`

Status:

- LANE ISOLATION: `UNPROVEN`
- Reason: protected hash diffs are non-zero and still require individual diff review, justification, and separate tests before any isolation claim can be made.

## 2026-06-23 OpenAPI / Data Surface Current Refresh

Scope: refreshed current OpenAPI compatibility and data-surface inventory artifacts after the latest read-only resource adapter work. This pass captures API/schema/source inventories only. It does not contact Redis, call exchanges, mutate runtime state, change live execution, alter trainer/PPO/MASA/strategy/risk logic, change live-gate transitions, order routing, Redis producer contracts, database trading records, or API field meanings.

| Area | Command | Collected | Passed | Failed | Errors | Skipped / did not run | Duration | Result |
|---|---|---:|---:|---:|---:|---:|---|---|
| Script syntax | `../.venv/bin/python -m py_compile scripts/nervyx_openapi_compatibility.py scripts/nervyx_data_surface_inventory.py` | 2 scripts | 2 | 0 | 0 | 0 | <1s | PASS |
| OpenAPI compatibility refresh | `../.venv/bin/python scripts/nervyx_openapi_compatibility.py` | current 114 paths / 118 operations; shimmed baseline 65 paths / 65 operations | n/a | 0 | 0 | 0 | 1.78s | PARTIAL: current capture valid, raw baseline still fails, shimmed baseline has 0 removed operations/fields/type/security changes |
| Data-surface inventory refresh | `../.venv/bin/python scripts/nervyx_data_surface_inventory.py` | source/runtime inventory summary | n/a | 0 | 0 | 0 | 0.23s | PASS as inventory generation; full field parity remains UNPROVEN |

OpenAPI refreshed status:

- Generated at: `2026-06-23T19:01:29.059417Z`
- Status: `PARTIAL_SHIMMED_BASE_UNPROVEN`
- Current capture: `PASS`
- Raw merge-base capture: `FAIL`
- Shimmed merge-base capture: `PASS`
- Current paths / operations: `114` / `118`
- Captured baseline paths / operations: `65` / `65`
- Removed operations: `0`
- Removed component schemas: `0`
- Removed component fields: `0`
- Component type changes: `0`
- Operation security changes: `0`
- Static fallback removed route keys: `0`

Data inventory refreshed status:

- Generated at: `2026-06-23T19:01:41.200801+00:00`
- Status: `IN_PROGRESS_NOT_FULL_PARITY`
- OpenAPI operation responses: `118`
- OpenAPI component fields: `91`
- Backend route surfaces: `152`
- Backend Redis/read-model key literals: `1163`
- Backend read-model key categories: `57`
- Frontend realtime resource subscriptions: `112`
- Frontend TypeScript interfaces: `483`
- Frontend TypeScript interface fields: `5282`
- Swift Codable models: `76`
- Swift Codable fields: `474`
- Swift API endpoints: `26`
- Runtime snapshot samples: `500`
- Runtime snapshot top-level fields: `12323`

Status:

- OPENAPI COMPATIBILITY: `UNPROVEN` because the baseline capture still requires shims.
- DATA PRESERVATION: `UNPROVEN` because every field still needs permission, source service, unit, null behavior, freshness threshold, web/iOS/watch destination, evidence/detail destination, formatter, tested status, and intentional-removal accounting.

Final artifact validation for this refresh:

| Area | Command | Result |
|---|---|---|
| Generated JSON syntax | `python3 -m json.tool` over OpenAPI summaries, data-surface summaries, data-surface inventory, before/after OpenAPI captures, and static route artifacts | PASS |
| Patch hygiene | `git diff --check` over OpenAPI/data-surface scripts, docs, todo, and artifacts | PASS |
| Trailing whitespace | `rg -n "[ \t]+$"` over OpenAPI/data-surface scripts and docs | PASS: no matches |

The latest operator addendum for paper position pricing, position AI reasoning, and expanded realtime Swift app surfaces is tracked in `docs/frontend-redesign-master-todo.md`. Those requirements remain open until authenticated rendered-field capture, native iPhone/watchOS validation, full field parity, and semantic zero/null/missing/stale tests pass.

## 2026-06-23 Brand Asset Inventory Refresh

Scope: refreshed the `/rebranding` evidence using a deterministic read-only scanner. This pass did not edit `/rebranding`, did not copy assets, and did not touch live execution, strategy, trainer, PPO, MASA, risk, order routing, exchange, Redis producer, or database trading code.

| Area | Command | Collected | Passed | Failed | Errors | Skipped / did not run | Duration | Result |
|---|---|---:|---:|---:|---:|---:|---|---|
| Script syntax | `python3 -m py_compile scripts/nervyx_brand_asset_inventory.py` | 1 script | 1 | 0 | 0 | 0 | <1s | PASS |
| Brand inventory generation | `python3 scripts/nervyx_brand_asset_inventory.py` | 51 `/rebranding` files, 14 required surfaces | n/a | 0 | 0 | 0 | 4.70s | PASS as evidence generation; native/TestFlight gates remain blocked |
| Token drift | `node scripts/check-nervyx-brand-token-drift.mjs` | shared web/Swift token outputs | n/a | 0 | 0 | 0 | <1s | PASS |
| Generated JSON syntax | `python3 -m json.tool artifacts/nervyx-brand-asset-inventory*.json` | 2 JSON artifacts | 2 | 0 | 0 | 0 | <1s | PASS |
| Patch hygiene | `git diff --check -- scripts/nervyx_brand_asset_inventory.py docs/nervyx-brand-asset-final-inventory.md artifacts/nervyx-brand-asset-inventory.json artifacts/nervyx-brand-asset-inventory-summary.json` | scanner, doc, artifacts | n/a | 0 | 0 | 0 | <1s | PASS |
| Trailing whitespace | `rg -n "[ \t]+$" scripts/nervyx_brand_asset_inventory.py docs/nervyx-brand-asset-final-inventory.md` | scanner + generated doc | n/a | 0 | 0 | 0 | <1s | PASS: no matches |

Refreshed evidence:

- Artifact: `artifacts/nervyx-brand-asset-inventory.json`
- Summary: `artifacts/nervyx-brand-asset-inventory-summary.json`
- Doc: `docs/nervyx-brand-asset-final-inventory.md`
- Generated at: `2026-06-23T19:10:56+00:00`
- Status: `IN_PROGRESS_NATIVE_VISUAL_TESTFLIGHT_BLOCKED`
- Source files inventoried: `51`
- Assets with exact checksum destinations: `38`
- Assets with generated destinations: `4`
- Assets with web usage evidence: `22`
- Assets with iOS usage evidence: `10`
- Assets with watchOS asset-level usage evidence: `0`
- Required surface rows: `14`
- Blocked/pending surface validations: `12`
- Token source checksum: `36bf9013c0a13604cadc6ffa3429a875249359f36755bb1b9bf13f6baf49f2d7`

Status:

- `/rebranding` SOURCE INVENTORY: `PARTIAL PROVEN` for checksums/destinations/source references.
- WEB BRAND USAGE: `IN PROGRESS` because full route-state screenshots and authenticated role rendering remain pending.
- IOS BRAND USAGE: `IN PROGRESS / NATIVE VALIDATION BLOCKED` because Linux can inspect sources but cannot run iPhone simulator, archive, accessibility, or notification rendering.
- WATCHOS BRAND USAGE: `IN PROGRESS / NATIVE VALIDATION BLOCKED` because the current repo snapshot shows text/display-name watch identity but no dedicated watch asset catalog or complication proof.
- TESTFLIGHT: `BLOCKED`.

## 2026-06-23 Semantic Price Validation Refresh

Scope: tightened read-only mobile API numeric parsing so non-finite `NaN`, `Infinity`, and `-Infinity` values do not become displayed quantity, price, mark-age, or unrealized-PnL values in compact mobile position payloads. Added focused tests for mobile entry/close/mark fallback behavior and market mark-candidate rejection. This pass did not change order routing, exchange execution, risk calculations, strategy selection, PPO, MASA, trainer calculations, signal generation semantics, publisher semantics, Redis producer contracts, database trading records, or live-gate transitions.

| Area | Command | Collected | Passed | Failed | Errors | Skipped / did not run | Duration | Result |
|---|---|---:|---:|---:|---:|---:|---|---|
| Script syntax | `../.venv/bin/python -m py_compile backend/app/api/v2/mobile.py backend/tests/unit/api/test_paper_mark_price_freshness.py` | 2 Python files | 2 | 0 | 0 | 0 | <1s | PASS |
| Focused backend semantic price tests | `../.venv/bin/python -m pytest backend/tests/unit/api/test_paper_mark_price_freshness.py -q` | 35 tests | 35 | 0 | 0 | 0 | 0.41s | PASS |
| Patch hygiene | `git diff --check -- backend/app/api/v2/mobile.py backend/tests/unit/api/test_paper_mark_price_freshness.py` | 2 files | n/a | 0 | 0 | 0 | <1s | PASS |
| Trailing whitespace | `rg -n "[ \t]+$" backend/app/api/v2/mobile.py backend/tests/unit/api/test_paper_mark_price_freshness.py` | 2 files | n/a | 0 | 0 | 0 | <1s | PASS: no matches |

New semantic coverage:

- Mobile compact position entry, close/exit, and mark prices reject `NaN`, `Infinity`, and `-Infinity`.
- Mobile compact position parsing may use a finite positive fallback price when the primary field is non-finite.
- Mobile compact positions leave non-finite prices unavailable when no finite positive fallback exists.
- Mobile optional quantity, mark age, and unrealized PnL reject non-finite values.
- Market mark price candidate creation rejects non-finite mark prices before age/source projection.

Status:

- SEMANTIC ZERO/MISSING/STALE VALIDATION: `IN PROGRESS`.
- NaN/non-finite price adapter coverage: `PARTIAL PROVEN` for focused read-only mobile and market adapters.
- Full rendered-field validation remains pending for every card/table/chart and for delayed, disconnected, fallback, reconnection, out-of-order frame, and duplicate-frame scenarios.

## 2026-06-23 Realtime Resource Frame Semantics Refresh

Scope: hardened the frontend read-only resource hook to use backend frame timestamps for ordering and preserve the current usable payload when later WebSocket/API frames are stale, incomplete, or older than the displayed payload. Added focused Playwright tests for stale/incomplete frame preservation, out-of-order frame rejection, duplicate frame acceptance, API fallback labelling, and timestamp parsing. This pass did not change backend route behavior, order routing, exchange execution, risk calculations, strategy selection, PPO, MASA, trainer calculations, signal generation semantics, publisher semantics, Redis producer contracts, database trading records, or live-gate transitions.

| Area | Command | Collected | Passed | Failed | Errors | Skipped / did not run | Duration | Result |
|---|---|---:|---:|---:|---:|---:|---|---|
| Focused Chromium realtime frame spec | `npx playwright test tests/e2e/realtime_resource_frame_semantics.spec.ts --project=chromium --reporter=line` | 5 tests | 5 | 0 | 0 | 0 | 0.46s | PASS |
| Frontend typecheck | `npm run typecheck` | TypeScript project | n/a | 0 | 0 | 0 | 6.39s | PASS |
| Patch hygiene | `git diff --check -- frontend/src/hooks/useRealtimeResource.ts frontend/tests/e2e/realtime_resource_frame_semantics.spec.ts` | hook + spec | n/a | 0 | 0 | 0 | <1s | PASS |
| Trailing whitespace | `rg -n "[ \t]+$" frontend/src/hooks/useRealtimeResource.ts frontend/tests/e2e/realtime_resource_frame_semantics.spec.ts` | hook + spec | n/a | 0 | 0 | 0 | <1s | PASS: no matches |

New semantic coverage:

- Stale or incomplete later frames preserve the last usable payload and add a preservation warning.
- Fresh but older out-of-order frames preserve the newer displayed payload and add an out-of-order preservation warning.
- Duplicate current frames are accepted without preservation warnings.
- Current API fallback frames remain usable while preserving visible `source_type: api` fallback labelling.
- Backend frame order uses `timestamp`, `received_at`, `generated_at`, `generated_utc`, or `updated_at` before falling back to browser receive time.

Status:

- REALTIME WEB DATA: `IN PROGRESS`.
- Hook-level stale/out-of-order/duplicate/API-fallback frame semantics: `PARTIAL PROVEN`.
- Full route-level disconnect/reconnect, delayed rendering, and every-field card/table/chart validation remain pending.

## 2026-06-23 Native Apple Validation Lane Refresh

Scope: made the prepared native Apple validation lane runnable from the GitHub repository root while preserving the `v2/.github` source copy used by local Swift static tests. This pass did not change signing, Apple accounts, entitlements, archive upload, App Store Connect, TestFlight state, live execution, order routing, exchange execution, risk calculations, strategy selection, PPO, MASA, trainer calculations, signal generation semantics, publisher semantics, Redis producer contracts, database trading records, or live-gate transitions.

| Area | Command | Collected | Passed | Failed | Errors | Skipped / did not run | Duration | Result |
|---|---|---:|---:|---:|---:|---:|---|---|
| Build-number preflight | `python3 scripts/check_ios_app_store_build_number.py` | 1 guard | 1 | 0 | 0 | 0 | <1s | PASS: `current=6 previous=4` |
| Workflow YAML parse | Python/PyYAML parse of `../.github/workflows/nervyx-ios-macos-validation.yml` and `.github/workflows/nervyx-ios-macos-validation.yml` | 2 workflow files | 2 | 0 | 0 | 0 | <1s | PASS: both expose `native-apple` job |
| Workflow copy consistency | `cmp -s ../.github/workflows/nervyx-ios-macos-validation.yml .github/workflows/nervyx-ios-macos-validation.yml` | 2 workflow files | 1 comparison | 0 | 0 | 0 | <1s | PASS: identical |
| Native Xcode availability | `xcodebuild -version` | host toolchain | 0 | 0 | 1 | native iOS/watchOS build not runnable on Linux | <1s | BLOCKED: `xcodebuild: command not found` |
| Swift package build | `swift build` from `mobile/` | 1 Swift package | 1 | 0 | 0 | 0 | 0.17s build phase | PASS |
| Swift package tests | `swift test` from `mobile/` | 16 XCTest | 16 | 0 | 0 | 0 | 0.247s test phase | PASS |
| Patch hygiene | `git diff --check` over native workflow, Swift test, and validation docs | workflow + docs + test | n/a | 0 | 0 | 0 | <1s | PASS |
| Trailing whitespace | `rg -n "[ \t]+$"` over native workflow, Swift test, and validation docs | workflow + docs + test | n/a | 0 | 0 | 0 | <1s | PASS: no matches |

New native-lane evidence:

- Repository-root workflow: `.github/workflows/nervyx-ios-macos-validation.yml`.
- v2 source/test workflow copy: `v2/.github/workflows/nervyx-ios-macos-validation.yml`.
- Both workflow files are byte-identical and parse with a `native-apple` job.
- The workflow runs on `macos-15`, installs XcodeGen, runs the iOS App Store build-number guard, runs `swift build` and `swift test`, generates the Xcode project, builds iOS simulator and watchOS simulator targets with `CODE_SIGNING_ALLOWED=NO`, records blocked native gates, and uploads validation artifacts.
- Swift static guard now verifies both workflow locations and asserts no `DEVELOPMENT_TEAM`, `fastlane pilot`, `altool`, or `notarytool` mutation/upload path.

Status:

- IOS SOURCE WIRING: `IN PROGRESS`.
- NATIVE IOS VALIDATION: `BLOCKED - MACOS/XCODE REQUIRED`.
- WATCHOS VALIDATION: `BLOCKED - MACOS/XCODE REQUIRED`.
- TESTFLIGHT: `BLOCKED`.
- REAL LIVE EXECUTION: `BLOCKED`.

## 2026-06-23 Position Pricing And AI Reasoning Guard Refresh

Scope: added focused source/static guards proving website open, closed, and historical position surfaces expose AI decision basis from `decision_reasoning`, and proving iOS position lanes link to detail rows with entry/exit/mark pricing and AI reasoning. Revalidated the focused backend pricing/reasoning suite. This pass did not change order routing, exchange execution, risk calculations, strategy selection, PPO, MASA, trainer calculations, signal generation semantics, publisher semantics, Redis producer contracts, database trading records, or live-gate transitions.

| Area | Command | Collected | Passed | Failed | Errors | Skipped / did not run | Duration | Result |
|---|---|---:|---:|---:|---:|---:|---|---|
| Focused web position contract | `PLAYWRIGHT_NO_WEBSERVER=1 npx playwright test tests/e2e/paper_positions_refresh_persistence.spec.ts --project=chromium --reporter=line` | 6 tests | 6 | 0 | 0 | 0 | 0.513s | PASS |
| Swift package tests - first run | `swift test` from `mobile/` | 17 XCTest | 16 | 1 | 0 | 0 | 0.339s test phase | FAIL: static snippet expected single-line Mark Price row |
| Swift static guard adjustment | `apply_patch` on `mobile/Tests/AIBotV2Tests/AIBotV2CoreTests.swift` | 1 test assertion | 1 | 0 | 0 | 0 | <1s | Fixed assertion to match multiline Swift `DataRow` |
| Swift package tests - rerun | `swift test` from `mobile/` | 17 XCTest | 17 | 0 | 0 | 0 | 0.031s test phase | PASS |
| Focused backend position pricing/reasoning tests | `../.venv/bin/python -m pytest backend/tests/unit/api/test_paper_mark_price_freshness.py -q` | 35 tests | 35 | 0 | 0 | 0 | 0.36s | PASS |
| Patch hygiene | `git diff --check` over backend/mobile/frontend position pricing and reasoning files plus docs | code + tests + docs | n/a | 0 | 0 | 0 | <1s | PASS |
| Trailing whitespace | `rg -n "[ \t]+$"` over backend/mobile/frontend position pricing and reasoning files plus docs | code + tests + docs | n/a | 0 | 0 | 0 | <1s | PASS: no matches |

Focused evidence added:

- Website `/positions` source guard pins `open`, `closed`, and `historical` tabs, `PositionEvidenceCard`, positive-only entry/exit/mark selection, and `AI Reasoning` fields for action, confidence, reason, risk, regime, signal, prediction, and source.
- Website `/admin/paper-trading` source guard pins `DecisionBasisPanel` for open position cards and historical/closed trade cards.
- iOS `PositionsView` static guard pins open/closed/historical lanes, detail navigation, entry/exit/mark/source rows, and AI reasoning signal/prediction detail rows.
- Existing backend focused suite confirms zero/non-finite prices are not displayed as valid, positive fallback prices preserve real entry/exit/mark values, realtime market marks drive open-position PnL, closed rows preserve exit prices, and signal/prediction reasoning attaches to open/closed/mobile paper summary payloads.

Status:

- PAPER POSITION PRICING: `IN PROGRESS / focused adapter and source guards passed`.
- POSITION AI REASONING: `IN PROGRESS / focused web and Swift source guards passed`.
- FULL AUTHENTICATED RENDERED-FIELD CAPTURE: `PENDING`.
- NATIVE IOS/WATCHOS RENDERED VALIDATION: `BLOCKED - MACOS/XCODE REQUIRED`.

## 2026-06-23 Mobile Resource Stream Metadata Slice

Scope: added Swift-side read-only websocket stream metadata handling and visible stream freshness cards for the iPhone positions and execution runtime surfaces. This pass did not change live execution, order routing, exchange execution, risk calculations, strategy selection, PPO, MASA, trainer calculations, signal generation semantics, publisher semantics, Redis producer contracts, database trading records, or live-gate transitions.

| Area | Command | Collected | Passed | Failed | Errors | Skipped / did not run | Duration | Result |
|---|---|---:|---:|---:|---:|---:|---|---|
| Swift package tests | `swift test` from `mobile/` | 18 XCTest | 18 | 0 | 0 | 0 | 0.233s test phase | PASS |
| Swift package build | `swift build` from `mobile/` | 1 Swift package | 1 | 0 | 0 | 0 | 0.19s build phase | PASS |
| Patch hygiene | `git diff --check` | working diff | n/a | 0 | 0 | 0 | ~2.5s | PASS |
| Trailing whitespace | `rg -n "[[:blank:]]+$" mobile/Sources/AIBotV2/Networking mobile/Sources/AIBotV2/ViewModels mobile/Sources/AIBotV2/Views mobile/Tests/AIBotV2Tests/AIBotV2CoreTests.swift` | touched mobile source/test surfaces | n/a | 0 | 0 | 0 | <1s | PASS: no matches |

Focused evidence added:

- `WebSocketClient` now exposes an async/await `AsyncThrowingStream<String, Error>` entry point while preserving the existing callback client used by current view models.
- `MobileResourceStream` now decodes both wrapped resource websocket frames and raw fallback payloads into `MobileResourceSnapshot`, preserving `source_type`, `timestamp`, `received_at`, `stale`, `missing_fields`, `warnings`, `transport`, and `resource_path`.
- `PositionsViewModel` and `PaperViewModel` now preserve source type, last update timestamp, stale state, warnings, and missing-field counts for websocket frames and API fallback payloads.
- `PositionsView` and `PaperTradingView` now render compact stream status cards near the top of the surface, so values are not presented as equally fresh when a frame is stale, missing, warned, or fallback-sourced.
- Swift static tests now pin the async websocket helper, resource snapshot metadata decoder, model metadata propagation, and visible position/execution stream status cards.

Not run in this slice:

- Backend pytest and frontend Playwright were not rerun because this slice only changed Swift mobile app source/tests and validation docs.
- Native rendered iPhone/watchOS validation remains blocked on macOS/Xcode.

Status:

- IOS SOURCE WIRING: `IN PROGRESS / mobile stream metadata slice passed Swift static validation`.
- MOBILE REALTIME DATA: `IN PROGRESS / source freshness visibility improved; native rendered validation pending`.
- NATIVE IOS VALIDATION: `BLOCKED - MACOS/XCODE REQUIRED`.
- WATCHOS VALIDATION: `BLOCKED - MACOS/XCODE REQUIRED`.
- TESTFLIGHT: `BLOCKED`.
- REAL LIVE EXECUTION: `BLOCKED`.

## 2026-06-23 Theme Persistence And Role-Escalation Guard Refresh

Scope: refreshed deterministic NERVYX brand/theme outputs from `/rebranding`, reran web/Swift drift evidence, and added focused Playwright coverage that public theme storage cannot escalate to Ops Terminal and that Polar Signal persists across reloads. This pass did not change live execution, order routing, exchange execution, risk calculations, strategy selection, PPO, MASA, trainer calculations, signal generation semantics, publisher semantics, Redis producer contracts, database trading records, or live-gate transitions.

| Area | Command | Collected | Passed | Failed | Errors | Skipped / did not run | Duration | Result |
|---|---|---:|---:|---:|---:|---:|---|---|
| Brand token generation | `npm run brand:tokens` | deterministic token generator | 1 | 0 | 0 | 0 | <1s | PASS: checksum `36bf9013c0a13604cadc6ffa3429a875249359f36755bb1b9bf13f6baf49f2d7` |
| Brand token drift | `npm run brand:tokens:check` | web + Swift generated outputs | 1 | 0 | 0 | 0 | <1s | PASS |
| Theme token Playwright drift | `npm run --prefix frontend test:e2e -- nervyx_theme_token_drift.spec.ts --project=chromium --reporter=line` | 1 Chromium test | 1 | 0 | 0 | 0 | 0.259s | PASS |
| Branding/theme Playwright first run | `npm run --prefix frontend test:e2e -- nervyx_branding.spec.ts --project=chromium --reporter=line` | 4 Chromium tests | 3 | 1 | 0 | 0 | 6.8s | FAIL: new persistence test reseeded localStorage on reload |
| Branding/theme Playwright rerun | `npm run --prefix frontend test:e2e -- nervyx_branding.spec.ts --project=chromium --reporter=line` | 4 Chromium tests | 4 | 0 | 0 | 0 | 1.5s | PASS |
| Frontend typecheck | `npm run --prefix frontend typecheck` | TypeScript project | n/a | 0 | 0 | 0 | 6.66s | PASS |
| Swift package tests | `swift test` from `mobile/` | 18 XCTest | 18 | 0 | 0 | 0 | 0.336s test phase | PASS |
| Patch hygiene | `git diff --check` over theme touched files/docs | generated tokens + branding spec + docs | n/a | 0 | 0 | 0 | <1s | PASS |
| Trailing whitespace | `rg -n "[[:blank:]]+$"` over theme touched files/docs | generated tokens + branding spec + docs | n/a | 0 | 0 | 0 | <1s | PASS: no matches |

Focused evidence added:

- `/rebranding/nervyx-one-brand-tokens.json` remains the source checksum for web CSS, web TypeScript tokens, web manifest, Swift tokens, and Swift theme manifest.
- Generated module text now keeps `NERVYX EXECUTE` public wording to `Execution order lifecycle` instead of exposing paper/live wording.
- Public `ThemeToggle` coverage now verifies only Midnight and Polar are user-selectable.
- Public `nervyx_theme=ops-terminal` localStorage attempts are sanitized to Midnight, legacy theme keys are removed, and no Ops Terminal button is exposed.
- Polar Signal persists across reload through `nervyx_theme=polar-signal`.
- Swift static tests still verify Ops Terminal is rejected without `backendConfirmedAdmin`.

Status:

- SHARED THEME SYSTEM: `IN PROGRESS / source drift, persistence, and public no-escalation guards passed`.
- FULL THEME VISUAL AUDIT: `PENDING`.
- NATIVE IOS/WATCHOS ACCESSIBILITY THEME VALIDATION: `BLOCKED - MACOS/XCODE REQUIRED`.
- TESTFLIGHT: `BLOCKED`.
- REAL LIVE EXECUTION: `BLOCKED`.

## 2026-06-23 OpenAPI Compatibility Capture Refresh

Scope: reran the NERVYX OpenAPI compatibility capture with the repository virtualenv and refreshed the before/after OpenAPI artifacts plus static route inventories. This pass did not change API implementation, live execution, order routing, exchange execution, risk calculations, strategy selection, PPO, MASA, trainer calculations, signal generation semantics, publisher semantics, Redis producer contracts, database trading records, or live-gate transitions.

| Area | Command | Collected | Passed | Failed | Errors | Skipped / did not run | Duration | Result |
|---|---|---:|---:|---:|---:|---:|---|---|
| OpenAPI script inspection | `sed -n '1,320p' scripts/nervyx_openapi_compatibility.py` and `sed -n '320,760p' scripts/nervyx_openapi_compatibility.py` | script source | n/a | 0 | 0 | 0 | <1s | PASS: read-only capture/comparison tool inspected |
| Existing report inspection | `sed -n '1,240p' docs/nervyx-openapi-compatibility-report.md` | previous report | n/a | 0 | 0 | 0 | <1s | PASS |
| System Python probe | `python3 scripts/nervyx_openapi_compatibility.py --help` | attempted help probe | 0 | 1 | 0 | 0 | 0.261s | FAIL: script has no help mode and system Python lacked `fastapi`; artifacts overwritten by later venv pass |
| Virtualenv dependency check | `../.venv/bin/python - <<'PY' ... import fastapi ... PY` | Python env | 1 | 0 | 0 | 0 | <1s | PASS: Python 3.12.3, FastAPI 0.115.0 |
| OpenAPI compatibility capture | `../.venv/bin/python scripts/nervyx_openapi_compatibility.py` | current + merge-base OpenAPI, static routes | 1 | 0 | 0 | 0 | 1.75s | PASS command; status `PARTIAL_SHIMMED_BASE_UNPROVEN` |
| Artifact sanity | JSON load/count check over `docs/nervyx-openapi-*.json` and `artifacts/nervyx-openapi-*.json` | 5 JSON artifacts | 5 | 0 | 0 | 0 | <1s | PASS |
| Patch hygiene | `git diff --check -- docs/nervyx-openapi-after.json docs/nervyx-linux-validation-results.md docs/nervyx-command-log.md` | tracked OpenAPI/docs diffs | n/a | 0 | 0 | 0 | <1s | PASS |
| Trailing whitespace | `rg -n "[[:blank:]]+$" docs/nervyx-openapi-before.json docs/nervyx-openapi-after.json docs/nervyx-openapi-compatibility-report.md artifacts/nervyx-openapi-before-static-routes.json artifacts/nervyx-openapi-after-static-routes.json artifacts/nervyx-openapi-compatibility-summary.json docs/nervyx-linux-validation-results.md docs/nervyx-command-log.md` | OpenAPI artifacts + docs | n/a | 0 | 0 | 0 | <1s | PASS: no matches |

Current OpenAPI evidence:

- Current branch: `codex/pipeline-trust-refresh`.
- Current HEAD: `5b0a4997dae6ab50b1f3aba3327ad9959e126247`.
- Merge base with `codex/nervyx-one-rebrand`: `680ddfb12d2810d950f7a465a39a4fb8a77ec205`.
- Current OpenAPI capture: `PASS`, `114` paths, `118` operations.
- Baseline raw capture: `FAIL`.
- Baseline shimmed capture: `PASS`, `65` paths, `65` operations.
- Removed operations from captured baseline: `0`.
- Removed component schemas: `0`.
- Removed component fields: `0`.
- Component type changes: `0`.
- Operation security changes: `0`.
- Static fallback removed route keys: `0`.
- Added operations versus captured baseline: `53`.
- Static route inventory: baseline `101`, current `178`.

Artifacts refreshed:

- `docs/nervyx-openapi-before.json`
- `docs/nervyx-openapi-after.json`
- `docs/nervyx-openapi-compatibility-report.md`
- `artifacts/nervyx-openapi-before-static-routes.json`
- `artifacts/nervyx-openapi-after-static-routes.json`
- `artifacts/nervyx-openapi-compatibility-summary.json`

Status:

- OPENAPI COMPATIBILITY: `IN PROGRESS / diagnostic capture passed, formal proof unproven because baseline required shims`.
- PERMISSION WEAKENING PROOF: `PENDING / OpenAPI security metadata showed 0 changes, but route-auth inspection still required`.
- FULL FIELD COMPATIBILITY: `IN PROGRESS / captured component fields showed 0 removals/type changes; full data-parity matrix remains pending`.

## 2026-06-23 Lane Isolation Inventory Refresh

Scope: refreshed current git worktree inventory, changed-file classification, protected-lane base/current SHA-256 manifests, protected hash diff JSON, and modified protected diff patch. This pass was evidence-only and did not change live execution, order routing, exchange execution, risk calculations, strategy selection, PPO, MASA, trainer calculations, signal generation semantics, publisher semantics, Redis producer contracts, database trading records, or live-gate transitions.

| Area | Command | Collected | Passed | Failed | Errors | Skipped / did not run | Duration | Result |
|---|---|---:|---:|---:|---:|---:|---|---|
| Lane script inspection | `sed -n '1,360p' scripts/nervyx_lane_isolation_inventory.py` and `sed -n '360,760p' scripts/nervyx_lane_isolation_inventory.py` | script source | n/a | 0 | 0 | 0 | <1s | PASS: evidence-only generator inspected |
| Existing lane docs inspection | `sed -n '1,260p' docs/nervyx-lane-isolation-final.md` and `sed -n '1,240p' docs/nervyx-changed-file-classification.md` | previous lane docs | n/a | 0 | 0 | 0 | <1s | PASS |
| Lane inventory generation | `python3 scripts/nervyx_lane_isolation_inventory.py` | git status inventory + protected hashes | 1 | 0 | 0 | 0 | 4.36s | PASS command; lane status remains `UNPROVEN` |
| Artifact sanity | Python JSON/gzip/hash validation over lane artifacts | summary JSON, protected diff JSON, gzip inventory, SHA files | 5 | 0 | 0 | 0 | <1s | PASS |
| Patch hygiene | `git diff --check -- docs/nervyx-lane-isolation-final.md docs/nervyx-changed-file-classification.md docs/nervyx-protected-lanes-base.sha256 docs/nervyx-protected-lanes-current.sha256 docs/nervyx-linux-validation-results.md docs/nervyx-command-log.md` | lane docs + validation docs | n/a | 0 | 0 | 0 | <1s | PASS |
| Trailing whitespace | `rg -n "[[:blank:]]+$"` over lane docs/JSON/hash artifacts excluding `artifacts/nervyx-protected-lane-modified-diffs.patch` | lane docs + JSON/hash artifacts | n/a | 0 | 0 | 0 | <1s | PASS: no matches |

Current lane-isolation evidence:

- Current branch: `codex/pipeline-trust-refresh`.
- Current HEAD: `5b0a4997dae6ab50b1f3aba3327ad9959e126247`.
- Merge base with `codex/nervyx-one-rebrand`: `680ddfb12d2810d950f7a465a39a4fb8a77ec205`.
- Worktree inventory records: `471957`.
- Inventory checksum: `07f3b30844d3b1cca9882b008f97d73baaa632754636eaf52140c062b2716b2b`.
- Base protected hashes: `155`.
- Current protected hashes: `324`.
- Protected hash diffs: `180`.
- Protected status counts: `169 added`, `11 modified`.
- Protected review buckets: `3 API_SURFACE_REQUIRES_REVIEW`, `59 CLI_OR_PUBLISHER_REQUIRES_REVIEW`, `4 DECISION_COMPOSITION_REQUIRES_REVIEW`, `114 SERVICE_LOGIC_REQUIRES_REVIEW`.
- Changed-file classification includes `23 PROTECTED_LANE_EXCEPTION` and therefore does not prove isolation.

Artifacts refreshed:

- `docs/nervyx-lane-isolation-final.md`
- `docs/nervyx-changed-file-classification.md`
- `docs/nervyx-protected-lanes-base.sha256`
- `docs/nervyx-protected-lanes-current.sha256`
- `artifacts/nervyx-changed-file-inventory.jsonl.gz`
- `artifacts/nervyx-changed-file-inventory.sha256`
- `artifacts/nervyx-changed-file-classification-summary.json`
- `artifacts/nervyx-protected-lane-hash-diff.json`
- `artifacts/nervyx-protected-lane-modified-diffs.patch`

Note: `artifacts/nervyx-protected-lane-modified-diffs.patch` is a raw `git diff` capture of protected files and preserves whitespace exactly from the protected-lane diff; it is not normalized as a formatted source artifact.

Status:

- LANE ISOLATION: `UNPROVEN / current inventory and hashes refreshed; protected diffs still require per-file justification and tests`.
- PROTECTED-LANE HASHES: `IN PROGRESS / base and current hash manifests present`.
- REAL LIVE EXECUTION: `BLOCKED`.

## 2026-06-23 Brand Asset Inventory Refresh

Scope: regenerated the read-only `/rebranding` source inventory and mapped approved assets to current web, iOS, watchOS, metadata, and pending TestFlight surfaces. This pass was evidence-only and did not change live execution, order routing, exchange execution, risk calculations, strategy selection, PPO, MASA, trainer calculations, signal generation semantics, publisher semantics, Redis producer contracts, database trading records, or live-gate transitions.

| Area | Command | Collected | Passed | Failed | Errors | Skipped / did not run | Duration | Result |
|---|---|---:|---:|---:|---:|---:|---|---|
| Brand inventory script inspection | `sed -n '1,360p' scripts/nervyx_brand_asset_inventory.py` and `sed -n '360,760p' scripts/nervyx_brand_asset_inventory.py` | script source | n/a | 0 | 0 | 0 | <1s | PASS: evidence-only generator inspected |
| Existing brand docs inspection | `sed -n '1,260p' docs/nervyx-brand-asset-final-inventory.md` | previous brand inventory doc | n/a | 0 | 0 | 0 | <1s | PASS |
| Asset destination scan | `find ../rebranding frontend/public mobile/Sources/AIBotV2 mobile/Sources/AIBotV2Watch ...` and `rg -n "nervyx-one|NERVYX ONE|/brand/|manifest|og:image|apple-touch|favicon|AppIcon|NervyxLogo|NervyxMark|notification|launch" frontend mobile -S --glob '!frontend/dist/**'` | source and usage paths | n/a | 0 | 0 | 0 | <1s | PASS |
| Brand asset inventory generation | `python3 scripts/nervyx_brand_asset_inventory.py` | 51 source files, 14 surface rows | 1 | 0 | 0 | 0 | <1s | PASS command; brand validation remains `IN_PROGRESS_NATIVE_VISUAL_TESTFLIGHT_BLOCKED` |
| Required surface sanity | Python JSON check over `artifacts/nervyx-brand-asset-inventory.json` and summary | 14 required surfaces | 14 | 0 | 0 | 0 | <1s | PASS: 0 missing required surfaces |
| Process check | `ps -eo pid,ppid,cmd | rg 'nervyx_brand_asset_inventory|python3 scripts|npm|playwright|vite' || true` | local processes | n/a | 0 | 0 | 0 | <1s | PASS: no leftover validation process |
| Artifact JSON sanity | Python JSON parse over brand inventory artifacts | 2 JSON artifacts | 2 | 0 | 0 | 0 | <1s | PASS |
| Trailing whitespace | `rg -n "[[:blank:]]+$"` over brand docs/artifacts and validation docs | brand docs + JSON artifacts | n/a | 0 | 0 | 0 | <1s | PASS: no matches |

Current brand-asset evidence:

- Source root `/home/wali/Desktop/AI BOT REBUILD/rebranding` was treated as read-only.
- Source files inventoried: `51`.
- Assets with exact checksum destinations: `38`.
- Assets with generated destinations: `4`.
- Assets with web usage: `22`.
- Assets with iOS usage: `10`.
- Assets with watchOS per-asset usage: `0`.
- Blocked or pending validation items: `12`.
- Required surface rows: `14`, with `0` missing from the generated inventory.
- Web header, login, landing, favicon, PWA, manifest, Open Graph, social metadata, and error/loading/empty-state surfaces are source-wired or configured, but full rendered route-state audit remains pending.
- iOS AppIcon, launch screen, login/dashboard/navigation/settings, and notification presentation surfaces are source-wired or configured, but native simulator/archive validation is blocked on this Linux host.
- watchOS identity is partially source-wired at the surface level; complication/icon assets are not configured in the current snapshot and watch simulator validation is blocked.
- TestFlight metadata remains blocked pending macOS/Xcode/App Store Connect validation.

Artifacts refreshed:

- `docs/nervyx-brand-asset-final-inventory.md`
- `artifacts/nervyx-brand-asset-inventory.json`
- `artifacts/nervyx-brand-asset-inventory-summary.json`

Status:

- BRAND ASSET USE: `IN PROGRESS / approved /rebranding assets inventoried and mapped; native visual, route-state, install, crawler, and TestFlight validation still pending or blocked`.
- WEB BRAND SURFACES: `IN PROGRESS / source-wired; full rendered route-state audit pending`.
- IOS BRAND SURFACES: `IN PROGRESS / source-wired; native simulator/archive validation blocked on Linux`.
- WATCHOS BRAND SURFACES: `IN PROGRESS / partial source wiring; watch simulator validation blocked on Linux`.
- TESTFLIGHT: `BLOCKED`.
- REAL LIVE EXECUTION: `BLOCKED`.

## 2026-06-23 Data Surface Inventory Refresh

Scope: refreshed the source-level data-surface inventory that feeds the data-preservation and rendered-field gates. This pass was evidence-only and did not change live execution, order routing, exchange execution, risk calculations, strategy selection, PPO, MASA, trainer calculations, signal generation semantics, publisher semantics, Redis producer contracts, database trading records, or live-gate transitions.

| Area | Command | Collected | Passed | Failed | Errors | Skipped / did not run | Duration | Result |
|---|---|---:|---:|---:|---:|---:|---|---|
| Data inventory script inspection | `sed -n '1,260p' scripts/nervyx_data_surface_inventory.py` and `sed -n '260,620p' scripts/nervyx_data_surface_inventory.py` | script source | n/a | 0 | 0 | 0 | <1s | PASS: read-only evidence generator inspected |
| Existing parity docs inspection | `sed -n '1,220p' docs/nervyx-data-parity-matrix.md` and `sed -n '1,220p' docs/nervyx-rendered-field-validation.md` | current parity docs | n/a | 0 | 0 | 0 | <1s | PASS |
| Data-surface inventory generation | `../.venv/bin/python scripts/nervyx_data_surface_inventory.py` | source/runtime inventory artifact | 1 | 0 | 0 | 0 | <1s | PASS command; status remains `IN_PROGRESS_NOT_FULL_PARITY` |

Current data-surface inventory:

- OpenAPI operation responses: `118`.
- OpenAPI component fields: `91`.
- Backend route surfaces: `152`.
- Backend Redis/read-model key literals: `1163`.
- Backend read-model key categories: `57`.
- Frontend realtime resource subscriptions: `112`.
- Frontend TypeScript interfaces: `483`.
- Frontend TypeScript interface fields: `5282`.
- Swift Codable models: `76`.
- Swift Codable fields: `474`.
- Swift API endpoints: `26`.
- Runtime snapshot samples: `500`.
- Runtime snapshot top-level fields: `12349`.

Artifacts refreshed:

- `artifacts/nervyx-data-surface-inventory.json`
- `artifacts/nervyx-data-surface-inventory-summary.json`
- `docs/nervyx-data-parity-matrix.md`
- `docs/nervyx-rendered-field-validation.md`

Status:

- DATA PRESERVATION: `UNPROVEN / current source inventory refreshed; full 100% field classification remains pending`.
- RENDERED FIELD VALIDATION: `IN PROGRESS / focused position and status evidence exists; every-card/table/chart route and native capture remains pending`.
- REALTIME WEB DATA: `IN PROGRESS / field-level validation pending`.
- NATIVE IOS VALIDATION: `BLOCKED / macOS/Xcode required`.
- WATCHOS VALIDATION: `BLOCKED / macOS/Xcode required`.
- REAL LIVE EXECUTION: `BLOCKED`.
