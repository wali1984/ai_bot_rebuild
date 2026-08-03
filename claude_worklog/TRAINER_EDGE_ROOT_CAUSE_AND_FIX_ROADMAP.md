# Trainer Edge Root Cause + Fix Roadmap — WHY the model has no edge (CG-F053 deep dive)

Date: 2026-07-17 | Workflow: wqo5fbkgi (11 agents, adversarially verified, READ-ONLY)
Lane: TRAINER / Codex Agent 1 (native_trainer is a protected ML runtime — Claude diagnoses, does NOT mutate)

## The question
CG-F053 established the deployed model has NO demonstrable directional edge
(Spearman(confidence, realized_pnl_bps)=+0.10, p>0.30; win% flat across confidence
terciles; expected_move inverted vs outcome). WHY — and what specifically fixes it?

## TWO code-proven PRIMARY causes (both required; neither alone is enough)

### PRIMARY 1 — Confidence head trained on the WRONG target (surgical fix)
`ppo_trainer.py:1920-1923` (and the supervised-loss twin at :1751-1754):
    confidence_loss = mse(out["confidence"], clamp(abs(expected_move_training_target)/100, 0, 1))
The confidence head is regressed on move MAGNITUDE, not probability-of-profit. So
"high confidence" literally means "large predicted move" — orthogonal by construction
to whether the trade WINS. Serving-side proof: spearman(|expected_move|, confidence_calibrated)=0.77
(the head does exactly what it is trained to do). This decorrelation would persist
even if the model had perfect edge. A monotonic recalibration CANNOT fix it (confidence.py:223).
FIX (targeted retrain, fast to validate): regress out["confidence"] against the realized
AFTER-COST profit/loss SIGN of closed paper trades — a calibrated P(profitable|features)
head. Success check: Spearman(confidence_calibrated, realized_net_pnl_bps) turns clearly
positive and win% separates across terciles on held-out realized outcomes.

### PRIMARY 2 — Data starvation / over-capacity → memorization → NEGATIVE OOS edge
The over-capacity net (1784-in / 2048-hidden / 4 residual blocks / GRU seq16) memorizes
a thin single-regime example set:
- train loss 40.77 -> 0.095 while validation loss stays flat ~28-30 (gap ~28) = textbook memorization
- examples=2846 built from 853,800 rows => **99.7% of rows REJECTED**; trusted_replay_examples_built=0
- validation_policy_edge_after_cost_bps=-1.39 (LCB -2.26) on its OWN held-out label; backtest expectancy -0.194 bps, PF 0.994
- 48 consecutive VALIDATION_POLICY_EDGE_NONPOSITIVE promotion rejections; effective_trainer_mode=INFERENCE_ONLY (serving a FROZEN prior checkpoint)
- ppo_entropy=1.056 = 96% of ln(3) => policy is near-UNIFORM (learned no directional preference; NOT collapsed)
**KEY PROOF edge IS extractable:** a simple 32-feature Ridge extracts +30 bps after-cost
on 4,484 holdout rows. So the signal exists; the deep net's data-fit/capacity is the failure.
FIX (retrain): repair the example-building pipeline — un-reject the 99.7% (fix
`missing_mask_schema_introduction_unproven` + `FUTURE_CANDLE_HORIZON_MISSING_4H` so
trusted_replay_examples_built > 0), widen TRUSTED_REPLAY_INITIAL_LOOKBACK_SECONDS beyond 25h
for multi-regime coverage, match capacity to data. Interim: harden + promote the holdout-passing
Ridge challenger (fix its 2580/119 long/short imbalance first). Also activate the DARK PPO
realized-reward lane (ppo_objective_used=false, 0/67 rows consumed, reason
CLOSED_ROWS_MISSING_ON_POLICY_FIELDS) so the policy trains on realized advantage, not on
imitating a negative-OOS-edge forward-move label.

## CONTRIBUTING (real, but not the confidence-decorrelation root)
- **Feature staleness / train-serve skew (fast, mixed lane):** training drops every stale row
  (trusted_only), but inference runs ~99% funding/long_short stale (v2:market:funding/long_short
  frozen ~27h; verified) + a 33/91 heuristic fallback lane with NO feature snapshot. NONE-snapshot
  cohort = 24.2% win / -50.5bps vs PRESENT = 44.8% / -1.2bps; retiring the stale lane moves the
  book -19 -> -1.2 bps (does NOT create edge). FIX: (a) add an inference point-in-time gate
  mirroring training (block entries with entry_feature_snapshot=None /
  FEATURE_AVAILABLE_AT_AFTER_DECISION_TIME) — paper-loop/entry-gate (Codex-active files);
  (b) OPERATIONAL: the v2:market funding/long_short feed is stale despite
  ai-bot-v2-binance-public-metadata-ingestor.service being active 21h — the funding/price write
  path is broken within the running ingestor (running-but-stale, like the prior _fetch_ticker_24hr
  echo bug); either fix the ingestor fetch or re-point the regime/cascade layer at the FRESH
  coinglass feed (v2:features:coinglass:*:1m, confirmed present). NEEDS its own operational dig.
- **Calibration compression (hygiene, fast):** confidence_temperature.json ABSENT => fixed T=1.4
  (fit_temperature() never ran) + coverage/missing shrink-toward-0.5 (confidence.py:223, 123/446
  features missing) compress confidence to the 11pp band. Monotonic => cannot create correlation,
  but cripples the confidence-floor gate + risk sizing as levers. FIX: fit+write the temperature
  from held-out realized outcomes; expose the data-quality shrink as a SEPARATE field; drop
  raw=max(probs[selected], confidence_head) (model.py:654); publish ECE/Brier/reliability.

## REFUTED
- **Label horizon mismatch (H2):** the 900s training label vs variable trailing-stop exit is real
  but REFUTED as the driver — the promotion-blocking validation edge is computed horizon-self-
  consistently and never sees the paper-book exit horizon. Deprioritize.

## Ordered roadmap
1. [trainer] Confidence-head target -> P(profitable) (PRIMARY 1). Surgical, fast to validate.
2. [trainer] Repair example pipeline (un-reject 99.7%, trusted_replay_examples_built>0) + widen lookback (PRIMARY 2). The reason there IS no edge.
3. [trainer] Activate the dark PPO realized-reward lane (fix CLOSED_ROWS_MISSING_ON_POLICY_FIELDS).
4. [claude/operator] Inference PIT gate to retire the stale lane (-19 -> -1.2 bps) + repair/re-point the dead funding feed.
5. [trainer] Fit confidence temperature + publish calibration telemetry (hygiene; unlocks the confidence gate).
6. [operator] Keep LIVE BLOCKED + leverage un-escalated until Spearman(confidence, realized_pnl) is positive OOS on a larger multi-regime sample.

## Honest framing for operator
The model isn't mysteriously edgeless — it has two specific, code-located defects: (1) it's
literally trained to be confident about big moves, not about winning; (2) it memorizes a
starved dataset. A 32-feature Ridge already finds +30bps of edge in the same data, so the
signal is there. These are trainer-lane fixes (Codex Agent 1 / protected runtime); risk-side
fixes (ceiling/liquidation/sizing) keep the book alive at breakeven meanwhile. 1000x still
runs through the trainer producing OOS-verified edge — but now with a concrete, prioritized
punch list instead of "improve the model."
