# Path to 1000x — Binding Constraint + Right-Tail Amputation (read-only analysis)

Date: 2026-07-18 | Author: Claude (read-only; no runtime state changed)
Scope: operator research request — "where are we lacking to reach 1000x, and how should the
trainer + other components act." Feeds CG-F052 (stop/sizing) and CG-F053 (trainer edge).
Evidence base: live v2:paper:closed_trades (92 post-policy), v2:trainer:hybrid_cuda:status.

## 1. The target is a floor, not a shape
1000x in 90 days = 7.98%/day UNIFORM compounding. But real returns are lumpy: the ceiling is
set by the fat right tail, not a smooth per-trade number. Reference floors (for context only):
  - @22 trades/day (current pace, ~2000 trades): +35 bps/trade geometric for exactly 1000x.
  - Currently: -16.8 bps/trade (simple), -18.1 bps notional-weighted, PF 0.658, 37% win rate.

## 2. TWO independent deficits (not one)

### Deficit A — directional/edge (CG-F053, TRAINER lane)
- Model's OWN PIT-safe validation edge = -1.39 bps after cost (lower bound -2.26, 402 rows,
  chronological purged split). effective_trainer_mode=INFERENCE_ONLY, serving a prior checkpoint
  "after rejection"; the PIT edge-promotion gate is correctly hard-rejecting (no edge to promote).
- Root causes: confidence head trained on move MAGNITUDE (clamp(|move|/100)) not P(profit-after-cost);
  overconfidence T~5.4 (why sizing is anti-correlated with outcome: notional-weighted -18.1 WORSE
  than simple -14.9); ~99.7% training-row rejection -> memorization -> negative OOS; cost-blind reward.
- Counter-evidence the edge IS capturable: a 32-feature Ridge extracts +30 bps on the same holdout.

### Deficit B — RIGHT-TAIL AMPUTATION (CG-F052, EXITS/SIZING lane) — the fast, under-recognized one
Winners are cut at ~55% of their favorable move; losers ride longer. The book violates the golden rule.

Evidence (92 closed):
  - avg winner +93 bps, avg loser -81 bps -> R:R only 1.15 (need >1.70 at 37% WR to break even).
  - best-5 winners avg +276 bps (KITE +370, CAP +348, ENS +244, TU +211, TLM +206) — the tail is large.
  - MFE-capture: winners realize only ~55% of max-favorable-excursion. Examples of money left on table:
      LDO 42/138 (30%), TIA 63/191 (33%), MET 42/116 (36%), AGLD 79/182 (43%), SLX 154/343 (45%),
      OPN 44/95 (47%). A dense cluster exits at a near-FIXED ~42 bps regardless of MFE.
  - Exit-reason mix: TIER_2_TRAILING_STOP (30) + TIER_2_MFE_BREAKEVEN_PROTECTION (12) = 42/92 exits
    are the trail/breakeven logic locking in small gains and killing runners. Losers exit on
    TIER_0_CATASTROPHIC (20) + TIER_1_ATR (15).
  - Hold times: winners 73 min < losers 81 min. Inverted — we cut winners faster than losers.

Impact estimate: if MFE-capture rose from ~55% -> ~85%, avg win ~+93 -> ~+140 bps, R:R ~1.15 -> ~1.7,
which at the current 37% win rate is roughly break-even-to-positive WITHOUT any model improvement.
The favorable moves already exist; the exit ladder discards them. This is a stop/sizing fix, not a retrain.

## 3. The levers that make "much more per day" real (ranked by ROI)
1. Fix exit asymmetry (immediate, no model dependency): MFE-proportional trailing (widen the trail as
   MFE grows), partial scale-outs with a "runner" tranche that only exits on true reversal or the
   catastrophic floor; keep tight stops on LOSERS only. Cut losers faster than winners.
2. Conviction concentration (the multiplier for 20-50% days): fractional-Kelly sizing on CALIBRATED
   P(profit); add-to-winners on confirmation. A few high-conviction runners sized aggressively produce
   the big days — not 22 uniform trades.
3. Leverage on tight-invalidation setups: 20 bps invalidation carries far more notional per dollar of
   risk than a 100 bps stop — high capital efficiency without liquidation risk.
4. More concurrent uncorrelated shots across the 136-symbol universe (microstructure/orderbook/liq feeds
   are live+healthy = the edge-discovery surface).

## 4. How each component must act
- TRAINER: relabel confidence head to P(profit-after-cost); bake round-trip cost into PPO/MASA reward;
  temperature-scale to T~1 (calibration is what makes conviction sizing SAFE); break the 99.7% row
  starvation via H2L/historical replay. KEEP the PIT promotion gate strict — make the model pass it.
- EXITS (exits.py, CG-F052): MFE-scaled trailing + scale-out tranches + runner tranche; asymmetric
  hold (cut losers < winners). Target metrics: MFE-capture >=80%, R:R >=1.7, winner-hold > loser-hold.
- ALLOCATOR (sizing_model.py): variable conviction-weighted size (fractional-Kelly on calibrated P);
  add-to-winners; fix notional=margin*leverage honesty (G10) so pressing is accounted for.
- GATES/preemptive-edge: keep blocking negative-EV; job flips to "admit a high-edge subset" once the
  model produces one. Do not loosen without model edge (converts blocked losses to realized losses).
- RISK/survival: activate the (currently inert) cross-margin cascade guard BEFORE any size scaling;
  per-trade dollar-risk cap. A single liquidation erases the entire compounding run.
- ORCHESTRATOR: do not authorize size/leverage scaling until trainer publishes a PROMOTED checkpoint
  with positive PIT-safe post-cost edge. Proposes; risk gateway disposes.

## 5. Ordering (honest)
Every lever multiplies expectancy, so signed edge must be >=0 first. BUT a large slice of the -18 bps
is the amputated right tail (Deficit B) — an exits/sizing fix that is fast, evidenced, and independent
of the months-long model retrain. Sequence: (1) fix the exit leak -> likely flips the book positive;
(2) fix model edge + calibration; (3) turn up conviction sizing + survivable leverage -> that stack,
not a uniform per-trade number, is where days well above 8% come from. 1000x/90d remains aspirational
(CLAUDE.md: survival first, "not a promise"), but the realized path is lumpier and higher on good days
than the smooth-compounding floor implies — the operator's intuition is correct.
