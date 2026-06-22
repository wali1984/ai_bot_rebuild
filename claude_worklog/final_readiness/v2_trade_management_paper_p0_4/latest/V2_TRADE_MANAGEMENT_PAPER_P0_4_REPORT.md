# V2 Trade Management Paper P0.4 - Stop/TP/Stealth/Hedge/Anti-Churn

Phase P0.4; Sprint 12h native core migration.

Generated: 2026-05-16T04:45:00Z
Git HEAD: 31a7fd70319f0d586c454b5ea2ea530ba9cb1541

## Components ported (paper-only)

- compute_stealth_stop_schedule (no exchange broadcast; time-decay
  buffer in bps).
- compute_dynamic_stop_plan (ATR-based, conservative fallback when
  atr_pct missing).
- compute_dynamic_take_profit_ladder (laddered partial exits).
- churn_veto (minimum hold seconds).
- evaluate_fee_ratio_gate (block when fee_bps/abs(EM_after_cost)
  exceeds max_ratio; missing EM_after_cost => block).
- evaluate_hedge_dca (FAIL_CLOSED_STUB by default).
- TradeManagementPaperService.plan_for_position and
  TradeManagementPaperService.evaluate_pre_trade.

## Components NOT ported (explicit blockers)

- full_legacy_stealth_stops_state_machine
- full_dynamic_tp_engine_regime_adaptive_ladders
- full_dynamic_adaptive_stops_regime_adaptive_distance
- adaptive_hedge_builder
- dynamic_adaptive_hedge
- hedge_pair_coordinator
- leg_manager
- exit_coordinator
- stealth_dynamic_integration
- live_order_routing

These are explicitly enumerated in components_missing of the public
payload.

## Tests

- v2/backend/tests/integration/cli/test_v2_trade_management_paper_worker.py:
  19 passed.

## Public payload

v2/frontend/public/operator_runtime/v2_trade_management_paper/latest/
v2_trade_management_paper_status.json contains:

- worker_id: v2_trade_management_paper
- live_gate: blocked_human_only
- live_symbols: []
- approves_live: false
- approves_canary: false
- approves_legacy_shutdown: false
- approves_redis_trim: false
- scope: PAPER_ONLY
- migration_classification: PARTIALLY_MIGRATED
- legacy_sha256_citations: 5 trading sources

## Legacy citations

- trading/stealth_stops.py
  sha256=a76de1902e7c2a754f2e90a39fa9aac23d991ec059d5c54d6e0772b79b8a47cf
- trading/dynamic_tp_engine.py
  sha256=54bf102e9d5cfedb00f22f953c4894c4592a1b627a16bad51c034a7069c1e908
- trading/dynamic_adaptive_stops.py
  sha256=523ef574f6f6729c831047e73ce53bfad3d980cb562a386bf8b648b22d9d061f
- trading/churn_prevention.py
  sha256=f258b87233fc68d7d73e05f13fece322774bdf2a6e95ad8c081b83cbc3771d1f
- trading/stealth_dynamic_integration.py
  sha256=0e1f5ab2ccd0dc20af7cbca8c258f0d69c05f64507191ce6960e6c06cf003d52
- trading/exit_coordinator.py
  sha256=fb0591c2a4ef29a40695556c536ef7998657135222dab86938a3ae4219941bc4
- rl/hedge_manager_v3.py
  sha256=8cc0c991bcace41853ec5304a27767d30ee332f669474c27a3d606c38f746edf
- rl/churn_veto.py
  sha256=2c81e961b69c557dd684293cdcc6540fb7980ad42a404c5c8d08c24f9b241c74
- rl/minimum_hold_time.py
  sha256=6ab470cf50b756134ccb420f42831481d4edc5951f14f8fa2ae7bebcf68fc1ae

## Permanent migration contract checklist

- Legacy source paths: yes.
- SHA256: yes.
- Dependency closure: yes (pure stdlib).
- Config/env mapping: base_buffer_bps, atr_multiplier,
  minimum_hold_seconds, fee_ratio_max are runtime knobs with
  documented defaults.
- Behavior mapping: yes.
- V2 implementation: yes.
- Tests: 19 passing.
- Public payload: yes.
- Codex review: pending.
- No old Redis writes: yes.
- No exchange mutation: yes.
- live_gate == "blocked_human_only": yes.
- live_symbols == []: yes.

## Decision

P0.4 is READY at the paper-only stop/TP/stealth/hedge/anti-churn
engine level. Hedge/DCA remain FAIL_CLOSED_STUB until the paper
hedge engine is fully implemented. Live order routing is out of
scope for this sprint.
