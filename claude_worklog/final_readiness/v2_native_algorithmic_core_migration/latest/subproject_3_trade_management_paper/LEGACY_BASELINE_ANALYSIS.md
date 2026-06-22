# Subproject 3 — Trade Management Paper Engine — Legacy Baseline Analysis

Generated: 2026-05-15
Live gate: `blocked_human_only`. Live symbols: `[]`.
Contract: `claude_worklog/final_readiness/permanent_migration_runtime/latest/MIGRATION_COMPLETION_CONTRACT.md`.

## Legacy sources consulted (read-only)

| Legacy path | SHA256 | Size (bytes) | V2 preserved path |
|-------------|--------|---------------|-------------------|
| `trading/stealth_stops.py` | `a76de1902e7c2a754f2e90a39fa9aac23d991ec059d5c54d6e0772b79b8a47cf` | 389,228 | `v2/legacy_preserved/full_runtime_closure/trading/stealth_stops.py` |
| `trading/dynamic_tp_engine.py` | `54bf102e9d5cfedb00f22f953c4894c4592a1b627a16bad51c034a7069c1e908` | 72,213 | `v2/legacy_preserved/full_runtime_closure/trading/dynamic_tp_engine.py` |
| `trading/dynamic_adaptive_stops.py` | `523ef574f6f6729c831047e73ce53bfad3d980cb562a386bf8b648b22d9d061f` | 47,578 | `v2/legacy_preserved/full_runtime_closure/trading/dynamic_adaptive_stops.py` |
| `trading/churn_prevention.py` | `f258b87233fc68d7d73e05f13fece322774bdf2a6e95ad8c081b83cbc3771d1f` | 22,085 | `v2/legacy_preserved/full_runtime_closure/trading/churn_prevention.py` |
| `trading/fee_ratio_gate.py` | `c1829afcbdb6848fb8dffd76e14b78a140832c663bb9c2f16e75029b0e7f8e7f` | 14,577 | `v2/legacy_preserved/full_runtime_closure/trading/fee_ratio_gate.py` |

## Behaviors PORTED (native V2, paper/shadow only)

1. **Stealth stop schedule** — computes a hidden stop price with a buffer
   that decays over time. Paper-only; never broadcast to any exchange.
2. **Dynamic ATR-based stop plan** — stop at `current_price * (1 - sign *
   atr_multiplier * atr_pct)`, with a safe default when ATR is missing.
3. **Dynamic take-profit ladder** — laddered partial exits at progressive bps
   targets with fraction validation.
4. **Churn veto** — blocks reopening before `minimum_hold_seconds` passes.
5. **Fee ratio gate** — blocks when `fee_bps / |expected_move_after_cost_bps|
   > max_ratio`, and blocks when expected move is missing.
6. **Hedge / DCA evaluator** — fail-closed stub. Denies every request with
   reason `HEDGE_DCA_NOT_PORTED_TO_V2_FAIL_CLOSED_STUB`. Classification
   `FAIL_CLOSED_STUB` under the migration completion contract.
7. **Service facade**: `TradeManagementPaperService.plan_for_position` and
   `evaluate_pre_trade` combine the gates.

## Behaviors PARTIALLY_PORTED

- Stealth stops: legacy state machine is far more elaborate (multi-leg trail
  adjustment, slippage adjustment, partial-fill replanning). V2 captures the
  schedule shape only.
- Dynamic TP: legacy ladders are regime-adaptive and include scale-out
  rebalancing. V2 captures static rungs only.
- Dynamic adaptive stops: legacy distance varies with regime and microstructure.
  V2 captures ATR-based distance only.

## Behaviors MISSING_IN_V2

- `adaptive_hedge_builder`, `dynamic_adaptive_hedge`, `hedge_pair_coordinator`.
- `leg_manager`, `exit_coordinator`, `stealth_dynamic_integration`.
- Live order routing (intentional fail-closed).

## Config / env mapping

| V2 parameter | Default | Notes |
|--------------|---------|-------|
| `base_buffer_bps` | 25.0 | stealth stop base buffer |
| `atr_multiplier` | 2.0 | dynamic stop |
| `minimum_hold_seconds` | 300 | churn veto |
| `fee_ratio_max` | 0.5 | fee ratio gate |

## Intentional V2 changes

- V2 never writes to legacy Redis.
- Hedge/DCA is intentionally FAIL_CLOSED in V2 until parity is built.
- V2 always emits an explicit stop price (no None) so paper soak is realistic.

## Deprecated legacy behavior

- Legacy adaptive hedge auto-construction is intentionally NOT imported to
  V2; live hedge construction must remain blocked until Codex review.

## Migration completion contract classification

`PARTIALLY_MIGRATED`. Hedge/DCA is `FAIL_CLOSED_STUB`. Not
`MIGRATED_CODEX_PASS`. Live, canary, legacy shutdown, Redis trim all `false`.
