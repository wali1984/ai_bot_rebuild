# THREE-HOUR A+ SYSTEM RECOVERY — HARD-STOP GOAL

## Primary objective

Restore the AI BOT system to a fully online, stable, observable, and internally consistent **A+ operational state within three hours**.

The recovery must include:

* Backend online at `http://localhost:8000`
* Website online at `http://localhost:5173`
* Redis and required runtime services healthy
* All canonical required ingestors running and fresh
* Moralis running correctly
* Liquidation event ingestion and Liquidation Level Engine running correctly
* Feature pipeline producing fresh trusted data
* Trainer/publisher chain producing fresh, trusted runtime output
* Orchestrator, allocator, risk gateway, and paper loop online
* Web and iOS receiving correct operational status
* No duplicate or legacy writers
* No failed required services
* Live trading remaining blocked

This is a **runtime recovery mission**, not another system-wide audit, redesign, documentation project, or theoretical hardening exercise.

---

# Absolute limits

## Time limit

The total elapsed time is capped at exactly **three hours**.

Record the start time immediately as `T0`.

Required phase deadlines:

* `T+15 minutes`: preflight and exact blocker list complete
* `T+45 minutes`: canonical ingestors restored
* `T+75 minutes`: Moralis and liquidation pipeline proven
* `T+120 minutes`: feature/trainer/publisher chain restored
* `T+150 minutes`: orchestrator/risk/paper flow and web/API recovery proven
* `T+165 minutes`: final regression and runtime observation complete
* `T+180 minutes`: hard stop and final report delivered

At `T+150 minutes`, stop starting new repairs. Use the remaining 30 minutes only for:

* Finishing an already active focused test
* Rolling back an unsafe change
* Restarting approved services
* Collecting evidence
* Writing the final report

At `T+180 minutes`, stop immediately. Do not continue with “one final issue,” further investigation, another audit, or another test suite.

## Token limit

Use no more than **10% of the available Codex usage shown at the start of this goal**.

At startup:

1. Record the available usage shown in Cursor.
2. Calculate the 10% maximum.
3. Record the limit in the recovery checkpoint.

Token controls:

* At 7% usage: stop exploration and complete only the current repair.
* At 8% usage: run final focused validation.
* At 9% usage: stop editing and produce the final report.
* At 10% usage: terminate immediately.

Do not launch a large agent swarm.

Maximum concurrency:

* One primary Codex agent
* At most one temporary read-only specialist
* Never more than two agents total

Do not regenerate the system atlas, reverse-engineering documents, dependency graph, symbol index, or low-level repository inventory.

Do not reread the full repository.

Use targeted source inspection only.

---

# Definition of “A+”

A+ in this goal means **operational and integration A+**.

It does not mean guaranteed profitability, guaranteed 1,000× returns, or fabricated positive performance evidence.

The system receives A+ only if every gate below passes:

1. Required services are active with no crash loop.
2. All canonical required ingestors are publishing fresh valid data.
3. Optional providers are classified honestly and do not incorrectly fail the system.
4. Moralis is operational and its data is usable or honestly quarantined with a precise reason.
5. Liquidation event ingestion and the Liquidation Level Engine are publishing valid, fresh, symbol-correct outputs.
6. Feature data is fresh, final, causally valid, and available to downstream consumers.
7. Trainer/publisher output is fresh and trusted.
8. Orchestrator, allocator, and risk gateway consume matching decision identities.
9. Paper runtime completes cycles without duplicate writers or accounting violations.
10. Backend and web expose the same runtime truth.
11. All required focused tests pass.
12. Live trading remains disabled.

Do not award A+ if one of these gates is warning, unknown, stale, held, unverified, or based only on unit tests.

If A+ cannot honestly be reached within three hours, deliver the actual grade and the smallest remaining blocker list. Never alter grade rules to produce A+.

---

# Hard safety boundary

Do not:

* Enable live trading.
* Add live execution symbols.
* Approve live execution.
* Submit, cancel, or modify an exchange order.
* Change exchange margin mode.
* Change live exchange leverage.
* Relax provenance, finality, freshness, risk, allocator, or loss controls.
* Convert missing evidence into PASS.
* Invent maintenance-margin values.
* Fabricate predictions, signals, provider data, or profitability evidence.
* Delete historical evidence.
* Rewrite historical paper trades without operator authorization.
* Use broad Redis `KEYS`.
* Run an unbounded Redis scan.
* Print credentials, tokens, API keys, or secret values.

Required final safety proof:

* Live gate remains blocked.
* Order submission remains false.
* Exchange action count remains zero.
* No live leverage or margin mutation occurred.

---

# Phase 1 — Fifteen-minute preflight

Do not edit code during the first preflight.

Record:

* Branch and HEAD
* Dirty files
* Recent Codex commits
* Active and failed `ai-bot-v2-*` services
* Duplicate processes
* Legacy writers
* Backend/frontend health
* Redis health
* Required service inventory
* Latest timestamps for critical data families
* Current live-gate state

Create:

`claude_worklog/codex/THREE_HOUR_RECOVERY_CHECKPOINT.md`

Identify only the **five highest-impact runtime blockers**.

A blocker qualifies only when it directly prevents one of these:

* Data ingestion
* Moralis operation
* Liquidation-level generation
* Feature generation
* Trusted publisher output
* Orchestrator/risk/paper flow
* Backend/frontend availability

Do not add theoretical defects to the active queue.

Freeze all other findings in a deferred list.

---

# Phase 2 — Restore the canonical ingestor plane

Enumerate canonical ingestors from current systemd units, source configuration, and `/api/v2/ingestors/status`.

Do not rely on an old hardcoded list.

For every required ingestor prove:

* Exactly one authoritative writer
* Service active
* No restart loop
* Current heartbeat
* Current source-event timestamp
* Expected Redis key family populated
* Payload parses correctly
* Symbol and timeframe correct
* Feed-specific freshness threshold satisfied
* Consumer can read the produced record

Required providers and data families include, where configured:

* Binance market data
* KuCoin market data
* CoinAnk
* CoinGlass
* CoinAPI, classified as optional when configuration says optional
* Moralis
* OHLCV closed candles
* Mark price
* Funding
* Open interest
* Order book
* Trades
* Liquidations
* Technical-analysis features
* Dynamic symbol universe
* Alternative-data confluence

Do not mark an optional provider failure as a core-system failure.

Do not mark a required provider healthy merely because its process exists.

Restart only canonical units. Stop duplicate or retired writers after proving ownership.

---

# Phase 3 — Moralis recovery

Moralis is a mandatory focus item.

Prove the complete chain:

1. Moralis scheduler service is active.
2. Scheduler is not unintentionally paused.
3. Credentials are detected without printing them.
4. CU ledger is available.
5. Daily and monthly CU values are valid.
6. `provider_polling_blocked` is false, unless the budget is legitimately exhausted.
7. Rate limiting and exact CU pacing work.
8. Watchlist is populated or honestly reports why it is empty.
9. Candidate, queued, verified, and admitted counts reconcile.
10. Token identity map is valid.
11. Unverified identities are quarantined rather than admitted.
12. Endpoint payload counts are nonzero where expected.
13. Raw records and admitted feature counts are reported separately.
14. Feature bridge uses causally valid records.
15. Trainer isolation status and rejection reasons are explicit.
16. `/api/v2/providers/status` and relevant web/iOS payloads reflect the same state.

Required Moralis runtime evidence:

* Exact service name and PID
* Last successful poll
* CU spent and remaining
* Scheduler state
* Watchlist count
* Verified identity count
* Quarantine count
* Raw record count
* Admitted feature count
* Freshness age
* Current status and reason

Moralis passes only when the data path works. A green process with zero usable payloads is not A+.

---

# Phase 4 — Liquidation pipeline and Liquidation Level Engine

Treat these as separate stages:

1. Raw liquidation event ingestor
2. Event normalization
3. Enhanced liquidation processing
4. Liquidation-level calculation
5. Level publication
6. API exposure
7. Consumer and UI exposure

Discover and verify the exact current services and Redis keys from source. Do not guess key names.

For the raw liquidation feed prove:

* Binance and any configured secondary source connect
* Events are arriving
* Symbols are valid
* Side and quantity semantics are correct
* Event timestamps are current
* No duplicate event writer exists
* Event retention is adequate but bounded

For the Liquidation Level Engine prove:

* Canonical service active
* Input events are current
* Reference price is current and symbol-matched
* Quantity and notional units are correct
* Long and short liquidation levels are not inverted
* Output levels change when input price/events change
* No fixed or stale reference price is reused
* No cross-symbol contamination
* Confidence or quality metadata is present
* Generated timestamp is current
* Required symbols have coverage
* Redis output parses
* API returns the same levels
* Website displays the same values and units
* Missing inputs render unavailable, not zero

Capture two engine snapshots at least 30 seconds apart and prove either:

* Inputs and levels updated, or
* No new events occurred and the output correctly reports that condition

A running service with stale levels does not pass.

---

# Phase 5 — Restore feature, trainer, and publisher chain

Do not reopen a six-day provenance redesign.

Use the current committed provenance implementation.

Identify the smallest concrete reason the publisher is not producing trusted output.

Validate this exact chain:

1. Closed/final market candle
2. Feature snapshot
3. Snapshot receipt
4. Feature availability time
5. Trainer-compatible schema
6. Model/checkpoint identity
7. Prediction publication
8. Routeability/trust result
9. Orchestrator consumption

Repair only direct runtime blockers.

Do not introduce a new receipt format, new archive, new registry, new attestation family, or new architecture unless the current implementation cannot run because of one proven coding defect.

Required proof:

* Fresh feature snapshot exists
* Feature width matches the active checkpoint
* No future-frame data
* Snapshot receipt validates
* Trainer service consumes the snapshot
* Publisher generates a fresh prediction
* Prediction contains finality and cutoff lineage
* Prediction trust result is explicit
* At least one prediction cycle completes without exception
* If no prediction is routeable, the exact blocker is shown

Do not weaken trust gates to manufacture a routeable prediction.

---

# Phase 6 — Orchestrator, risk, allocator, and paper runtime

Verify matching identity across:

* Prediction
* Orchestrator decision
* Risk decision
* Allocation
* Paper admission
* Paper fill or explicit denial

Required invariants:

* Orchestrator decision ID matches the candidate.
* Risk decision is authoritative and current.
* Missing risk never becomes PASS.
* Only one canonical writer owns each decision namespace.
* Proposed leverage is distinct from executed leverage.
* `notional = quantity × execution price`.
* `margin = notional ÷ effective leverage`.
* Margin reservations include existing and same-cycle positions.
* No duplicate paper writer exists.
* Paper service completes at least two cycles.
* Every blocked candidate has a precise reason.
* No exception class leaks into operator-facing text.

A+ does not require forcing a paper trade. It requires a functioning chain that can either admit a valid candidate or correctly deny an invalid candidate.

If a valid trusted candidate exists, prove one complete paper-only path.

If none exists, prove the entire chain reached a legitimate evidence-based denial.

---

# Phase 7 — Backend and website recovery

Verify:

* Backend `/health` and required API endpoints return 200.
* Frontend returns 200.
* Authentication works.
* Runtime WebSockets connect.
* No required endpoint returns HTML instead of JSON.
* No operator page shows stale data as live.
* Moralis status is visible.
* Liquidation engine status is visible.
* Required ingestor statuses are visible.
* Trainer/publisher status is visible.
* Live gate is visibly blocked.
* No page is blank, crashed, or permanently loading.

Perform only a focused website smoke test in this recovery goal:

* Dashboard
* Markets
* Ingestors/providers
* Moralis provider panel
* Liquidation/derivatives panel
* Trainer/prediction status
* Risk/paper status
* System health

Do not restart a full field-by-field UI redesign inside this three-hour recovery.

---

# Testing requirements

Use focused tests only.

Required:

* Syntax/compile checks for edited Python files
* Unit tests directly covering each repaired blocker
* Ingestor status/API tests
* Moralis scheduler/budget/identity tests
* Liquidation engine normalization and publication tests
* Feature/publisher trust-chain tests
* Orchestrator/risk identity tests
* Paper accounting invariant tests
* Frontend TypeScript check if frontend changed
* Swift build only if iOS files changed
* `git diff --check`

Do not run the entire historical test estate unless focused tests expose a shared regression.

A failing unrelated legacy test must be documented, not allowed to consume the remaining recovery window.

---

# Change limits

To prevent another uncontrolled expansion:

* Maximum 20 source files edited
* Maximum 4 commits
* Maximum one new small status endpoint
* No new subsystem
* No new database
* No new receipt family
* No new feature registry
* No documentation rewrite
* No architecture redesign
* No broad formatting changes
* No historical data rewrite
* No live execution changes

If recovery requires exceeding these limits, stop and report the architectural blocker instead of continuing.

---

# Restart order

Use controlled restarts in this order:

1. Canonical market metadata and core ingestors
2. Moralis
3. Liquidation raw ingestor
4. Liquidation Level Engine
5. Feature pipeline
6. Trainer
7. Prediction publisher
8. Orchestrator/arbitrator
9. Risk gateway
10. Adaptive tuner, if authoritative configuration exists
11. Paper loop
12. Backend
13. Frontend

After each restart verify:

* New PID
* Start timestamp
* `NRestarts`
* Heartbeat
* Expected output key
* No duplicate old PID
* No failed dependent unit

Do not restart live order services.

---

# Evidence required before declaring A+

Create:

`claude_worklog/codex/THREE_HOUR_A_PLUS_RECOVERY_REPORT_<timestamp>.md`

The report must contain:

## Timing and usage

* Start time
* End time
* Total elapsed time
* Starting available usage
* Maximum permitted usage
* Actual usage
* Confirmation that the 10% limit was respected

## Changes

* Files edited
* Commits
* Services restarted
* Duplicate/legacy services stopped
* Rollbacks performed

## Runtime gates

For every gate report `PASS`, `FAIL`, or `NOT APPLICABLE`:

* Backend
* Frontend
* Redis
* Core ingestors
* Optional ingestors
* Moralis scheduler
* Moralis CU budget
* Moralis watchlist and identity map
* Raw liquidation feed
* Liquidation Level Engine
* Feature pipeline
* Trainer
* Prediction publisher
* Orchestrator
* Risk gateway
* Allocator
* Paper runtime
* Web operational status
* Live-trading lock

## Runtime proof

Include exact:

* PID
* Service start time
* Restart count
* Latest heartbeat
* Latest source event time
* Redis key or endpoint
* Freshness age
* Record count
* Current classification
* Blocker reason, when blocked

## Final grade

Report one:

* `A+ OPERATIONAL — END-TO-END ONLINE`
* `A OPERATIONAL — ONLINE WITH NONCRITICAL DEGRADATION`
* `B OR LOWER — PARTIAL RECOVERY`
* `NO-GO — ROLLED BACK OR STILL BLOCKED`

A+ may be reported only when every required gate is proven green through runtime evidence.

## Remaining work

Maximum five items, each with:

* Exact blocker
* Owning file/service
* Required action
* Whether operator authorization is needed
* Smallest next validation step

Do not end with an open-ended promise to continue working.

---

# Mandatory operating behavior

Do not circle.

Do not repeatedly audit the same component.

Do not keep discovering lower-priority defects after the active five-blocker list is established.

Do not expand the scope because a new theoretical weakness is noticed.

When a direct blocker is fixed:

1. Test it.
2. Restart its canonical service.
3. Verify live output.
4. Commit.
5. Move to the next blocker.

When a repair fails twice:

1. Revert the unsuccessful change.
2. Record the exact evidence.
3. Mark the blocker unresolved.
4. Continue to the next independent recovery item.

The objective is to restore the running system, not to achieve theoretical perfection.
