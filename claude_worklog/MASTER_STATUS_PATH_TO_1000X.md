# AI BOT V2 — Master Status & Path to 1000x (consolidated)

Date: 2026-07-17 | Author: Claude | Live: BLOCKED (unchanged) | Paper book: -$11.89 / PF 0.70 / 91 trades

This ties together the whole session's work into one decision-ready page. Detail in the
per-topic worklogs + FINDINGS.jsonl (CG-F049..F053).

## Your four original concerns — answered
1. **"1x leverage is static/fake"** — TRUE, and deeper than a display bug. The reported
   leverage was fiction: capital accounting was incoherent (CG-F050), and separately the
   model has no edge to justify leverage. Leverage is now correctly un-escalated; scaling it
   on a no-edge book multiplies losses (the reverted aggressive-leverage commits were right).
2. **"BTC/ETH/SOL not preferred"** — working as designed: adaptive universe, majors stable-
   sorted first but selection is market-driven (no hardcoded lists, per policy). Not a defect.
3. **"1000x in 90 days not ready"** — CORRECT. The book loses money. Root cause is model
   edge, not gates/leverage (see below). Now root-caused to specific code with a fix plan.
4. **"A+ grade not flowing"** — the probe/admission chain was fixed earlier; the binding
   constraint is now genuinely model edge quality, not gating.

## The honest bottom line
- **Risk-management fixes get the book to BREAKEVEN, not profit.** All risk drags combined
  (ceiling + liquidation + sizing + stale-lane) move -$11.89 -> ~-$1.85 / PF ~0.92. They do
  NOT create positive expectancy. (Adversarially verified; do not sum per-dimension gains — they
  overlap the same ~34 catastrophic-long trades.)
- **The money must come from the trainer.** The model has NO demonstrable directional edge —
  and we now know exactly why (CG-F053), with proof a 32-feature Ridge extracts +30bps on 4,484
  holdout rows. The edge is THERE; the deep model just isn't capturing it.

## Priority punch list (impact | owner | status)
| # | Action | Expected impact | Owner | Status |
|---|--------|-----------------|-------|--------|
| 1 | Confidence head: train on P(profit), not \|move\| (ppo_trainer.py:1920-1923) | Makes confidence correlate with winning — the core edge defect | TRAINER (Codex A1) | roadmap handed off |
| 2 | Un-reject the 99.7% training rows / trusted_replay_examples_built>0 + widen lookback | Creates the edge (memorization -> generalization) | TRAINER | roadmap handed off |
| 3 | Activate dark PPO realized-reward lane (CLOSED_ROWS_MISSING_ON_POLICY_FIELDS) | Trains policy on realized PnL not a bad label | TRAINER | roadmap handed off |
| 4 | ATR-stop ceiling (PAPER_ATR_STOP_CEILING_BPS=80) | -$11.89 -> ~-$2.49, bounds tail risk (NOT profit) | OPERATOR activate | built+committed 7b0f1ebb65, drop-in ready |
| 5 | G10 hidden-leverage repair (45 stored rows) | G10 gate PASS; accounting coherent | OPERATOR authorize | built+proven, tools/g10_capital_invariant_repair.py --apply |
| 6 | Liquidation exit fix (CG-F051) | Real margin-call backstop (was dead code) | CODEX (done in worktree) | DONE uncommitted, test green |
| 7 | Short-edge inversion (CG-F049) + inference PIT gate (retire stale lane) | ~$0 in-sample $ but restores model's short distribution; stale-lane retire -19->-1.2bps | CODEX (entry_gate.py) | in progress uncommitted |
| 8 | Fix/repoint stale funding+long_short feed (27h) to fresh coinglass | Removes stale features from inference | OPERATOR/CODEX | flagged, not started |

## Sequencing to 1000x
1. TRAINER produces edge (#1-3) — the ONLY path to positive expectancy. Validate: Spearman(confidence,
   realized_pnl) turns positive OOS on a larger multi-regime sample.
2. Risk plumbing coherent (#4-7) — keeps the book alive at breakeven and bounds tail risk meanwhile.
3. ONLY THEN scale leverage/hedging on a proven positive-edge book. Not before.
4. LIVE stays BLOCKED until out-of-sample edge is demonstrated.

## What's yours to decide right now
- Activate the ceiling (#4) — one drop-in, halves the loss, bounds tail risk.
- Authorize the G10 repair (#5) — one command, turns G10 green.
- Green-light the trainer roadmap (#1-3) for Codex Agent 1 — the actual 1000x lever.

## Guardian gate reality (all 6 reds are HONEST)
G03 (5 findings tracked) · G10 (capital repair pending your authorization) · G11/G13/G14
(negative edge -> trainer) · G12 (6 grading artifacts + 2 real risks S08/S17, the latter now
fixed by Codex). None are gaming; they measure real state. They go green as the trainer produces
edge and you authorize the risk-side fixes.
