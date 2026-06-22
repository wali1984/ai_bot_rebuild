# Remediation Packet — CG-F002: ATR Volatility Stop Dominates V1 Exits (72.5%)

**FINDING_ID:** CG-F002
**SEVERITY:** CRITICAL
**OWNER:** Codex (V2_P0 goal)
**STATUS:** OPEN — requires Codex investigation + runtime evidence

---

## FILES (likely candidates — Codex must confirm)

- v2/backend/app/paper_trading/ (exit engine — TIER_1_ATR_VOLATILITY_STOP implementation)
- v2/backend/app/paper_trading/ (entry admission gate — expected_move_after_cost_bps gate)
- v2/backend/app/ (ATR calculation, ATR multiplier config)

---

## REPRODUCTION

```bash
# Measure ATR stop rate in V1 policy
redis-cli get v2:paper:closed_trades | python3 -c "
import sys, json
trades = json.loads(sys.stdin.read())
v1 = [t for t in trades if t.get('paper_exit_policy_version') == 'PAPER_EXIT_AFTER_COST_TRAILING_FLOOR_V1']
atr = [t for t in v1 if t.get('close_reason') == 'TIER_1_ATR_VOLATILITY_STOP']
pnls = [t.get('realized_pnl_usd', 0) or 0 for t in atr]
print(f'ATR stops: {len(atr)}/{len(v1)} ({len(atr)/len(v1)*100:.1f}%), WR=0%, Net=\${sum(pnls):.2f}')
"
```

---

## EXPECTED BEHAVIOR

The TIER_1_ATR_VOLATILITY_STOP is the **hard stop** (emergency exit). It should:
- Fire on ≤ 20% of exits (rare safety net, not primary exit mechanism)
- When it fires, it prevents larger losses but accepts the loss on this trade
- The trailing stop / take-profit / model reversal should be the primary exits

At 72.5% ATR stop rate, the hard stop is the de facto exit policy — meaning:
- 72.5% of trades immediately go adverse beyond the ATR stop distance
- The paper system is systematically entering at the wrong time OR the ATR stop is too tight

---

## ACTUAL BEHAVIOR (observed 2026-06-20T02:49Z)

```
V1 Policy exits:
  TIER_1_ATR_VOLATILITY_STOP: 288 / 397 = 72.5%, WR=0%, Net=-$114.74
  TIER_2_TRAILING_STOP:        74 / 397 = 18.6%, WR=98.6%, Net=+$55.28
  TIER_2_TAKE_PROFIT:          14 / 397 =  3.5%, WR=100%, Net=+$29.35
  Other:                       21 / 397 =  5.3%

MFE avg on ATR-stopped trades: 22.0 bps
MAE avg on ATR-stopped trades: 49.6 bps
```

The avg MFE on ATR-stopped trades is 22 bps, MAE is 49.6 bps. This means:
- Trades DID move favorably (avg 22 bps) but then reversed
- The adverse move (49.6 bps) was more than double the favorable move
- This is NOT a purely tight-stop problem — the trade direction itself reversed

---

## ROOT CAUSE (two sub-hypotheses)

**Sub-hypothesis 2A: ATR stop too tight relative to noise**
- ATR multiplier produces a stop distance shorter than typical market noise
- Small price fluctuations immediately trigger the hard stop before the trade can develop
- Evidence: 22 bps MFE suggests trade moved right initially but noise is > 22 bps

**Sub-hypothesis 2B: Entry quality is fundamentally poor**
- Entries are taken when edge_after_cost_bps is marginal or negative
- Market immediately reverses because the entry was against dominant flow
- ATR stop correctly prevents larger losses
- The problem is upstream in signal/entry admission, not in the stop itself

**Diagnostic commands:**
```python
# For 20 random ATR-stopped trades, check entry signal quality:
for trade in atr_stopped_sample:
    print(trade.get('expected_move_after_cost_bps'))   # Was this positive?
    print(trade.get('strategy_router_confidence'))     # Was confidence high?
    print(trade.get('strategy_regime_labels'))         # What was the regime?
    print(trade.get('mfe_bps'))                        # How far right did it go?
    print(trade.get('mae_bps'))                        # How far wrong did it go?
```

---

## MINIMAL FIX

**DO NOT widen the ATR stop globally without diagnosis.** A global stop widening would:
- Increase losses on genuinely bad entries
- Mask the entry quality problem

**DO THIS INSTEAD:**

1. **Sample 20 ATR-stopped trades** and inspect expected_move_after_cost_bps, confidence, regime
2. **If expected_move_after_cost_bps < some threshold on stopped trades:**
   - Tighten the admission gate (raise minimum expected_move_after_cost_bps)
   - Test: do new admissions still get ATR-stopped at 72% rate?
3. **If expected_move_after_cost_bps is positive but trade immediately reverses:**
   - The expected move model is wrong — recalibrate or raise the required margin
   - Add a volatility-adjusted minimum: expected_move must exceed ATR × N (not just costs)
4. **If ATR distance is < 20 bps on stopped trades:**
   - The hard stop is too tight for these symbols/timeframes
   - Symbol-specific ATR multiplier calibration needed

---

## TESTS REQUIRED

- [ ] Sample 20 ATR-stopped V1 trades: verify expected_move_after_cost_bps distribution
- [ ] After fix: ATR stop rate drops to < 30% on new V1 trades (200 trade sample)
- [ ] After fix: ATR-stopped trade MFE/MAE ratio improves (MFE closer to stop distance)
- [ ] Verify take-profit and trailing stop become the dominant exits (>50% of closes)

---

## RUNTIME PROOF REQUIRED BEFORE CLOSE

- After fix: 200 consecutive V1 policy trades where ATR stop rate < 30%
- After fix: overall V1 policy net PnL > 0
- After fix: TIER_2_TAKE_PROFIT + TIER_2_TRAILING_STOP > 50% of exits

---

## SAFETY NOTES

- Tightening entry admission gate is safe — it reduces trade frequency
- Widening ATR stop increases per-trade max loss — acceptable only after entry quality proven
- No leverage or exchange mutations required

---

*Generated by Claude Guardian 2026-06-20T02:49:11Z*
