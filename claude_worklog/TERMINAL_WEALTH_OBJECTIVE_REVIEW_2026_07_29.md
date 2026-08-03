# Terminal-Wealth Objective — Adversarial Review of In-Flight Implementation (2026-07-29)

Reviewer: Claude (interactive session). Subject: the UNCOMMITTED working-tree
implementation of the operator's 90-day terminal-wealth directive on branch
`codex/pipeline-trust-refresh` (Codex in-flight; last file touch observed
21:30 EDT). Review inputs: 8-reader subsystem map (1.22M tokens), 4-lens
adversarial design panel (math/contracts/ops/fidelity), and direct raw reads
of the working tree. Every finding below carries a working-tree anchor;
line numbers are as of 21:30 EDT and will drift while Codex edits.

## What the implementation gets RIGHT (verified)

- Info-gain-per-loss is genuinely demoted from primary: designation ranking key
  is now `(learned_terminal_utility, terminal_target_probability,
  expected_log_growth, −liquidation_probability, gain_nats, action_id)`
  ([paper loop :41764-41771]) with the selection rule string updated; IG kept
  as hard eligibility (positive) and tie-break — preserving the cold-start
  escape that authorization requires (`expected_information_gain > 0`,
  adaptive_paper_policy_authorization_v2.py:401-405, unmodified).
- Parity discipline held: production utility, reference twin
  (adaptive_objective_reference_v2.py:48-63), score replay, and evaluation
  replay all updated in lockstep; 358/358 adaptive_system + domain unit tests
  pass on the current tree.
- Contract style preserved: TerminalEquityProjectionV1 is a fingerprint-safe
  frozen dataclass with `guaranteed_target_claim` forced False, horizon/multiple
  pinned to 90/1000, quantile monotonicity, PIT `state_available_at_ms ≤
  decision_time_ms`, and full paper-only/live-blocked flags (adaptive_objective_v2.py:496-616).
- Paper-loop producer publishes an authenticated terminal state per cycle
  (epoch starting equity, session started_at, pre-cycle equity/drawdown —
  `terminal_objective_state`, paper loop :55397-55412).
- Correlation entered both the state (correlation_exposure_fraction/bps) and
  the fitted objective (correlation_penalty fitted INSIDE the logistic
  optimizer on correlation_exposure × |MAE| features — genuinely learned).
- New weights flow producer→consumer coherently (fitter → artifact →
  `_weights` rebuild → fingerprint recomputation).

## Findings (ranked)

### F1 — BLOCKING — Units mismatch neutralizes every risk penalty
`expected_log_equity_growth_reward = return_scale / mean(|per-trade log1p return|)`
(calibration_v2.py:1253-1263) prices **per-trade** nats (weight ≈ 10^4 when
mean |return| ≈ 30 bps). But the utility multiplies it by the **full-horizon**
compounded growth `opportunities × log1p(f·edge)` (shadow `_terminal_equity_projection`
:1600-1619; consumed in `_derive_score_values`). For a 5m intent at the 8%
exposure cap with +30 bps edge: n ≈ 3,900 opportunities → growth ≈ 0.94 nats →
contribution ≈ **9,400**, while the return term ≈ 30 and drawdown/tail/
liquidation/impact/funding/turnover/concentration penalties total ≈ tens.
The declared minimization terms influence ranking at the ~0.3% level — the
objective effectively maximizes `edge × n × f` alone. Any noise-positive
after-cost edge (current stats are counterfactual-informed, posterior
prior-only) is amplified ~300×, and utility>0 exploration gating loses its
cost-scale meaning (mass-admission risk once any edge estimate goes positive).
**Fix options:** (a) score the growth term per-opportunity (μ_step, keeping n
only in the published projection), or (b) scale all penalty inputs to the same
horizon basis (n×), or (c) normalize the growth input by n before weighting.
One consistent unit basis, declared in UNIT_CONTRACT, with a magnitude
regression test (growth contribution within, say, 10× of the return term at
reference operating points).

### F2 — BLOCKING — Deploy skew = paper-loop crash-loop, not graceful block
`validate_candidate_outcome_calibration_v2` still does NOT require the new
weight fields (fingerprint-consistency only, calibration_v2.py:1693-1699
region) — the LIVE redis artifact (verified: schema `learned_objective_weights_v2`,
no terminal fields) passes validation, then `_weights` hits
`raw["terminal_target_probability_reward"]` → **KeyError** (shadow :265-271),
which is NOT in the paper-loop catch tuple (paper loop :55432-55440:
AdaptivePolicyShadowError/OSError/RuntimeError/TypeError/ValueError only) —
unhandled → run_once dies → systemd restart loop for as long as the old
artifact sits in redis. Same gap in the designation guard (:51862 tuple).
**Fix:** (1) validator requires every v3 weight key + schema string;
(2) `_weights` uses a strict accessor raising AdaptivePolicyShadowError;
(3) add KeyError/LookupError to both catch tuples anyway;
(4) deploy choreography (all four units run SHA-pinned immutable checkouts,
currently on THREE different SHAs, with Requires= coupling): one commit set →
one release checkout/venv → repoint 90-immutable-*.conf for calibration
publisher + candidate outcome publisher + shadow runtime + paper loop to the
SAME SHA → daemon-reload → restart calibration publisher first → verify v3
artifact in redis → restart paper loop + shadow. Rollback = repoint drop-ins
to the previous SHA (old artifact remains valid for old code).

### F3 — BLOCKING — Silent-default evidence path stamps `evidence_supported_probability=True`
When `terminal_objective_state` is absent/partial, the estimator silently
falls back: `session_started_at → decision_time` (horizon resets to a full
90 days), `starting_equity → current_equity` (the 1000× target re-anchors
every cycle), drawdown → 0, regime → 0.5 (shadow :1474-1499), then stamps
`evidence_supported_probability=True` unconditionally (:1740). The paper-loop
producer is honest, but any consumer without the new producer — the UNMODIFIED
diagnostic shadow runtime (v2_adaptive_policy_shadow_runtime.py) reading live
`v2:paper:trade_management:status` — fabricates a fresh-horizon projection
labeled as evidence-supported. Violates the Evidence Integrity Rule and
directive point 10.
**Fix:** absent/defaulted state ⇒ either raise (paper-loop path, where the
producer guarantees presence) or emit `evidence_supported_probability=False`
prior-only projections; never defaults posing as evidence. Bind the terminal
state's digest into the action input fingerprint.

### F4 — BLOCKING — False "learned online" attestations
`terminal_target_probability_reward = expected_log_equity_growth_reward × ln(1000)`
(deterministic transform, calibration_v2.py:1265-1268) and the growth reward is
a ratio-of-means — the exact non-optimizer pattern the fitter's own docstring
says was removed. Yet optimizer evidence stamps
`terminal_target_probability_reward_learned_online: True`,
`expected_log_equity_growth_reward_learned_online: True`, and
`all_economic_tradeoff_weights_learned_online: True` (:1317-1321).
Genuine-attestation is a standing hard rail.
**Fix:** either fit both rewards inside the logistic optimizer (features:
realized log-equity contribution & target-progress per matured row — the data
exists) or declare the derivation honestly
(`derivation: RETURN_SCALE_RATIO_TIMES_LN_TARGET_MULTIPLE`, learned_online:
false) and drop the aggregate flag. Do not ship self-contradicting evidence.

### F5 — IMPORTANT — terminal_target_probability is a step function with fabricated certainty
Variance model has NO persistent parameter-uncertainty term (posterior
uncertainty enters only as a multiplicative per-step stddev inflation,
:1636-1641; variance grows as n·σ² only). With drift and sd both scaling in n,
P(target) ≈ step(sign(n·μ − ln1000-distance)): ≈0 everywhere inside the 8%
exposure cap (z ≈ 44+ → float underflow), snapping to ≈1 for large-f plans
(f ≳ 0.2 at 50 bps edge) — a claim of near-certain 1000× on a prior-only
posterior. As a utility term it is inert-or-overconfident; as published
telemetry it is dishonest at the boundary. The panel's quantitative lens
(UNSOUND verdict) derived the same failure for the design I drafted.
**Fix:** add the persistent-uncertainty term (law of total variance over the
Beta posterior; exact since μ is linear in p), compute tail probabilities by
quadrature over the posterior (or closed form P_Beta(p ≥ p*)), and stamp
prior-only/underdispersed flags when magnitude/cadence evidence is thin.
Keep raw P out of the utility (it already is, effectively — F1 dominates);
report it honestly (≈0 today).

### F6 — IMPORTANT — Self-crediting horizon conditioning + timeframe bias
Each directional action's growth term assumes ITS OWN trade is repeated for
the entire remaining horizon (n = remaining/timeframe_horizon × fill × regime
× (1−corr), :1600-1610); flat gets 0. Consequences: (a) a single 5-minute
trade is credited with 90 days of compounding — the direction-vs-flat
comparison is biased toward trading on hair-positive noise edges; (b) n scales
inversely with timeframe (5m gets 48× the 4h credit), structurally preferring
the smallest timeframe regardless of per-trade evidence quality; (c) the
"opportunities" model ignores the position-transition rail (one open position
at a time) and realized cadence — it is an upper-bound capacity, not an
evidence-based rate.
**Fix (aligned with F1):** rank on per-opportunity contribution with the
posterior/cadence/n FROZEN across action and flat branches (only the current
fill-weighted step differs); publish the horizon projection separately. Add
the panel's unit test: zero-edge, zero-cost action ⇒ zero terminal deltas.

### F7 — IMPORTANT — Loss/liquidation model internally inconsistent
(a) `1 − exp(−q·√n)` for horizon liquidation (:1651-1656) is an undeclared
ad-hoc form (why √n?); (b) per-trade tail mass is double-counted — full tail
retained in the dispersion AND compounded into liquidation probability;
(c) the −0.999999999999 clamp on per-opportunity return (:1614-1617)
fabricates a finite log-step where the true event is ruin; (d) loss is not
truncated at the liquidation boundary (beyond-margin losses are impossible in
isolated margin). Declare the model (three-branch mixture: win / loss
truncated at boundary / liquidation) or document the approximations in the
projection payload.

### F8 — IMPORTANT — Requirement 9 publication is embedded-only
`_terminal_equity_after_completed_outcome` (outcomes.py, new) computes
`terminal_paper_equity_after_outcome_v1` per close and embeds it in the close
record — good lineage — but there is NO dedicated status key, nothing surfaces
it to Monitor Center/Signal Explainability, the calibration fitter never sees
realized-vs-projected error, and `v2:goal:trajectory_1000x`
(v2_1000x_trajectory_tracker.py) remains BROKEN post-rotation
(days_elapsed=null — parses a timestamp suffix hashed session ids don't have;
equity sums closed_trades UNSCOPED, mixing archived sessions).
**Fix:** publish `v2:adaptive_system:terminal_wealth:status` on each close
batch (probability, distribution quantiles, evidence counts, prior-only flags,
`target_guaranteed: false`), and repair/session-scope the 1000x tracker to the
epoch pointer (`v2:paper:account_epoch:current.started_at`).

### F9 — MEDIUM — Residual fixed cutoffs unclassified (directive point 5)
Surviving fixed constants in the effective selection path (verified live):
`PAPER_DRAWDOWN_RECOVERY_MIN_CONFIDENCE = 0.65` (paper loop :442),
`POSITIVE_EDGE_PROBATION_LOSS_PROBABILITY_BOUND = 0.65` (:876), the
0.65–0.75 adaptive-confidence clamp band, exploration `utility > 0`, champion
flat-baseline requirement. Some are structural safety (allowed), some are
allocation knobs. The directive demands an explicit inventory: classify each
as operator-envelope/structural (justified) or adaptivize in a named
follow-up. Currently undocumented.

### F10 — MINOR
- Designation `schema_version` stays `bootstrap_information_acquisition_designation_v1`
  while semantics changed (rule string, terminal hard filters). Old shadows
  ignore unknown versions gracefully — bump to v2 is skew-safe and honest.
- Diagnostic shadow runtime unmodified → will diverge from paper-loop
  evaluations and hit the F3 default path; update or gate it.
- The `(1 − correlation)` opportunity haircut and `regime` multiplier in the
  opportunity count are undeclared heuristics — name them in the projection
  payload assumptions.

## Directive scorecard (10 points)

1. Full candidate universe — PASS (unchanged universe; designation traverses full ranked set).
2. Terminal distribution per candidate/plan — PARTIAL (p10/p50/p90 + P(target) exist; math per F5-F7).
3. State completeness — PASS (equity, target distance, time, drawdown, edge, uncertainty, costs, liquidity, correlation, regime all present; evidence chain per F3).
4. Max P(1000x)+log-growth+info / min tail+liq+cost+concentration+correlation — STRUCTURAL PASS, NUMERICAL FAIL (F1 neutralizes minimization terms).
5. All multipliers learned online, no fixed knobs — PARTIAL (correlation genuinely fitted; two terminal rewards are transforms with false flags — F4; residual cutoffs unclassified — F9).
6. Policy chooses symbol/tf/side/notional/leverage/margin/entry/stop/exit/holding — PASS within existing action set; hedging remains structurally disabled (hedged action pinned to probability 0, hedge_enabled=False hardcoded — needs explicit scope note or enablement).
7. Continuous execution, async maturation — PASS (preserved by design; docstrings updated).
8. Invariants preserved — PASS in code structure (hard validator, venue attestation, accounting, mandatory stop, causality untouched); F2 threatens availability, not safety.
9. Publish after every completed outcome — PARTIAL (embedded per-close only — F8).
10. No guarantee claims, honest probability — PARTIAL (guaranteed_target_claim=False enforced; F3/F4/F5 undermine honesty of the numbers themselves).

Permanent flags: paper_only/live_gate/routes_to_live/places_real_order/
exchange_action_taken verified forced at every new contract layer. PASS.

## Recommended completion order

1. F2 validator+accessor+catch-tuple+deploy choreography (availability).
2. F1 unit-basis fix with magnitude regression test (economics).
3. F3 evidence honesty + F4 attestation honesty (integrity rails).
4. F5-F7 estimator math hardening (can land as follow-up with declared
   approximations in the payload meanwhile).
5. F8 status key + 1000x tracker repair; F9 cutoff inventory; F10 hygiene.
