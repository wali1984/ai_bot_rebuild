# Final product-completion audit task list

Created: 2026-07-22T05:24:52Z  
Branch: `codex/pipeline-trust-refresh`  
Planning HEAD: `fc9de15bcbf70703aca26275efc9ba6428f04083`  
Upstream divergence: 8 commits ahead, 0 behind  
Working tree at planning time: 95 dirty paths

## How to use this list

- Maximum concurrency is one primary agent plus one read-only specialist.
- Read `FINAL_PRODUCT_AUDIT_HOLD_LIST_20260721T230728Z.md` before every edit.
- Treat every currently dirty path as held until ownership is classified; never use `git add -A`.
- Do not edit publisher, strategy, PPO/MASA, risk-authority, sizing, trainer-admission, or exchange-mutation logic unless a separately authorized task explicitly requires it.
- Live order submission, cancellation, leverage, margin, symbol, and approval changes are forbidden in this audit.
- Complete each slice as: audit → defect register → minimal fix → focused tests → built-runtime verification → screenshots → scoped commit → checkpoint update.
- Every checkpoint must record the exact next command and prove that the live gate stayed blocked.

## Current evidence that may be reused

- [x] Authoritative web inventory established: 58 active route templates, 82 redirects, 3 dynamic patterns, 71 concrete final-regression cases.
- [x] Web family reruns recorded 284/284 viewport captures, zero console errors, zero failed requests, and zero overflow in the family artifacts.
- [x] Frontend typecheck and production build passed for the audited commit.
- [x] Linux SwiftPM build passed.
- [x] Swift core tests passed 36/36 after the visible-copy repair.
- [x] Publisher HOLD_LIST exists and publisher-owned paths were not edited by the completed web/iOS slices.
- [x] Live execution remained fail-closed during those runs.
- [ ] The current summary coverage matrix is not yet the required per-route/per-screen matrix.
- [ ] The current backend/web/iOS field map is summary-only and does not map every operator-facing field.
- [ ] The current visual index summarizes directories but does not link and describe every screenshot.
- [ ] The iOS audit does not yet prove every screen, deep link, iPhone path, and iPad path is reachable and source-correct.
- [ ] The recent backend change-first contract audit is not yet complete.
- [ ] A real Codemagic/Xcode archive has not been proved; Apple credentials/signing remain the documented external dependency.
- [ ] The checkpoint and defect register contain stale, superseded entries that must be reconciled before the final report.

## P0 — Freeze ownership and refresh preflight

- [ ] Record current branch, HEAD, upstream divergence, complete dirty/untracked lists, and recent Codex/Claude commits.
- [ ] Diff the current 95 dirty paths against the existing 35-path publisher HOLD_LIST.
- [ ] Classify all remaining dirty paths by owner; do not infer ownership from filename alone.
- [ ] Inventory frontend/backend/mobile processes and active/inactive/failed/duplicate/legacy/held services.
- [ ] Verify frontend 5173, backend 8000, Redis, authentication, and bounded WebSocket connections.
- [ ] Capture exact live-gate, live-symbol, execution-symbol, order, leverage, and margin-mutation proof.
- [ ] Verify iOS base URLs and Codemagic scheme, bundle ID, signing variable names, branch triggers, tests, and artifact paths.
- [ ] Write a new timestamped preflight rather than overwriting historical evidence.

Exit evidence: new preflight, refreshed HOLD_LIST, zero edits to owner-unproven paths, and explicit live-gate proof.  
Commit: `audit(preflight): refresh product ownership and runtime proof`.

## P1 — Repair the audit evidence model

- [ ] Generate one canonical route/screen inventory from source registries, not documentation.
- [ ] Give every web route and iOS destination a stable audit ID, role, canonical/redirect status, and reachability state.
- [ ] Convert family artifacts into a per-route coverage matrix with endpoint/resource, field count, screenshot path, status, defect IDs, fixed commit, and hold reason.
- [ ] Expand the visual index to link all 284 web screenshots individually and describe what each proves.
- [ ] Add iPhone and iPad screenshots or static reachability evidence for every iOS destination.
- [ ] Reconcile stale entries in the checkpoint and defect register; retain history but mark superseded evidence unambiguously.
- [ ] Add a verifier that fails when a route/screen, screenshot, defect ID, or required matrix property is missing.

Exit evidence: schema-valid per-surface matrix and visual index with no summary-only placeholders.  
Commit: `audit(evidence): make route screen and screenshot coverage exhaustive`.

## P2 — Change-first backend contract audit

- [ ] Establish the last verified UI baseline commit.
- [ ] Inspect only operator-facing backend commits after that baseline.
- [ ] Extract added, renamed, removed, and enum-changed fields; producer ownership; Redis/source namespace; API/WebSocket projection; web consumer; iOS consumer.
- [ ] Classify every item as `WIRED`, `PARTIAL`, `UNEXPOSED`, `BROKEN`, `INTERNAL`, `HELD_PUBLISHER`, or `OBSOLETE`.
- [ ] Live-query each current payload with bounded requests; never use `redis-cli KEYS` or an unbounded scan.
- [ ] Flag stale-wrapper freshness, fabricated defaults, dead writer namespaces, contradictory units, and unbounded aggregation.
- [ ] Populate `FINAL_BACKEND_WEB_IOS_FIELD_MAP_<timestamp>.json` per field, including unit, freshness, and optional/required semantics.

Exit evidence: every recent operator-facing backend field has one classification and a current-payload witness.  
Commit: `audit(contracts): classify operator backend changes and parity`.

## P3 — Shared contracts and API projection fixes

- [ ] Create focused defects from P2 before editing.
- [ ] Fix only projection, decoding, envelope, timeout, or unit defects outside held/engine-owned paths.
- [ ] Add null, stale, missing, optional, malformed, enum-forward-compatibility, RBAC, and WebSocket tests.
- [ ] Add bounded-query performance tests for any Redis aggregation touched.
- [ ] Python-compile every edited backend file and run focused endpoint contract tests.
- [ ] Verify at least three repaired values directly against live payloads.

Exit evidence: projection tests pass, real endpoints meet declared timeout, and no engine or publisher behavior changed.  
Commit: one scoped commit per endpoint family.

## P4 — Global shell and public surfaces

- [ ] Re-audit navigation, redirects, auth state, role display, runtime truth, market feed, live gate, PnL strip, ticker, error boundary, service worker, asset MIME, and static evidence serving.
- [ ] Verify every visible value against its direct source, including units, sign, time zone, freshness, null behavior, and provenance.
- [ ] Test guest and authenticated states at 1600×1000, 1440×900, 390×844, and tablet width.
- [ ] Fix only recorded defects; verify no route loops, dead links, raw JSON, fake green, or permanent spinners.
- [ ] Capture two runtime snapshots at least 20 seconds apart for dynamic shell fields.

Exit evidence: exhaustive field rows, direct-source witnesses, four-view screenshots, clean console/network logs.  
Commit: `audit(web-shell): complete global and public truth surfaces`.

## P5 — Markets and charts

- [ ] Audit prices, mark/index, base/quote volume, 1h/4h/24h/7d changes, spread, funding, OI/delta, long/short, liquidations, depth, walls, history, indicators, universe, watchlist, gainers/losers, and reconciliation labels.
- [ ] Test empty and populated `/market/:symbol?` and `/chart/:symbol?` cases.
- [ ] Prove candle finality and `available_at <= decision_time`; never treat unfinished higher-timeframe candles as final.
- [ ] Fix unit/source-label/freshness defects and add focused tests.
- [ ] Rebuild, live-verify, screenshot four viewports, and checkpoint.

Exit evidence: every market field mapped to a compatible named source with correct unit/finality.  
Commit: `audit(markets): complete chart and market-source parity`.

## P6 — Ingestors and providers

- [ ] Audit every discovered dynamic ingestor route, including hub and named detail routes.
- [ ] Verify liveness thresholds, optional/required, retryable/failed, request/CU budgets, quota, scheduler, quarantine, verified map, admissions, raw/admitted counts, isolation, cutoff/finality, partial bundle, universe deltas, and writer ownership.
- [ ] Distinguish service liveness from writer/probe liveness and held publisher conditions.
- [ ] Fix projection/display defects, then run focused tests and all four viewports.

Exit evidence: each feed has explicit ownership, semantics, cutoff, and honest missing/held state.  
Commit: `audit(ingestors): complete provider and admission truth`.

## P7 — Trading, portfolio, margin, and risk

- [ ] Audit balances, gross/net PnL, open/closed/history, quantity, notional, margin, leverage, stops, liquidation, hold duration, signal freshness, risk verdict, orchestrator action, mode, journal, and empty held state.
- [ ] Verify margin used/free/buffer/invariants, executed versus proposed leverage, adaptive ceiling, bracket evidence/authentication, and valid liquidation distance.
- [ ] Prove missing evidence renders unavailable rather than zero.
- [ ] Verify invalid position transitions fail closed before any order path.
- [ ] Do not edit risk/sizing/live-execution engines; escalate any engine-owned defect separately.

Exit evidence: direct-source comparisons, paper-only runtime tests, zero exchange mutations, live gate blocked.  
Commit: `audit(trading-risk): complete portfolio margin and fail-closed display truth`.

## P8 — Trainer and AI observability

- [ ] Audit trainer state, publisher hold, prediction age, trust blockers, checkpoint identity/source, service versus probe liveness, CUDA, replay/challenger, feature lineage, and routeable-prediction explanation.
- [ ] Verify MASA `feature_cutoff <= PPO decision_time` and no future-leaking feature is presented as admissible.
- [ ] Prove a fresh wrapper cannot label stale internal evidence `Live`.
- [ ] Preserve held publisher states; do not synthesize predictions or enable held services.
- [ ] Run four-view verification including the bounded signal-explainability capture.

Exit evidence: every blocked/stale/held state has a truthful operator explanation.  
Commit: `audit(trainer-ai): complete trust and lineage observability`.

## P9 — Admin and system

- [ ] Audit ledger, dangerous-control persistence, service/held/retired state, duplicate writers, logs, reports, review status, configuration, sessions/users, evidence, build/mobile readiness, coverage, replay, and RBAC.
- [ ] Enumerate roles actually assignable from the current user store and prove each protected route is reachable by a real role.
- [ ] Correct or explicitly document impossible-role pages.
- [ ] Verify unknown enums and structured evidence render safely.
- [ ] Run focused RBAC/auth tests and four-view screenshots.

Exit evidence: no dead privileged page, audit persistence is visible, and all control surfaces remain non-mutating unless explicitly authorized.  
Commit: `audit(admin): complete system RBAC and evidence truth`.

## P10 — iOS models, screens, and navigation

- [ ] Enumerate every SwiftUI destination separately from reusable components.
- [ ] Record iPhone TabView/More reachability and iPad NavigationSplitView reachability for every destination.
- [ ] Audit login, dashboard, portfolio, signals, execute, alerts, markets/detail, derivatives, trainer telemetry, predictions, replay, activity, risk, readiness, monitor, health, providers, admin, audit, and settings.
- [ ] Audit deep links, feature flags, empty/error/admin states, REST resources, and WebSocket subscriptions.
- [ ] Map every operator field to the same backend source, unit, freshness, optionality, and status semantics as web.
- [ ] Add optional decoding before requiring new fields and retain fixture tests for old payloads.
- [ ] Add formatter tests for currency, sign, unit, time zone, and freshness.
- [ ] Run SwiftPM build/tests locally; use the macOS lane for actual iPhone/iPad SwiftUI compilation and navigation evidence.

Exit evidence: no orphan screen, per-screen matrix rows, captured fixtures, backward-compatible decoding, and iPhone/iPad reachability proof.  
Commit: split into networking/models and screens/navigation commits.

## P11 — GitHub and Codemagic validation

- [ ] Verify both GitHub macOS workflows against the current commit and inspect their actual run results.
- [ ] Ensure Codemagic runs tests before archive, uses scheme `AIBotV2`, bundle ID `com.wali1984.aibot-v2`, valid monotonically increasing build number, correct artifact paths, and secret names only.
- [ ] Validate signing/profile recognition without printing secret values.
- [ ] Trigger the manual Codemagic iOS workflow when Apple credentials are available.
- [ ] Prove dependency resolution, Swift/Xcode compile, tests, archive, export, and IPA artifact.
- [ ] If credentials are unavailable, record exactly one external blocker with the missing integration/profile names and preserve all local/macOS compile evidence.

Exit evidence: successful Codemagic build URL/artifact metadata, or one precise external signing blocker.  
Commit: `ci(ios): validate GitHub and Codemagic release integration` if configuration changes are required.

## P12 — Final one-shot verifier and deliverables

- [ ] Reconcile latest publisher-lane commits without overwriting held work.
- [ ] Re-run route enumeration and verify the matrix has no missing active routes or impossible roles.
- [ ] Rebuild frontend, backend-edited modules, Swift core, and native iOS through the available macOS/Codemagic lane.
- [ ] Run authenticated and public Playwright sweeps against the built frontend.
- [ ] Verify at least three repaired fields per family against direct API values.
- [ ] Capture two market/dashboard snapshots at least 20 seconds apart.
- [ ] Verify all publisher-held surfaces remain honestly held/stale/unavailable.
- [ ] Re-prove live gate blocked and zero order/leverage/margin mutations.
- [ ] Run `git diff --check` and classify every remaining dirty path by owner.
- [ ] Validate all six required deliverables against their schemas and remove stale contradictions.
- [ ] Final report must state exact branch/commit, web route count, iOS screen count, individual mapped-field count, defects fixed, removals, cross-platform additions, tests/builds, restarts, holds, operator actions, residual blockers, and separate GO/NO-GO decisions.

Exit evidence: every acceptance criterion has a direct witness; warning-only operator-truth gaps remain NO-GO.  
Final commit: `audit(final): publish verified web backend ios completion evidence`.

## Required final GO/NO-GO decisions

- [ ] Web product completeness.
- [ ] iOS code completeness.
- [ ] Codemagic build/archive/export.
- [ ] Paper runtime evidence.
- [ ] Live trading (must remain NO-GO unless separately authorized).

## Immediate next actions

1. Complete P0 and write a refreshed preflight/HOLD_LIST for the current 95-path dirty tree.
2. Complete P1 before claiming the existing 284 screenshots prove field-level coverage.
3. Run P2 against operator-facing commits since the verified UI baseline.
4. Execute P3–P11 only for defects actually proven by P1/P2.
5. Finish with P12 and replace the current summary completion report with the acceptance-criteria-backed report.
