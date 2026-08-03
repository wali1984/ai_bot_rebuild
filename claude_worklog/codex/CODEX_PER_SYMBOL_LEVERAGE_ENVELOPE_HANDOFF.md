# CODEX HANDOFF — Lift the binding leverage envelope to per-symbol adaptive tiers

Date: 2026-07-18 | From: Claude | Operator-authorized | Live gate: BLOCKED (paper only)
Priority: MEDIUM (unlocks operator directive; safe because gated on realized edge)

## Why this is handed to you, not done by Claude
The BINDING per-cycle leverage cap lives in files you have UNCOMMITTED (CG-F049/G10 work):
  - v2/backend/app/services/adaptive_capital_allocator/dynamic_envelope.py
  - v2/backend/app/services/adaptive_capital_allocator/contracts.py
Claude did NOT edit them to avoid clobbering your in-flight money-path changes. Claude already
shipped the RECOMMENDATION side (clean file, 32 tests): see
services/paper_trade_management/leverage_recommendation.py::symbol_leverage_ceiling().

## Operator directive (authorized 2026-07-18)
Per-symbol ADAPTIVE leverage, no longer stuck at 1-3x:
  - BTC/ETH        -> up to 75x
  - SOL/LTC/XRP    -> up to 50x
  - all other alts -> up to 20x
Adaptive to market conditions; risk-first but not perpetually conservative; margin adaptive.

## Current binding constraints (why effective leverage is still <=10x)
  dynamic_envelope.py:18   _PAPER_HARD_MAX_LEVERAGE = 10.0
  dynamic_envelope.py:115  _clamp(base_leverage, 1.0, _PAPER_HARD_MAX_LEVERAGE)
  dynamic_envelope.py:318  leverage = _clamp(base.max_effective_leverage * exp(log_factor), 1.0, _PAPER_HARD_MAX_LEVERAGE)
  contracts.py:35          RiskEnvelope.max_effective_leverage: float = 3.0   (base)

## Requested change (keep the adaptive/earned semantics — only lift the CEILING)
1. Make the hard ceiling PER-SYMBOL, sourced from the canonical function:
       from app.services.paper_trade_management.leverage_recommendation import symbol_leverage_ceiling
   Replace the `_PAPER_HARD_MAX_LEVERAGE` upper bound in the two clamps with
   `symbol_leverage_ceiling(symbol)` (BTC/ETH=75, SOL/LTC/XRP=50, alt=20; env-tunable).
   The envelope builder must receive the symbol (it is per-position/per-signal). If a call site is
   portfolio-level and has no symbol, keep the global fallback ceiling (env PAPER_ABSOLUTE_MAX_LEVERAGE=75).
2. KEEP the realized-evidence exp() scaling (losing_evidence_pressure + favorable_growth - context_pressure
   - drawdown_pressure). High tiers must remain EARNED through realized win-rate/PF/edge — never granted.
   Because current model edge is NEGATIVE, favorable_growth ~= 0, so effective leverage STAYS LOW today;
   this only raises the reachable ceiling once real edge appears. (Verified on the recommendation side:
   non-positive after-cost edge -> 1x.)
3. Raise the base (contracts.py:35) only if you want the resting leverage above 3x; recommend LEAVING base
   at 3.0 and letting the exp() factor + per-symbol ceiling do the adapting (safer: rests low, earns up).
4. G10 INVARIANT: whatever effective_leverage you emit, write allocated_margin = notional / effective_leverage
   so gross_notional ~= allocated_margin * effective_leverage holds (this is the capital-invariant gate).
   Raising leverage without this fix widens the G10 violations.

## Liquidation safety (already enforced on the recommendation; mirror if you clamp independently)
leverage_recommendation.py keeps liq distance >= 5x ATR (env PAPER_LEVERAGE_LIQ_SAFETY_ATR_MULT) so a
normal candle cannot liquidate. If the envelope selects leverage independently, apply the same
volatility-scaled liquidation-safety clamp.

## Acceptance
- Effective leverage for a strong, calibrated, low-vol BTC signal can exceed 10x (up toward 75x), while a
  weak/negative-edge or high-vol signal still resolves to ~1x.
- G10 capital-invariant holds on 100% of new post-policy trades (allocated_margin = notional/leverage).
- Existing allocator/envelope tests updated; add a per-symbol-ceiling test.

## Canonical source Claude already shipped (import, don't duplicate)
  symbol_leverage_ceiling(symbol) -> int   # 75/50/20, env PAPER_MAX_LEVERAGE_MAJOR_TIER1/TIER2/ALT
See claude_worklog/MASTER_PATH_TO_1000X_AND_SESSION_FINDINGS.md Part 5 for full reasoning.
