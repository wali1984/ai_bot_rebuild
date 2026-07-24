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

Tasks requested:

# FINAL WEB, BACKEND, AND iOS PRODUCT-COMPLETION AUDIT

## Mission

Bring the complete operator product to a verified, internally consistent, production-quality state across:

* Web frontend running at `http://localhost:5173`
* FastAPI backend running at `http://localhost:8000`
* Swift iOS application under `v2/mobile`
* GitHub and Codemagic iOS build configuration
* All operator-facing Redis, API, WebSocket, static-payload, and status contracts

This is a product-completion audit, not another full reverse-engineering exercise. The system atlas, master documentation, prior audits, previous fixes, and current risk register already exist. Reuse them. Do not regenerate the complete atlas or reread the entire repository without a precise reason.

The objective is to ensure that every visible card, field, chip, table cell, chart, banner, button, route, screen, and status accurately reflects the current backend truth, and that every new operator-relevant backend capability is available on both web and iOS where applicable.

Do not promise or claim that the system can guarantee the 1,000× target. Do not modify trading strategy, edge logic, live execution, leverage policy, risk authority, trainer admission, or publisher provenance merely to make the UI look healthy.

---

# 1. Hard safety and ownership boundaries

## Live execution

The live gate must remain blocked unless separately and explicitly authorized by the operator.

Do not:

* Enable live order placement.
* Add execution symbols.
* Change operator approval.
* Submit, cancel, or modify exchange orders.
* Change live margin mode or leverage.
* Weaken risk, provenance, point-in-time, freshness, or evidence gates.
* Turn a missing or stale value into a fabricated healthy value.

Verify after every backend restart that:

* `live_gate` remains blocked.
* No live order was submitted.
* No exchange mutation occurred.
* No live leverage or margin mutation occurred.

## Codex publisher hold

Codex is still completing the authenticated publisher/provenance lane.

Before editing, identify the exact dirty files, services, Redis keys, and current commits belonging to that lane. Put them in a written `HOLD_LIST`.

Do not edit, restart, supersede, or build assumptions on top of unfinished publisher-owned files.

Expected temporary conditions may include:

* Stale or absent predictions.
* Empty paper signal lists.
* Zero new paper intents.
* Stale trainer evidence.
* Held trainer, replay, or guardian services.
* Missing newly proposed publisher fields.

These are not UI defects when the UI labels them clearly as held, stale, unavailable, blocked, or awaiting trusted evidence.

Hold these items and continue completing all independent web, API, observability, and iOS work.

---

# 2. Mandatory preflight

Perform this before any audit or edit.

## Repository state

Record:

* Current branch.
* HEAD commit.
* Upstream branch and divergence.
* Full dirty-file list.
* Untracked-file list.
* Recent Codex and Claude commits.
* Running frontend/backend/mobile-related processes.
* Active, inactive, failed, duplicate, legacy, and deliberately held systemd services.

Do not use `git add -A`.

Never edit a dirty file until its owner and current work are understood. Preserve all unrelated changes.

Create:

`claude_worklog/codex/FINAL_PRODUCT_AUDIT_PREFLIGHT_<timestamp>.md`

It must include:

* Files safe to edit.
* Files held because Codex is still working on them.
* Existing fixes that must be regression-tested.
* Existing known defects that remain unresolved.
* Current live-gate proof.

## Runtime health

Confirm:

* Frontend returns HTTP 200 on port 5173.
* Backend returns HTTP 200 on port 8000.
* Authentication works.
* Redis responds.
* WebSocket endpoints connect.
* iOS API base URLs match the correct environment.
* Codemagic workflow references the correct repository, scheme, bundle identifier, signing configuration, and branch.

## Cursor/Codex stability

Before starting a long run:

* Use one Cursor window and one repository.
* Do not launch more than two concurrent subagents.
* Do not run broad repository indexing or regenerate the complete system atlas.
* Do not paste large logs or generated atlas files into model context.
* Use targeted `grep`, `git show`, direct file reads, and bounded API/Redis queries.
* Never run `redis-cli KEYS`.
* Never use an unbounded `SCAN`, `scan_iter`, filesystem traversal, or log tail over the full data set.
* Use exact Redis keys whenever known.
* Any Redis scan must have a cursor-iteration cap, result cap, and wall-clock limit.
* Exclude runtime archives, generated payloads, `.git`, virtual environments, `node_modules`, build output, large replay archives, `.codex`, and Cursor state directories from watchers and searches.

If Codex chat remains on loading after initialization:

1. Stop further agents and preserve a checkpoint.
2. Use `Developer: Reload Window`.
3. Retry once.
4. If still stuck, fully close Cursor before database maintenance.
5. Do not repeatedly launch new sessions against the same wedged extension process.

---

# 3. Resource and token-control contract

Quality must not be reduced, but work must be divided into bounded slices.

## Context budget

* At approximately 30–35% session usage, write a checkpoint.
* Do not allow one session to exceed approximately 45–50%.
* Continue in a new session from the checkpoint instead of relying on automatic compaction.
* Never start a new major phase when the current session is already above 35%.

## Concurrency

Maximum:

* One primary Codex agent.
* One read-only specialist at a time.
* No more than two agents running concurrently.

Do not launch a ten-agent or eleven-agent audit swarm.

## Commit discipline

Commit after each coherent surface or contract slice, normally no more than:

* 10–20 edited files, or
* one frontend page family, or
* one backend endpoint family, or
* one iOS feature family.

Each commit must include:

* Exact scope.
* Tests run.
* Runtime verification performed.
* Explicit statement that live execution remained blocked.

## Checkpoint file

Continuously update:

`claude_worklog/codex/FINAL_PRODUCT_AUDIT_CHECKPOINT.md`

Include:

* Completed surfaces.
* Open defects.
* Held publisher items.
* Current branch and commit.
* Tests and screenshots completed.
* Exact next command.
* Token/context usage when checkpointed.
* Any process or service that was restarted.

This file must allow another session to resume without rereading the full conversation.

---

# 4. Establish the authoritative product inventory

Do not trust old route lists or documentation alone.

## Web inventory

Enumerate all currently mounted routes from:

* Route registry.
* Route files.
* Navigation configuration.
* Redirect and legacy-route maps.
* Admin route definitions.
* Dynamic symbol and ingestor routes.

Classify each route:

* Canonical active route.
* Intentional redirect.
* Obsolete dead route.
* Missing canonical replacement.
* Role-inaccessible route.
* Publisher-held surface.

A redirect is valid only when the destination contains all required functionality. If functionality was lost during consolidation, restore it on the canonical page or remove the obsolete navigation entry.

## Backend inventory

Map all operator-facing endpoints used by:

* Web.
* iOS.
* WebSockets.
* Static payload pages.
* Public routes.
* Authenticated trader routes.
* Admin/operator routes.

Identify endpoints that:

* Return stale envelopes around old content.
* Return fields that are never rendered.
* Use fields or keys that no longer have writers.
* Read old Redis namespaces.
* Perform unbounded scans.
* Return fabricated defaults.
* Return contradictory units or semantics.

## iOS inventory

Enumerate every:

* SwiftUI screen.
* Navigation destination.
* View model.
* API model.
* WebSocket subscription.
* REST endpoint.
* Feature flag.
* Deep link.
* Empty state.
* Error state.
* Admin/operator state.
* iPhone and iPad navigation path.

Determine whether each screen is reachable.

## Codemagic inventory

Audit:

* `codemagic.yaml` and related workflow files.
* Xcode project or Swift package references.
* Build scheme.
* Release configuration.
* Bundle identifier.
* App version/build-number handling.
* Signing and provisioning environment names.
* App Store Connect integration.
* Generated assets.
* Required secrets by name only; never print secret values.
* Artifact paths.
* Test execution.
* Cache paths.
* Branch triggers.
* GitHub status reporting.

---

# 5. Use two complementary audit passes

## Pass A — surface-first visual and field audit

For every active web route and every iOS screen:

1. Open the surface.
2. Record every visible field, card, chip, badge, row, column, chart series, action, error, and empty state.
3. Identify the exact endpoint, WebSocket resource, or payload file used.
4. Query the same source directly.
5. Compare the rendered value against source truth.
6. Verify:

   * Field name.
   * Numeric value.
   * Sign.
   * Currency placement.
   * Unit.
   * Scaling.
   * Percentage basis.
   * Timestamp.
   * Time zone.
   * Freshness calculation.
   * Status classification.
   * Optional versus required source semantics.
   * Null and unavailable behavior.
   * Role/access state.
   * Source provenance.
7. Record PASS or a defect for every field.

No sampling is allowed. Count the fields checked.

Required web viewports:

* 1600×1000.
* 1440×900.
* 390×844.
* At least one tablet-width viewport.

Validate:

* No overlap.
* No clipping.
* No horizontal overflow unless deliberately scrollable.
* No unreadable ticker collisions.
* No broken modal.
* No raw JSON.
* No HTML returned where JSON is expected.
* No `undefined`, `NaN`, `[object Object]`, or parse errors.
* No fake green status beside stale or unavailable data.
* No permanently spinning panel.
* No dead button or link.
* No route loop.

For iOS, verify both iPhone and iPad navigation logic where supported.

## Pass B — change-first contract audit

Review backend commits since the last verified UI baseline.

For every commit that changes an operator-facing publisher or payload:

* Extract new Redis keys.
* Extract new fields.
* Extract renamed fields.
* Extract removed fields.
* Extract new enums and status semantics.
* Identify producer and owner.
* Identify backend API exposure.
* Identify web exposure.
* Identify iOS exposure.
* Live-verify the current payload.

Classify each item:

* `WIRED`
* `PARTIAL`
* `UNEXPOSED`
* `BROKEN`
* `INTERNAL`
* `HELD_PUBLISHER`
* `OBSOLETE`

Treat silent field renames as high-priority defects.

Do not create UI for deep internal CAS, cryptographic, replay, or attestation mechanics unless they produce an operator-actionable status. Operator-actionable items include:

* Why predictions are blocked.
* Which provenance or trust check failed.
* Whether a provider is quarantined.
* Whether margin invariants hold.
* Whether leverage-bracket evidence is authenticated.
* Whether an adaptive tuner is missing or non-authoritative.
* Whether a service is deliberately held.
* Whether data is stale, optional, isolated, or absent.

---

# 6. Required functional areas

Audit and complete every relevant area below.

## Global shell

* Navigation.
* Route redirects.
* Authentication state.
* User role display.
* Runtime truth strip.
* Market feed state.
* Live gate state.
* PnL strip.
* Global ticker.
* Responsive behavior.
* Error boundary.
* Service worker and asset MIME behavior.
* Static evidence payload serving.

## Dashboard and trading

* Account values.
* Balances.
* Gross and net PnL.
* Open, closed, and historical positions.
* Quantity.
* Notional.
* Margin.
* Leverage.
* Stop and liquidation values.
* Hold duration.
* Signal freshness.
* Risk verdict.
* Orchestrator action.
* Paper/live mode.
* Trade journal.
* Empty held-publisher state.

## Markets

* Prices.
* Mark and index prices.
* Base volume versus quote turnover.
* 1h, 4h, 24h, and 7d change.
* Spread.
* Funding.
* Open interest.
* Open-interest delta.
* Long/short ratio.
* Liquidations.
* Depth.
* Whale walls.
* Chart history.
* Technical indicators.
* Dynamic universe membership.
* Watchlist persistence.
* Gainers and losers.
* Source reconciliation and units.

Never show data from two incompatible sources under the same label without source names or reconciliation.

## Ingestors and providers

* Per-feed liveness thresholds.
* Optional versus required source classification.
* Retryable versus failed.
* CU and request budgets.
* Remaining quota.
* Scheduler state.
* Quarantine counts.
* Verified-map counts.
* Feature-admission counts.
* Raw-versus-admitted records.
* Provider isolation reason.
* Data cutoff/finality.
* Partial bundle state.
* Universe additions/removals.
* Service and writer ownership.

## Trainer and AI

While the publisher lane remains held, ensure the UI honestly explains:

* Current trainer state.
* Current publisher hold.
* Prediction age.
* Trust-gate blockers.
* Checkpoint identity and source.
* Service liveness versus probe liveness.
* CUDA evidence state.
* Replay/challenger state.
* Feature lineage state.
* Why no routeable predictions exist.

Do not show `Live` merely because a wrapper payload was recently republished.

## Risk, allocator, leverage, and margin

Surface:

* Live gate.
* Fail-closed state.
* Latest canonical risk verdict.
* Margin used.
* Margin free.
* Margin buffer.
* Margin invariant status and failure reasons.
* Executed leverage, distinct from proposed leverage.
* Adaptive leverage ceiling.
* Bracket-evidence state.
* Bracket authentication state.
* Liquidation distance where valid.
* Missing evidence as missing, never as zero.

Do not edit the risk or sizing engines in this goal unless an API projection bug is proven and the engine-owned file is not on the publisher hold list.

## System and admin

* Audit ledger.
* Dangerous-control audit persistence.
* Service status.
* Deliberately stopped services.
* Retired service holds.
* Duplicate or legacy writers.
* Logs.
* Reports.
* Codex review status.
* Configuration truth.
* User/session truth.
* Operator evidence.
* Build validation.
* Mobile readiness.
* Data coverage.
* Backtest and replay truth.
* RBAC reachability for roles that actually exist.

A page requiring a role that no human account can possess is a dead page and must be corrected or explicitly documented.

## iOS parity

Every operator-relevant feature added to web must be evaluated for iOS parity.

For each backend field:

* Add optional decoding fields first.
* Preserve backward compatibility.
* Show honest null/unavailable states.
* Match units and freshness semantics with web.
* Match optional/isolated/blocked status colors and explanations.
* Avoid hardcoded feed thresholds.
* Verify iPhone and iPad navigation.
* Ensure no screen is orphaned.

---

# 7. Removal rules

An item may be removed only when all are true:

1. Its source is permanently retired, not temporarily held.
2. No active backend producer exists.
3. No web or iOS consumer relies on it.
4. No operator workflow requires it.
5. A canonical replacement exists or the function is truly obsolete.
6. Removal does not erase audit, safety, or failure information.

For every removal record:

* Source file.
* Consumer search.
* Replacement, if any.
* Reason.
* Screenshot before and after.
* Test proving navigation and build remain valid.

Do not remove a held publisher surface. Keep it and label the hold honestly.

---

# 8. Fixing procedure

Work sequentially in these slices:

1. Shared contracts and API projection defects.
2. Global shell and navigation.
3. Markets and charts.
4. Ingestors and providers.
5. Trading, portfolio, margin, and risk displays.
6. Trainer and AI observability.
7. Admin and system pages.
8. iOS models and shared networking.
9. iOS screens and navigation.
10. Codemagic and GitHub build integration.
11. Final parity and visual verification.

For each slice:

* Audit.
* Write defect list.
* Fix.
* Run focused tests.
* Run relevant build.
* Live-verify.
* Capture screenshots.
* Commit.
* Update checkpoint.

Do not mix unrelated slices in one commit.

---

# 9. Mandatory testing

## Backend

At minimum:

* Python syntax/compile checks for every edited file.
* Focused unit tests for changed endpoints and projections.
* API contract tests.
* Authentication and RBAC tests.
* WebSocket resource tests.
* Null, stale, missing, optional, and malformed-payload tests.
* Bounded-query performance tests for any Redis aggregation.

Any operator endpoint should return within its declared timeout on the real 1.5M-plus-key Redis instance.

## Web

Run:

* TypeScript typecheck.
* Unit/component tests where present.
* Production build.
* Playwright authenticated route sweep.
* Playwright unauthenticated public-route sweep.
* Mobile-width visual checks.
* Console-error collection.
* Network-failure collection.
* Screenshot evidence.

Restart and test the built frontend, not only the Vite source view.

## iOS

Run:

* `swift build`.
* `swift test` where available.
* Model decoding tests using captured live endpoint fixtures.
* Navigation/reachability checks.
* Optional-field backward compatibility tests.
* Currency, sign, unit, and freshness formatter tests.

Where local Linux cannot build SwiftUI/Xcode targets, use static compile checks available locally and ensure Codemagic performs the real Xcode build.

## Codemagic

Trigger or validate a build after code completion.

Prove:

* Dependency resolution succeeds.
* Swift/Xcode compile succeeds.
* Tests run.
* Signing configuration is recognized.
* Archive/export step succeeds, or record the exact external signing blocker.
* Generated IPA/artifact path is correct.
* Build number and version are valid.
* No secret value appears in logs.

---

# 10. Final one-shot verifier

After all commits:

1. Rebase or reconcile against the latest publisher-lane commits without overwriting them.
2. Rebuild backend/frontend/iOS.
3. Restart only approved read-only or paper services.
4. Enumerate every active web route again.
5. Screenshot every active route.
6. Verify every route has:

   * No crash.
   * No blank page.
   * No parse error.
   * No dead loading state.
   * No console error.
   * No failed required network request.
7. Recheck at least three repaired fields from every surface family against direct API values.
8. Capture two market/dashboard snapshots at least 20 seconds apart to prove updates.
9. Verify all held publisher surfaces still show honest hold/stale status.
10. Verify live gate remains blocked.
11. Run final web and Swift builds.
12. Check `git diff --check`.
13. Check working tree and identify any remaining Codex-owned dirty files.

Do not declare completion if there are warning-only gaps that affect operator truth.

---

# 11. Required deliverables

Create:

## A. Product coverage matrix

`claude_worklog/codex/FINAL_WEB_IOS_PRODUCT_COVERAGE_MATRIX_<timestamp>.json`

For every route/screen:

* Surface.
* Role.
* Endpoint/resource.
* Fields checked.
* Screenshot path.
* Status.
* Defect IDs.
* Fixed commit.
* Held reason, if applicable.

## B. Backend-to-surface mapping

`claude_worklog/codex/FINAL_BACKEND_WEB_IOS_FIELD_MAP_<timestamp>.json`

For each operator-facing field:

* Producer.
* Redis key or source.
* API endpoint.
* Web consumer.
* iOS consumer.
* Unit.
* Freshness contract.
* Optional/required semantics.
* Current status.

## C. Defect register

`claude_worklog/codex/FINAL_PRODUCT_DEFECT_REGISTER_<timestamp>.md`

Classify:

* Fixed.
* Held publisher.
* Codex-owned in-flight.
* External operator action.
* Genuine missing producer.
* Obsolete and removed.
* Not applicable.

## D. Visual evidence index

`claude_worklog/codex/FINAL_VISUAL_EVIDENCE_INDEX_<timestamp>.md`

Link every screenshot and describe what was verified.

## E. Codemagic report

`claude_worklog/codex/FINAL_IOS_CODEMAGIC_BUILD_REPORT_<timestamp>.md`

## F. Final completion report

`claude_worklog/codex/FINAL_PRODUCT_COMPLETION_REPORT_<timestamp>.md`

Include:

* Exact branch and final commit.
* Number of web routes inspected.
* Number of iOS screens inspected.
* Number of individual fields validated.
* Number of defects fixed.
* Number of obsolete items removed.
* Number of new backend items added to both web and iOS.
* Tests and builds.
* Services restarted.
* Held publisher items.
* Operator actions.
* Residual blockers.
* Live-gate proof.
* Explicit GO/NO-GO for:

  * Web product completeness.
  * iOS code completeness.
  * Codemagic build.
  * Paper runtime evidence.
  * Live trading.

---

# 12. Acceptance criteria

The goal is complete only when:

* Every active web route has been visually inspected.
* Every iOS screen and navigation destination has been audited.
* Every rendered field has been mapped to a live source or clearly marked unavailable.
* Every recent operator-facing backend field is classified and wired, held, internal, or rejected as not applicable.
* Web and iOS show matching semantics.
* No required page is inaccessible because of an impossible role.
* No active link loops or redirects away from required functionality.
* No fake freshness.
* No fake zero.
* No wrong sign.
* No wrong unit.
* No contradictory source labels.
* No unbounded Redis or filesystem traversal was introduced.
* Frontend build passes.
* Swift build/tests pass.
* Codemagic build is validated or has one precisely documented external blocker.
* Live trading remains disabled.
* Publisher-held items remain untouched and honestly displayed.
* The repository contains a precise resume checkpoint if any Codex-owned publisher work is still unfinished.

Do not stop at “tests pass.” Completion requires source validation, visual validation, API comparison, web/iOS parity, and recorded evidence.
