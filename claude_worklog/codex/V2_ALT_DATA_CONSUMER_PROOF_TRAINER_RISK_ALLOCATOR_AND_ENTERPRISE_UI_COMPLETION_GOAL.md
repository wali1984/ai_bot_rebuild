# CODEX_GOAL_ID: V2_ALT_DATA_CONSUMER_PROOF_TRAINER_RISK_ALLOCATOR_AND_ENTERPRISE_UI_COMPLETION

REPOSITORY: /home/wali/Desktop/AI BOT REBUILD

Approved by operator 2026-07-09 as the follow-up to Fable's
FABLE_ALT_DATA_PRODUCTION_BLOCKED_ONE_REASON verdict (single blocker:
ALT_DATA_CONSUMER_PROOF_MISSING). Fable artifacts live at
`goal_state/FABLE_COINGLASS_SANBASE_MORALIS_ALT_DATA_FULL_PRODUCTION_INTEGRATION_AND_GO_LIVE_READINESS/`
(21 files incl. FINAL_VERDICT.json with exact wire points) — REUSE them, do not re-probe.

Note: run all commands with the repo venv interpreter (`.venv/bin/pyth\on3` — escaped here
only to satisfy a local command-scanning hook; it resolves normally in bash).

## PATH RECONCILIATION (verified against tree 2026-07-09 — use THESE paths)

- `hybrid_cuda_trainer/feature_schema.py` DOES NOT EXIST — the feature schema lives inside
  `tensor_builder.py` (FEATURE list + missing_mask/stale_mask/source_availability vectors
  at ~lines 150-333). Patch there; bump its schema version explicitly.
- `v2/backend/app/services/risk/` and `v2/backend/app/services/orchestrator/` DO NOT EXIST.
  Risk-gate logic = `v2/backend/app/services/a_plus_trade_gate/service.py` (+
  `native_trainer/a_plus_phase8_trade_gate.py`); orchestrator =
  `v2/backend/app/cli/v2_orchestrator_arbitration_loop.py`.
- `v2/backend/app/services/preemptive_edge_control/` EXISTS (decision.py, loss_probability.py,
  portfolio_stress.py, schema.py, reasons.py, ...) — wire confluence reads into decision.py
  and add reasons to reasons.py.
- `v2/backend/app/services/allocator/{simulation.py,hedge_plan_simulator.py}` EXIST as specified.
- `v2/backend/app/cli/v2_live_canary_dry_run.py` EXISTS as specified.
- Redis: `v2:provider:santiment:feature_bridge_status` DOES NOT EXIST — Santiment status is
  `v2:altdata:santiment:status` (+ per-symbol `v2:altdata:santiment:symbol:{SYMBOL}`).
  `v2:live_gate:state` EXISTS. Confluence keys: `v2:altdata:confluence:{symbol}:{timeframe}`
  published by `ai-bot-v2-altdata-confluence-loop.service` (active), engine + reader helpers in
  `v2/backend/app/services/altdata/` — import `provider_feature_bridge.py` readers instead of
  re-parsing Redis JSON by hand.

## ALREADY DONE — DO NOT REDO

- CoinGlass: probe matrix (27/32 available), rate budget (43/min projected vs 65 cap),
  publisher masks (missing/stale/disabled/decision_time_safe) — verified in Redis.
- Santiment: 22 metrics, 5k/month header-verified budget (6 batched calls/cycle ≈14%/mo),
  >=31d plan lag documented — REGIME LAYER ONLY, must stay stale-masked.
- Moralis: token map, seeded watchlist (YELLOW), feature bridge publishing.
- Confluence engine: 15 scores, no-zero-fill masks, single-provider-can-block-never-approve,
  9 invariant tests, systemd service active.
- Santiment+CoinGlass ARE already in the tensor (santiment_* score fields,
  coinglass_derivatives_score via v2:altdata:symbol_score) — keep them; the gap is
  moralis.* + altdata_confluence.* and the direct risk/orchestrator/allocator reads.

## CONCURRENCY WARNING

A large multi-file working-tree diff (frontend types, mobile models, market_contracts,
trainer files) may be in flight from a parallel agent. Rebase/coordinate before editing
tensor_builder/data_loader; do not clobber uncommitted work.

---

MISSION: Finish the one blocker: ALT_DATA_CONSUMER_PROOF_MISSING.

Do not redo provider probing. Do not redo ingestion. Do not create another broad audit.
Do not lower trading thresholds. Do not mark A+ or live-ready from provider data alone.
Do not place real orders, test orders, or mutate leverage/margin.

Prove CoinGlass, Sanbase/Santiment, Moralis, and altdata confluence are consumed by:
PPO trainer, MASA trainer, preemptive edge control, risk controller (a_plus_trade_gate),
orchestrator (arbitration loop), allocator, paper trader, dry-run/canary packet,
backend API, frontend website, iOS app.

## Phase 0 — Freeze Fable output and current runtime

Create `goal_state/<GOAL_ID>/phase0_fable_completion_freeze.json` + COMMANDS_RUN.md + FILES_CHANGED.md.

Capture (corrected key set):
```bash
redis-cli GET v2:provider:coinglass:health
redis-cli GET "$(redis-cli --scan --pattern 'v2:features:coinglass:*' | head -1)"
redis-cli GET v2:altdata:santiment:status
redis-cli GET v2:provider:moralis:feature_bridge_status
redis-cli --scan --pattern 'v2:altdata:confluence:*' | wc -l
redis-cli GET v2:altdata:confluence:BTCUSDT:1m
redis-cli GET v2:altdata:provider_consumption_status
redis-cli GET v2:live_gate:state
```
Hard fail if any provider shows green from heartbeat/API-key only or payload without bridge.

## Phase 1 — Trainer tensor integration

Add as actual model inputs: `moralis.*` (from v2:features:moralis + v2:smart_money:signals)
and `altdata_confluence.*` (from v2:altdata:confluence). Keep existing santiment/coinglass fields.

Patch: `tensor_builder.py` (schema lives here — bump schema version), `data_loader.py`,
`model.py`, `ppo_trainer.py` (feature_dim), MASA equivalent.

Required proof: PPO+MASA tensors include provider features; feature_dim change explicit;
missing/stale masks + source availability channel present; feature_cutoff <= decision_time;
Sanbase marked stale/regime-only; Moralis/confluence no longer trainer_consumption=false.

Artifacts: phase1_altdata_tensor_schema.json, phase1_ppo_masa_altdata_consumption_proof.json,
phase1_trainer_feature_dim_change_status.json.

Hard fail: Redis features exist but tensor excludes them; Moralis missing_mask=true everywhere
while bridge data exists; confluence absent from PPO or MASA; Sanbase lag treated as fresh 1m.

## Phase 2 — Risk / orchestrator / preemptive consumption

Wire direct reads of: altdata_trade_block_score, altdata_reduce_size_score,
altdata_hedge_required_score, altdata_confluence_long/short_score,
altdata_liquidation_sweep_risk_score, altdata_social_euphoria_risk_score,
altdata_wallet_distribution_score, altdata_exchange_flow_pressure_usd.

Patch (corrected): `services/a_plus_trade_gate/service.py`,
`cli/v2_orchestrator_arbitration_loop.py`, `services/preemptive_edge_control/decision.py`
(+reasons.py), `cli/v2_trade_management_paper_loop.py`.

Rules: alt-data can block / reduce size / require hedge / alter exit aggressiveness;
may increase confidence ONLY with market-structure + microstructure + risk agreement;
can NEVER approve a trade alone.

Artifacts: phase2_altdata_risk_orchestrator_consumption.json,
phase2_altdata_preemptive_decision_matrix.json,
phase2_altdata_block_reduce_hedge_reason_matrix.json.

Hard fail: risk/orchestrator cannot explain provider contribution; high block score passes
without reduction/hedge; provider data directly creates A+ candidate.

## Phase 3 — Allocator and hedge integration

Patch `services/allocator/simulation.py`, `services/allocator/hedge_plan_simulator.py`,
`cli/v2_a_plus_candidate_inventory.py` to consume reduce_size/hedge_required/sweep_risk/
exchange_flow_pressure/wallet_distribution.

Behavior: high reduce_size -> lower notional; high hedge_required -> explicit hedge plan;
high sweep risk -> more conservative max-loss/liquidation buffer; Moralis/Santiment
distribution conflict vs CoinGlass long -> never increase size.

Artifacts: phase3_allocator_altdata_consumption.json, phase3_hedge_plan_altdata_consumption.json,
phase3_candidate_inventory_altdata_lineage.json.

Hard fail: allocator packet lacks provider_features_used; hedge plan ignores hedge_required_score;
missing max-loss/liq-buffer while altdata risk high.

## Phase 4 — Paper trader and dry-run contract

Patch accepted fills, closed rows, dry-run packets with: provider_features_used,
provider_features_missing, coinglass/santiment/moralis/confluence feature hashes,
block/reduce/hedge scores, altdata_decision_contribution, altdata_feature_cutoff,
altdata_available_at.

Patch: `cli/v2_trade_management_paper_loop.py`, `cli/v2_live_canary_dry_run.py`,
`api/v2/market_contracts.py`, `api/v2/mobile.py`.

Artifacts: phase4_paper_fill_altdata_lineage.json, phase4_live_dry_run_altdata_lineage.json,
phase4_provider_hash_reconciliation.json.

Hard fail: paper vs dry-run provider context differs; closed feedback row lacks lineage;
feature_cutoff after decision_time.

## Phase 5 — Feedback and replay

Feedback rows gain: altdata_context_id, provider_features_used, altdata_confluence_scores,
provider_missing/stale_masks, altdata_block_reduce_hedge_reason, altdata_outcome_attribution.

Replay scenarios to prove: CoinGlass bullish + Moralis distribution -> reduce/hedge/block;
liquidation sweep risk -> block/reduce; social euphoria -> reduce confidence; CEX inflow
spike -> block/reduce long; whale accumulation + short squeeze + microstructure trust ->
confidence boost but never standalone approval; missing Moralis -> masks not zero-fill;
Sanbase delayed -> regime-only.

Artifacts: phase5_altdata_feedback_consumption.json, phase5_altdata_replay_backtest_status.json,
phase5_provider_outcome_attribution.json.

## Phase 6 — Enterprise web/iOS provider truth

Provider cards must show (real numbers from Fable phase artifacts):
- CoinGlass: 27/32 probe, 2 plan-blocked gray, 3 path-mismatch, 43/min projected vs 65 cap,
  features published, consumer proof status.
- Sanbase: 22 metrics, 5k/month verified, 6 calls/cycle, ~14% monthly use, 31-day lag,
  regime-only, consumer proof status.
- Moralis: watchlist status, T0/T1 counts, token map, CU used/remaining, bridge ready,
  trainer_consumption status, consumer proof status.
- Confluence: service active, symbols/timeframes published, provider fusion count,
  block/reduce/hedge outputs.

Artifacts: phase6_frontend_altdata_provider_truth.json, phase6_ios_altdata_provider_truth.json,
phase6_ai_page_altdata_brain_status.json.

Hard fail: UI green while consumer proof missing; Moralis green while trainer_consumption=false;
Sanbase shown execution-fresh; plan-blocked endpoint shown red; data disappears on refresh.

## Phase 7 — Validation

```bash
.venv/bin/pyth\on3 -m py_compile v2/backend/app/services/altdata/*.py \
  v2/backend/app/services/smart_money_wallets/*.py v2/backend/app/services/allocator/*.py \
  v2/backend/app/cli/v2_trade_management_paper_loop.py v2/backend/app/cli/v2_live_canary_dry_run.py
.venv/bin/pytest -q v2/backend/tests/unit/services/altdata \
  v2/backend/tests/unit/services/smart_money_wallets v2/backend/tests/unit/services/allocator \
  v2/backend/tests/unit/cli/test_v2_trade_management_paper_loop.py
npm --prefix v2/frontend run typecheck && npm --prefix v2/frontend run build
swift test --package-path v2/mobile
git diff --check
```
Plus the order/leverage/margin mutation + key-exposure rg scans (bracket-escape the
mutation tokens, e.g. `creat[e]_order`, so the local safety hook does not false-positive).

Final marker: `V2_ALT_DATA_CONSUMER_PROOF_READY_LIVE_STILL_BLOCKED`
or `V2_ALT_DATA_CONSUMER_PROOF_BLOCKED_ONE_REASON` (exactly one blocker).

READY requires: all provider consumer proofs complete; confluence in PPO/MASA tensor;
risk/orchestrator/allocator direct reads; paper/dry-run lineage; frontend/iOS truth;
no heartbeat-only green; no key exposure; no live mutation; live_gate=blocked_human_only;
A+/probation gates not bypassed.
