# AI BOT V2 — System Decision Logic, Gaps, and Path to 1000x

Date: 2026-07-18 | Author: Claude (read-only analysis + this-session fixes) | Live gate: BLOCKED
Companion docs: [PATH_TO_1000X_EDGE_AND_RIGHT_TAIL_ANALYSIS.md], [FULL_STACK_AUDIT_REMEDIATION.md],
[TRAINER_EDGE_ROOT_CAUSE_AND_FIX_ROADMAP.md], [MASTER_STATUS_PATH_TO_1000X.md].
Evidence base: live v2:paper:closed_trades (92 post-policy), v2:trainer:hybrid_cuda:status, source trace.

================================================================================
PART 1 — HOW THE SYSTEM DECIDES TODAY (current running mechanics)
================================================================================

## 1.1 Entry — where + which direction
Direction/conviction come from the MODEL SIGNAL (side + confidence_calibrated + expected_move).
Entry is MARKET-ON-SIGNAL (fills at current mark) only if it survives a sequential veto pipeline in
services/paper_trade_management/entry_gate.py — each rejection logged with a reason code:
  - min_confidence_calibrated floor
  - expected move must be FAVORABLE AFTER ALL COSTS for the requested side (:139)
  - side/mode blocks learned from outcome history (e.g. long:mean_reversion blocked at WR21%/PF0.25, CG-F009)
  - outcome-memory degradation (a losing symbol auto-blocks)
  - cascade / liquidation-regime gates (blocks shorts into a squeeze, longs into a cascade)
  - loss-probability pre-trade estimate
There is no discretionary price level — enters now if the post-cost edge case clears, else blocked.

## 1.2 Exit — strict priority ladder (services/paper_trade_management/exits.py::evaluate_exit :392)
Runs every ~60s after a min_hold_seconds lock. First matching tier closes:
  1  TIER_0 liquidation distance   (mark within emergency_liquidation_distance_bps of liq price)  [hard safety]
  2  TIER_0 drawdown emergency     (account drawdown >= limit)                                     [hard safety]
  3  TIER_1 microstructure reversal(orderbook/CVD reversal score high)                             [signal flip]
  4  TIER_1 model reversal         (model flips direction)                                         [signal flip]
  5  TIER_1 confidence decay       (confidence <= floor)                                           [signal died]
  6  TIER_1 structure invalidation (FVG / VWAP-CVD / liquidity-sweep break)                        [thesis broken]
  7  TIER_2 MFE breakeven protect  (a trade that "paid for itself" decays back near breakeven)     [protect winner]
  8  TIER_2 band-gap giveback      (former winner gapped past the breakeven band in one cycle)     [fast reversal]
  9  TIER_2 trailing stop          (price retraces past trailing level)                            [lock gains]
  10 TIER_1 ATR vol stop / TIER_0 catastrophic floor (150 bps)                                     [final loss cap]

- NEGATIVE positions run until: signal flip (3-6), the adaptive ATR stop, or the 150bps floor / TIER_0
  liquidation backstop. min_hold + ATR give room to breathe (not cut just for being red).
- POSITIVE positions run until the trailing stop or MFE-breakeven fires. <-- this is where winners are cut.
- Fast unpredictable move nets: TIER_0 liquidation + catastrophic floor (adverse gap); band-gap giveback
  (winner reversal). Everything is a POINT-IN-TIME check per 60s tick — blind between cycles.

## 1.3 Leverage + margin — fully adaptive, evidence-driven
Size (risk budget %) — adaptive_capital_allocator/sizing_model.py::adaptive_budget_pct (:72):
  budget% = max_loss_per_trade_pct
          x confidence x edge x market_state x volatility x liquidity
          x spread_slippage x drawdown x exposure x correlation x regime   (clamped to single-symbol cap)
  confidence = 0.6*calibrated + 0.25*PPO + 0.15*MASA.
Leverage — dynamic_envelope.py (:309):
  leverage = base_leverage * exp(losing_evidence_pressure + favorable_growth - context_pressure - drawdown_pressure)
             clamped [1.0, PAPER_HARD_MAX]
  => contracts on realized losses/drawdown/poor-liquidity-regime; expands only on REALIZED favorable edge.
Margin: allocated_margin = notional / effective_leverage; margin_mode SIMULATED; leverage_live_mutation=False.
  (This invariant is currently violated on 46/92 trades -> guardian G10; the write path doesn't keep it consistent.)

## 1.4 Hedging — safety-first, profit-swing supported but gated
Primary live hedge = SAFETY: ADAPTIVE_ADVERSE_EXCURSION_HEDGE — open an opposing hedge when a position
moves against you, to cap downside WITHOUT closing (still can catch a reversal), instead of stopping out.
hedging.py::evaluate_adaptive_hedge (:26) VALIDATES a hedge_intent, requiring: explicit hedge_intent=True,
a hedge_reason, a defined unhedge/exit condition, budget 0<b<=$25 cap, risk_approved, and blocks accidental
same-symbol nettings; hedge notional <= 35% of position (max_hedge_ratio). A runtime safety interlock guards
the deferred hedge path (v2_trade_management_paper_loop.py:27720). Cross-margin engine
(risk/cross_margin_liquidation.py::marginal_liquidation_impact) REJECTS any hedge that raises maintenance
margin more than it reduces risk. Profit-swing hedges are representable (hedge_type generic) but not the
currently-wired trigger.

================================================================================
PART 2 — WHERE WE ARE (honest current state)
================================================================================
Book (92 post-policy closed): 37% win rate, PF 0.658, mean -16.8 bps (simple) / -18.1 bps (notional-weighted),
  net -$14.41. avg win +93 bps, avg loss -81 bps -> R:R 1.15. best-5 winners avg +276 bps (KITE+370,CAP+348,ENS+244).
Model: PIT-safe validation edge -1.39 bps after cost (lower bound -2.26, 402 rows, chronological purged split);
  effective_trainer_mode=INFERENCE_ONLY, serving a prior checkpoint "after rejection"; PIT edge-promotion gate
  correctly HARD-REJECTING (no positive edge to promote).
Target: 1000x/90d = 7.98%/day uniform compounding = +35 bps/trade geometric @ 22 trades/day (current pace).

================================================================================
PART 3 — GAPS & ISSUES FOUND THIS SESSION
================================================================================

## 3.1 The TWO trading deficits (this is the whole -18 bps)
A) DIRECTIONAL EDGE (CG-F053, TRAINER lane): validation edge -1.39 bps. Root causes: confidence head trained
   on move MAGNITUDE (clamp(|move|/100)) not P(profit-after-cost); overconfidence T~5.4 (=> sizing is
   ANTI-correlated with outcome: notional-weighted -18.1 WORSE than simple -14.9); ~99.7% training-row rejection
   -> memorization -> negative OOS; cost-blind reward. Counter-proof: a 32-feature Ridge gets +30 bps on the
   same holdout — the edge IS in the data.
B) RIGHT-TAIL AMPUTATION (CG-F052, EXITS/SIZING lane) — the fast, under-recognized half:
   winners realize only ~55% of their max-favorable-excursion; a dense cluster exits at a near-FIXED ~42 bps
   regardless of MFE (LDO 42/138=30%, TIA 63/191=33%, MET 42/116=36%, SLX 154/343=45%). TIER_2 trailing (30) +
   MFE-breakeven (12) = 42/92 exits cut winners. Winner hold 73min < loser hold 81min (golden rule INVERTED).
   Estimate: MFE-capture 55->85% lifts avg win ~+93->~+140 bps, R:R 1.15->~1.7 => roughly break-even-to-positive
   WITHOUT any model change. Cost drag ~15 bps (validation -1.4 vs live -16.8) = fees+slippage+funding+adverse selection.

## 3.2 Guardian gates blocked (all on operator-auth or Codex lane, none on Claude)
  G10 capital-invariant: 46/92 notional!=margin*leverage (hidden-leverage split-brain). Historical repair is
     classifier-BLOCKED (mutating records "to pass a gate"); needs operator auth. Write-path fix in Codex's
     uncommitted sizing_model.py/lifecycle.py/paper_loop.py.
  G11 counterfactual sweep FAIL — downstream of G10's bad data.
  G12 rare-event stress: 8 warned / 0 failed (documented residual).
  G13 after-cost expectancy -18.1 bps  |  G14 PF 0.658  — both = the edge+right-tail deficits above.
  G03 CG-F049..F053 evidence chain — Codex-lane findings pending their commit.

## 3.3 Full-stack audit defects fixed this session (43 across 14 commits; details in FULL_STACK_AUDIT_REMEDIATION.md)
  - PnL truth: GROSS->NET across get_paper_status equity curve, accuracy/profit-factor, iOS positions.
  - Security: admin privilege-boundary (no granting role above own rank, step-up MFA for password reset),
    /audit/chain restricted to operator, backtest/run require_auth, login brute-force limiter, RBAC from JWT not X-Role.
  - DoS: ~10 blocking Redis KEYS -> bounded SCAN + pipelined TTL across API + 3 CLI publishers.
  - Safety: cross_margin_liquidation short-side maintenance sign bug (withheld protective close in up-squeeze).
  - Data honesty: stale-labeled-fresh across useRealtimeResource (shared) + 5 pages; fabricated baselines removed;
    24h-change 100x understatement; backtest UI wiring (query params, result mapping, status 'complete').
  - iOS: 24 findings — 1 backend fixed (admin actor id), 23 Swift handed off to Agent 2 (can't build-verify on Linux):
    HIGH = /api/auth/me nested-decode logs out every launch; force-unwrap URL crashes; WatchSyncCenter data race.

## 3.4 Operator-config gaps (NOT code — need operator action)
  - CRITICAL: ALPHAFORGE_ENV unset -> production auth hardening inert (admin MFA step-up bypass, cookie flags).
  - adaptive_gate_tuner reads v2:market:candle:latest:{sym} which NO service writes -> volatility/regime
    adaptation is DEAD (protective high-vol tightening never fires). Repoint to an existing candle key.
  - CoinAPI returns HTTP 403 on every symbol (expired key/quota) — fallback source, Binance WSS is primary+live;
    operator to renew the key (.env, not Claude-writable).
  - Legacy old-bot systemd units (aibot-feature-pipeline, ai-ta) run the forbidden ../AI BOT tree Restart=always -> mask.
  - Cross-margin cascade guard is INERT (reads positionAmt but paper positions carry net_quantity) -> portfolio
    liquidation-breach protection never fires. Fixing ACTIVATES a force-CLOSE (Codex lifecycle lane) -> operator-gated.

## 3.5 Infra fixed this session (reboot recovery)
  - orderbook_replay_rollover: walked only empty binance/, never kucoin/ (154GB) -> now walks all exchanges +
    excludes today; ran 153.5GB->99.9GB (disk 74%->63%). Unit path-quoting bug also fixed.
  - Cursor stuck-on-loading: 18GB un-checkpointed WAL from the hard reboot; clean shutdown checkpointed it away;
    DB verified healthy (quick_check ok, 18GB chat history intact), backed up, relaunched; Codex ext live, WAL 2.5MB.
  - Verified ALL real-time feeds live post-reboot (Binance WSS, microstructure, orderbook, TA-Lib, liquidation);
    started 2 dead enabled feed units (kucoin-rest, provider-data-plane-health); systemd back to running.

================================================================================
PART 4 — SUGGESTED PATH TO 1000x
================================================================================
Principle: 7-8%/day is a FLOOR for uniform compounding, not the ceiling or the shape. Real returns are lumpy —
flat/small most days, then +20-50% days when a few high-MFE runners align and get sized into. The ceiling =
edge x right-tail-capture x conviction-concentration x survivable-leverage. Three of those four are structural
levers WE CONTROL, not model magic. But every lever multiplies expectancy, so signed edge must reach >=0 first.

## STAGE 0 — Truth & survival (mostly DONE this session, rest operator/Codex)
  - PnL/capital/health telemetry now honest (audit fixes). KEEP the PIT edge-promotion gate strict.
  - Operator: authorize the G10 repair, set ALPHAFORGE_ENV=production (+secrets), repoint the gate-tuner candle key,
    renew CoinAPI, decide on cross-margin cascade-guard activation.

## STAGE 1 — Cross zero (the two independent fixes; do BOTH in parallel)
  1a EXITS/SIZING (fast, no model dependency — Codex exits.py/sizing_model.py):
     - MFE-proportional trailing (widen the trail as MFE grows) + partial scale-outs with a RUNNER tranche that
       only exits on true reversal or the catastrophic floor. Targets: MFE-capture >=80%, R:R >=1.7.
     - Asymmetric hold: cut LOSERS faster than winners (invert the current 73<81 min). This alone plausibly flips
       the book positive.
  1b TRAINER (owns ~50 of the 52 bps — Codex trainer lane, CG-F053):
     - Relabel the confidence head to P(profit-AFTER-COST). Bake round-trip cost into the PPO/MASA reward.
     - Temperature-scale to T~1 (calibration is what makes conviction sizing SAFE instead of harmful).
     - Break the 99.7% row starvation via H2L / historical-replay pretraining (persistent brain, not live scraps).
     - Success criterion: PIT-safe validation post-cost edge crosses from -1.4 to >+15 bps (break-even live).

## STAGE 2 — Earn the right to compound (only after live PF>1.0 on a real sample)
  - Turn on CALIBRATED fractional-Kelly sizing (size ~ calibrated P(profit)); ADD-TO-WINNERS on confirmation.
  - Activate the cross-margin cascade guard + a per-trade dollar-risk cap FIRST (survival gate before scaling).
  - Orchestrator must not authorize size/leverage scaling until a PROMOTED checkpoint with positive edge exists.

## STAGE 3 — Scale the tail (where 10x->100x->beyond comes from)
  - Conviction concentration: the few 70%+ setups get 5-10x the capital of the 55% ones (that's the big days).
  - Leverage on TIGHT-invalidation setups (20bps stop carries far more notional per $ risk than a 100bps stop)
    — high capital efficiency WITHOUT liquidation risk.
  - More concurrent uncorrelated shots across the 136-symbol universe (microstructure/orderbook/liq feeds are the
    edge-discovery surface; all live+healthy).
  - Intraday compounding: a good morning funds bigger, still-survivable afternoon size.

## HONEST VERDICT
1000x in 90 days (7.98%/day) is aspirational and at the edge of plausibility without ruinous leverage (CLAUDE.md:
survival first, "not a promise"). But the operator's intuition that "we can do more per day" is CORRECT: a large
slice of today's -18 bps is the amputated right tail (an exits/sizing fix, days not months) and the current book
already generates +276 bps best-5 winners it throws away. Sequence: fix the exit leak -> likely flip positive ->
fix model edge+calibration -> then conviction sizing + survivable leverage. That STACK, not a uniform per-trade
number, is where days well above 8% come from. The single binding constraint remains real, cost-aware, calibrated
MODEL EDGE (Codex trainer lane) — everything Claude fixed removed distortions that were HIDING that truth.

================================================================================
PART 5 — OPERATOR-DIRECTED CHANGES 2026-07-18 (leverage tiers, symbol priority)
================================================================================
Operator directive: stop being stuck at 1-3x; use per-symbol ADAPTIVE leverage
(BTC/ETH 1-75x, SOL/LTC/XRP 1-50x, alts 1-20x); margin adaptive; risk-first but
not perpetually conservative (don't keep missing moves); BTC/ETH/SOL always the
first symbols to trade. Authorized. What I changed and WHY:

## 5.1 CHANGED (clean files, tested) — per-symbol adaptive leverage recommendation
File: services/paper_trade_management/leverage_recommendation.py (was hard-capped 1-3x effective).
- Per-symbol CEILINGS via symbol_leverage_ceiling(): BTC/ETH=75, SOL/LTC/XRP=50, alts=20
  (env-tunable: PAPER_MAX_LEVERAGE_MAJOR_TIER1/TIER2/ALT).
- Leverage is now CONTINUOUSLY adaptive within [1, ceiling], earned from a MULTIPLICATIVE evidence
  quality score = conf_q * edge_q * vol_q (all three must be strong to approach the ceiling), then
  clamped by a volatility-scaled LIQUIDATION-SAFETY cap (keep liq distance >= 5x ATR, env
  PAPER_LEVERAGE_LIQ_SAFETY_ATR_MULT) so a normal candle can never liquidate.
- ALL existing risk gates preserved: non-positive after-cost edge -> 1x; flat/low-confidence -> 1x;
  high volatility (ATR>=80bps) -> 1x. 32/32 unit tests pass (5 new).

WHY THIS IS RIGHT (and safe on today's negative-edge book):
- Leverage is a DERIVED value from positive, calibrated, low-volatility edge — never a static grant.
  Because the current model edge is NEGATIVE (-1.39 bps validation), every trade today still resolves
  to 1x (verified: negative/zero edge -> 1x). The ceiling is RAISED but DORMANT until real edge appears.
- When the model DOES produce a strong, calibrated, low-vol signal, the system can now size a BTC move
  up toward 75x instead of leaving it at 3x — this is the "don't miss moves" half, gated by evidence.
- Liquidation-safety is adaptive to volatility (tight ranges permit more, chop forces less) rather than
  a static cap — matches "margin adaptive to market conditions."
- Majors carry more headroom because they are the deepest/most-liquid and lowest-slippage books;
  alt tail risk is higher, so 20x.

## 5.2 CHANGED (clean file, tested) — BTC/ETH/SOL selection priority
File: services/v2_symbol_runtime_universe.py — resolve_symbols() now ranks PREFERRED_MAJOR_SYMBOLS
(BTC/ETH/SOL, env V2_PREFERRED_MAJOR_SYMBOLS) FIRST in every production path, always included, with the
full adaptive universe following. Ordering PREFERENCE, not an exclusive whitelist / static threshold —
consistent with the "preferred majors, market-driven, no hardcoded lists" policy. Verified: universe of
149 symbols now leads with BTC,ETH,SOL. NOTE: strict per-cycle trade priority also depends on downstream
consumers iterating in list order; if the opportunity/selection ranker (Codex lane) re-sorts by score,
it should apply the same major preference — flagged for Codex.

## 5.3 VALIDATION — are we picking up moves in advance? (operator question)
Evidence from 92 live closed trades:
- BY TIMEFRAME: 1h is the ONLY positive-edge TF (+28.3 bps, WR 36%, n=11). 5m ~ breakeven (-4.5). 15m
  (-17), 4h (-31, the largest bucket n=37) and 1m (-70) are negative. So there IS longer-TF signal, but
  it PEAKS AT 1h — "longer = always better" is FALSE here (4h is worst). Bias signal weighting toward 1h.
- BY VOLATILITY: low ATR<30 -> WR 52%, +34.5 bps (system makes money in calm markets). high ATR>80 ->
  WR 10%, -87.5 bps (CATASTROPHIC directionally) BUT avg MFE 86 bps (the big moves ARE there).
  => Today the system CANNOT call direction in high vol (10% win rate) -> the high-vol->1x gate is
  correct RIGHT NOW. The opportunity (86 bps MFE) is real but uncaptured.

## 5.4 DESIGN — profit FROM volatility via hedging (operator vision; Codex trainer/hedge lane)
The operator is right that high volatility is where the big profit is IF the system predicts the move.
The data says: it can't yet call DIRECTION in high vol (10% WR), but the MAGNITUDE is large (86 MFE).
The correct structure for "know a big move is coming, unsure of direction" is a HEDGED/bidirectional
position that harvests magnitude either way, converting to directional once the move commits. Path:
  1. TRAINER: add a longer-TF (1h) MAGNITUDE/"big-move-incoming" head (expected |move| + confidence),
     separate from the directional P(profit) head. This is what turns volatility into signal.
  2. HEDGE: extend hedging.py from safety-only (ADAPTIVE_ADVERSE_EXCURSION_HEDGE) to a PROFIT/volatility
     hedge: when big-move-confidence is high but direction is uncertain, open a bounded straddle-like
     pair; unwind the losing leg once direction commits, let the winning leg run (ties to the CG-F052
     right-tail fix). Keep the existing caps (<=35% ratio, mandatory unhedge condition, maintenance-margin
     rejection) — risk stays bounded.
  3. LEVERAGE GATE: make the high-vol->1x gate EDGE-CONDITIONAL — once a calibrated big-move signal +
     an active hedge are present, permit controlled (liquidation-safe) exposure in high vol instead of
     a blanket 1x. Until that signal exists (now), stay 1x. I did NOT loosen the gate yet because on a
     10%-WR-in-high-vol book, loosening would be reckless; it unlocks with proven predictive power.

## 5.5 STAGED / FLAGGED for Codex (binding cap — do NOT edit their in-flight files)
The BINDING per-cycle leverage cap is the dynamic risk envelope in Codex's UNCOMMITTED files:
  - adaptive_capital_allocator/dynamic_envelope.py: _PAPER_HARD_MAX_LEVERAGE = 10.0 (final clamp) and
  - contracts.py: RiskEnvelope.max_effective_leverage default 3.0 (base).
So effective leverage stays <=10x until these are lifted, regardless of the (now up-to-75x) recommendation.
EXACT change for Codex (or after they commit): make the hard cap per-symbol/env-driven and consume
symbol_leverage_ceiling() as the clamp, keeping the realized-win-rate/PF/drawdown exp() scaling so high
tiers stay EARNED. I did not edit these to avoid clobbering Codex's active CG-F049/G10 money-path work.

-- Runtime state: leverage_recommendation + symbol priority are LIVE (clean files); effective leverage
   remains <=10x (Codex envelope) until 5.5 is applied; live trading remains BLOCKED.
