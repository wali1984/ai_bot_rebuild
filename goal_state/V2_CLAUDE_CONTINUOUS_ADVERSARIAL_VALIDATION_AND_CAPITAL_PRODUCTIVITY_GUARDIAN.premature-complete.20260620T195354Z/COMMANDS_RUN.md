# Commands Run — Guardian Goal

## 2026-06-19T20:45:00Z — Initialization

```bash
# Check goal_state directory structure
ls /home/wali/Desktop/AI\ BOT\ REBUILD/goal_state/

# Check Codex P0 goal lock
cat .../V2_P0_DIRECTIONAL_EXIT_EXECUTION_RISK_AND_ADAPTIVE_CAPITAL_REMEDIATION/GOAL_LOCK.json

# Parse P0 validation ledger
python3 -c "import json; d=json.load(open('VALIDATION_LEDGER.json')); ..."

# Read P0 FINAL_BLOCKERS
python3 -c "import json; d=json.load(open('FINAL_BLOCKERS.json')); print(json.dumps(d,indent=2))"

# Check running processes
ps aux | grep -E "(python|node|redis|uvicorn|paper)" | grep -v grep

# Check Redis paper keys
redis-cli keys "v2:paper:*"
redis-cli get "v2:portfolio:state"

# Check git log
git log --oneline --since="2026-06-18"
```

## Results — Initialization

- P0 Codex goal state: PASSED_AUDIT_GATES_TRAILING_STOP_PRICE_COST_FLOOR_PATCH_RUNTIME_VALIDATION_268_50_LIVE_GATE_BLOCKED_HUMAN_ONLY
- P0 VALIDATION_LEDGER says PASSED but FINAL_BLOCKERS has NO_GO with F02=INSUFFICIENT_EVIDENCE (CONTRADICTION)
- v2:portfolio:state shows realized_pnl_usd=33.64, unrealized=1700.93 (explained: 86 open positions)
- All 86 current open positions are SHORT
- 153 processes running in V2 runtime
- 447 v2:paper:* Redis keys exist

## 2026-06-20T02:49Z–03:15Z — Phase 1 + Phase 2 Analysis

```bash
# Full closed trades analysis
redis-cli get v2:paper:closed_trades | python3 -c "import json,sys; t=json.loads(sys.stdin.read()); print(len(t))"
# → 1372 trades, SHORT=1164 (84.8%), LONG=208 (15.2%)

# Field inspection on last 5 trades
redis-cli get v2:paper:closed_trades | python3 << 'PYEOF' ...
# → revealed: bid_ask_spread_bps NOT top-level but in microstructure_context (100%)
# → realized_slippage_bps = constant 2.0
# → effective_leverage = constant 1.0
# → stop_distance_bps = NULL in 96% of trades
# → min_profit_before_trailing = constant 30.0 bps

# ATR stop vs spread analysis
# → Only 4/50 ATR-stopped trades had spread > ATR (ADAUSDT, FILUSDT)
# → ATR stop dominance (72.5%) is NOT primarily from tight spread/stop

# V1 policy regime analysis
# → mean_reversion_mode dominates at 68.8% (275/397)
# → mean_reversion_mode: WR=23%, Net=-$36.86 — WORST performer
# → trend_mode: WR=29%, Net=-$8.94 — also losing
# → reduce_size_mode: WR=33%, Net=+$21.25 — ONLY profitable mode

# TREND regime analysis
# → TREND regime (80 trades): WR=32.5%, Net=+$4.04, PF=1.15
# → Within TREND: reduce_size_mode WR=56%, Net=+$11.60 (9 trades)
# → Within TREND: trend_mode WR=30%, Net=-$7.56 (71 trades) — ALSO LOSING

# Outcome memory check
redis-cli keys "v2:paper:outcome_memory:*" | wc -l
# → 255 keys
redis-cli get "v2:paper:outcome_memory:__ALL__:1h" | python3 -c "..."
# → BLOCKED since 2026-06-19T02:09:01Z

# Outcome memory vs actual trades (CRITICAL FINDING)
# → 1h BLOCKED but 220 V1 trades placed after block (latest: 2026-06-20T03:02:38Z)
# → 15m BLOCKED but 105 V1 trades placed after block
# → 4h BLOCKED but 5 V1 trades placed after block
# → 83% of V1 trades (331/397) on blocked timeframes

# Counterfactual
# → If blocks enforced: V1 Net=-$2.17 vs actual -$24.63 (91% loss reduction)
```

## Key Findings Summary

1. CRITICAL: CG-F001 — LONG WR=26.6%, net losing (-$20.56)
2. CRITICAL: CG-F002 — ATR stop 72.5% of V1 exits
3. CRITICAL: CG-F009 — mean_reversion_mode LONG WR=21%, PF=0.25
4. CRITICAL: CG-F013 — mean_reversion_mode replaced trend_mode as monopoly (68.8%)
5. CRITICAL: CG-F014 — outcome memory blocks NOT wired to admission gate (83% blocked TF trades)
6. HIGH: CG-F003 — 13.95x gross leverage untracked
7. HIGH: CG-F004 — VALIDATION_LEDGER contradicts FINAL_BLOCKERS
8. HIGH: CG-F010 — realized slippage constant 2.0 bps
9. HIGH: CG-F011 — leverage constant 1.0 (Phase 8 not implemented)
10. MEDIUM: CG-F005 through CG-F008, CG-F012
