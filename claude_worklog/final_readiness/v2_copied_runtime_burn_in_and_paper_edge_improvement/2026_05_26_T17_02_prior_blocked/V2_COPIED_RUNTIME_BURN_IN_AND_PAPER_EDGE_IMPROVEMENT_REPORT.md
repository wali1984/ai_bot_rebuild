# V2 Copied Runtime Burn-In and Paper-Edge Improvement — Snapshot Report

- **Task ID**: `v2_copied_runtime_burn_in_and_paper_edge_improvement`
- **Generated EST**: 2026-05-26T17:02:47-0400
- **Generated UTC**: 2026-05-26T21:02:47Z
- **Git HEAD**: 10513bbe0517fd81c9c87e4672bb15486a083c02
- **GO/NO-GO**: `V2_COPIED_RUNTIME_BURN_IN_AND_PAPER_EDGE_IMPROVEMENT_BLOCKED`
- **Live recommendation**: `BLOCK_LIVE_PAPER_EDGE_NOT_PROVEN`
- **Canary recommendation**: `BLOCK_LIVE_PAPER_EDGE_NOT_PROVEN` (no `CANARY_OPERATOR_DECISION_REQUIRED` emitted because the edge gate has not been crossed)

## Why BLOCKED

The 24h war-room executor already ran with the copied-runtime expansion
in place: **76 dataset rows / 60 train / 16 validation**, with edge verdict
`INCONCLUSIVE_OBSERVED_EVIDENCE_MISSING` on all three operator profiles
(aggressive / balanced / conservative). Both `after-cost expectancy`
and `lower CI` failed every profile; `min_sample_count` and
`max_false_negative_rate` failed balanced + conservative. Edge cannot be
claimed and live / canary cannot be unblocked from this evidence base.
The runtime IS healthy — the EDGE is not.

## Phase summary (all 7 artifacts in this directory)

| Phase | Artifact | Headline |
|------|----------|----------|
| 1 | `v2_copied_runtime_burn_in_status.json` | **30 services + 28 timers + 2 slices active**; 27/30 services zero restarts; 1 service (position-history-tracker) has 21 restarts which is *expected* from its `--max-seconds-per-session 600` design |
| 2 | `v2_liquidation_bridge_levels_runtime_impact.json` | liquidation-bridge + levels-engine **wrapped and running 53 min**; `v2:liquidations:events` stream exists but `XLEN=0`; `v2:market:liquidation_levels:*` has 0 keys; `live_binance_liquidations.py` confirmed excluded from every active service |
| 3 | `v2_dynamic_symbol_runtime_evidence.json` | **27 discovered symbols** (25-baseline + 2 intelligence-only); baseline coverage 25/25; resolver default branch active in every running ingestor; no `V2_SYMBOL_PROFILE` env override leaked into a service |
| 4 | `v2_feature_ta_trainer_runtime_impact.json` | Redis feature output FRESH across 27 symbols (170 unified-feature keys); operator-runtime payloads for feature-pipeline + owned-trainer + liquidation-ingestor are STALE (last refresh 2026-05-15) — services run but don't emit operator_runtime mirror; trainer role correctly labeled `copied_parity_baseline_bridge` (not v2_native_readiness) |
| 5 | `v2_post_copied_runtime_paper_edge_status.json` | Edge **NOT proven**: INCONCLUSIVE on all 3 profiles; 16 validation rows; trainer vs strategy comparison cannot pick a winner |
| 6 | `v2_trading_platform_runtime_ui_verification.json` | **31 frontend pages**, trading-platform classification (trader / paper-trading / executions / signals / symbols / markets / market-intelligence / exchange-manager / risk via config+strategy admin); backend service active 220 min; rendered screenshot evidence deferred to operator/visual-regression lane |
| 7 | `v2_copied_runtime_burn_in_remediation_status.json` | **7 remediation tasks surfaced**: 3 stale operator_runtime payload refreshes, 2 liquidation diagnostic probes, 1 24h war-room re-run, 1 rendered UI evidence pass. 0 require operator gates. Spark automation runner already active to consume queued tasks |

## Runtime health (Phase 1)

Post-reboot (2026-05-26 13:22:02 EDT, **220 min burn-in window so far**):

- **58 ai-bot-v2-\* user units active** (30 services + 28 timers, plus 2 slices)
- **27 of 30 services have 0 restarts**
- **1 service has 21 restarts** (position-history-tracker — designed for 600s/session, total uptime ~3.5h matches expectations; **not a failure**)
- **2 services newly added this session** (liquidation-bridge, liquidation-levels-engine) — 53 min uptime, 0 restarts
- **freeze root cause cleared** (wma-audits.service storm halted earlier this session)

## Liquidation impact (Phase 2)

- `ai-bot-v2-liquidation-bridge.service` ✅ active, 0 restarts
- `ai-bot-v2-liquidation-levels-engine.service` ✅ active, 0 restarts
- `ai-bot-v2-liquidation-wss-paper-shadow.service` ✅ active 220 min, 0 restarts
- `live_binance_liquidations.py` ✅ confirmed absent from every active service
- `v2:liquidations:events` stream exists but `XLEN=0` after 53 min — either Binance force-order quiet period or bridge warmup; classified as `info`-severity in remediation Phase 7
- `v2:market:liquidation_levels:*` family has 0 keys — possible prefix mismatch or warmup; also classified as `info` and queued for inspection

## Dynamic symbol evidence (Phase 3)

- **27 discovered symbols** = 25-symbol baseline + `COINANK_ONLY_USDT` + `KUCOIN_ONLY_USDT`
- 25/25 baseline symbols present
- `binance_usdm_directly_tradable_symbols` is still BTC/ETH/SOL — but this is a *Binance tradability flag*, not a "currently active V2 symbol" set; the broader 27-symbol set feeds the resolver and the unified-features pipeline
- No service exports `V2_SYMBOL_PROFILE=smoke_test`; the 3-symbol pin is nowhere active

## Feature / TA / trainer impact (Phase 4)

Redis evidence (currently active writes):

| Family | Key count |
|--------|-----------|
| `v2:market:*` | 128 |
| `v2:features:*` | 64 |
| `v2:unified_features:*` | **170** (27 symbols × multiple timeframes) |
| `v2:paper:*` | 89 |
| `v2:liquidations:*` | 1 (events stream, XLEN=0) |
| `v2:altdata:*` | 1 |
| `v2:risk:*` | 1 |
| `v2:symbol_universe:*` | 1 |

Old-Redis writes (should be 0):

| Family | Key count |
|--------|-----------|
| `live_orders:*` | 0 ✅ |
| `exchange:order:*` | 0 ✅ |
| `orchestrator:*` | 0 ✅ |

Stale operator-runtime payloads (services run but heartbeat path not wired
correctly) — surfaced as Phase 7 remediation tasks:

- `v2/frontend/public/operator_runtime/v2_feature_pipeline_native/latest/v2_feature_pipeline_native_status.json` (10.8 days old)
- `v2/frontend/public/operator_runtime/v2_owned_trainer/latest/status.json` (10.8 days old)
- `v2/frontend/public/operator_runtime/v2_liquidation_ingestor/latest/v2_liquidation_ingestor_status.json` (~9.3 days old)

Trainer role label: `copied_parity_baseline_bridge` ✅ (not `v2_native_readiness`).
No torch import, no checkpoint loaded, no model adopted.

## Paper edge (Phase 5)

- `edge_claimed = false`
- `edge_claim_blocked_reason = "operator_thresholds_required_and_not_set"`
- All 3 profile verdicts: `INCONCLUSIVE_OBSERVED_EVIDENCE_MISSING`
- 16 validation rows (well below any defensible edge claim threshold)
- Trainer vs strategy baselines: no winner declared
- **Recommendation: `BLOCK_LIVE_PAPER_EDGE_NOT_PROVEN`** for both live and canary

What would unblock the edge gate (no live/canary changes either way):

1. Let burn-in accumulate >300 validation rows (paper/shadow only)
2. Operator sets edge thresholds explicitly
3. Re-run 24h war-room executor after burn-in window grows
4. Add per-symbol PnL attribution lane once validation set crosses min_sample_count

## Trading platform UI (Phase 6)

**31 frontend pages** present, including: trader, paper-trading,
executions, signals, symbols, markets, market, market-intelligence,
mission-control, monitor-center, audit-ledger, config-admin,
strategy-admin, trainer-admin, exchange-manager, codex-review-center,
mobile-iphone-readiness, operator-proof-dashboard, history, etc.

`v2_default_blocked_execution_adapter` confirmed as the default — no real
order path is reachable from the frontend without operator-gate approval.

Rendered screenshot evidence packet is deferred to a separate
visual-regression / operator screenshot lane (cannot be produced inside a
headless Claude turn).

## Auto-remediation (Phase 7)

7 remediation tasks surfaced (full detail in
`v2_copied_runtime_burn_in_remediation_status.json`). None require an
operator gate; all are paper-only and target stale operator-runtime
payloads, liquidation diagnostics, or re-running the existing war-room.

This turn **surfaces** the task definitions but does NOT materialize
`agent_supervisor/tasks/*.json` spec descriptors directly, to avoid
bypassing the no-manual-next-task policy. The
`ai-bot-v2-parallel-spark-automation.service` (running 220 min) and
`ai-bot-v2-claude-task-runner.timer` are the proper enqueue path for
operator-blessed task generation.

## Hard constraints honored

| Constraint | Status |
|-----------|--------|
| `live_gate=blocked_human_only` | ✅ held |
| `live_symbols=[]` | ✅ held |
| Did not enable live | ✅ |
| Did not enable canary | ✅ |
| Did not place/cancel/modify orders | ✅ |
| Did not call test-order endpoint | ✅ |
| Did not change leverage | ✅ |
| Did not change margin mode | ✅ |
| Did not write old Redis | ✅ |
| Did not restart legacy | ✅ |
| Did not trim Redis | ✅ |
| Used EST timestamps in artifacts | ✅ |
| Did not emit LIVE_READY or CANARY_READY | ✅ |
| Did not call checkpoint shape pass "model ready" | ✅ |
| Did not redispatch completed tasks | ✅ |

## Path from BLOCKED to READY

The BLOCKED verdict here has **two distinct prerequisites**:

**(A) Runtime side** — clearable by automation:

1. Land 3 stale-payload refresh remediations (Phase 7 tasks 1-3).
2. Land 2 liquidation diagnostic remediations (Phase 7 tasks 4-5).
3. Wait for `v2:liquidations:events` `XLEN > 0` or close the bridge-warmup
   ambiguity diagnostically.

**(B) Edge side** — requires real burn-in, not code:

4. Accumulate burn-in time so the 24h war-room dataset crosses
   `min_sample_count` on all 3 profiles (currently 16 validation rows;
   target 300+).
5. Operator sets edge thresholds explicitly.
6. Re-run 24h war-room executor; if any profile flips from
   `INCONCLUSIVE_OBSERVED_EVIDENCE_MISSING` to a positive-edge verdict,
   THIS lane's GO/NO-GO can flip to `_READY`.
7. Even then, the live/canary recommendation only becomes
   `CANARY_OPERATOR_DECISION_REQUIRED` — never `_READY` from this lane.
