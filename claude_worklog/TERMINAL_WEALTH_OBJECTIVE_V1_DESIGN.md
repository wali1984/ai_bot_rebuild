# TERMINAL_WEALTH_OBJECTIVE_V1 — Design (2026-07-29)

> **SUPERSEDED IN PART (same day):** a concurrent Codex implementation of this
> directive landed in the working tree while this design was under adversarial
> review. The authoritative document is now
> `TERMINAL_WEALTH_OBJECTIVE_REVIEW_2026_07_29.md` (review of the in-flight
> code, with the design panel's math findings folded in). This design stays as
> the reference for the delta-based estimator math the panel endorsed
> (per-step Δlog-growth + Δz transform; quadrature tails; persistent
> parameter-uncertainty variance).

Operator directive: replace information-gain-per-loss as the PRIMARY allocation
objective with a horizon-aware terminal-equity objective (90-day horizon,
1000x-of-starting-equity target), inside the EXISTING pipeline. No new project,
service, selector, or execution path. All invariants preserved. paper_only=true,
live_gate=blocked_human_only, routes_to_live=false, places_real_order=false,
exchange_action_taken=false — permanently.

## 1. Where the current objective lives (raw evidence)

| Surface | File:line | Current rule |
|---|---|---|
| Fitted linear utility | `v2/backend/app/services/adaptive_system/adaptive_objective_v2.py:620-641` | utility = w_ret·after_cost_return − Σ penalties + w_ig·E[info_gain] |
| Exploration eligibility | `adaptive_objective_v2.py:1034-1055` | exploration requires utility>0 AND information_gain_contribution>0 |
| Bootstrap designation ranking | `v2/backend/app/cli/v2_trade_management_paper_loop.py:41653-41691` | `MAX_EXPECTED_INFORMATION_GAIN_NATS_PER_EXPECTED_LOSS_USD` (the literal info-gain-per-loss primary) |
| Weight learning (online) | `v2/backend/app/services/adaptive_system/candidate_outcome_calibration_v2.py:1137-1255` | positive projected logistic risk-price fit over matured outcomes; info reward from rejected-profitable mean |
| Per-action inputs | `adaptive_policy_shadow_v2.py:1416-1560` (`_objective_action`) | built from hierarchical Beta posterior stats (`_statistics` :449-517) |
| Selection parity mirror | `adaptive_objective_reference_v2.py` | independent recompute; any production-only change = parity disagreement |
| Horizon/target anchor | `v2/backend/app/services/paper_session/epoch.py:27,110-114,733-741` | epoch pointer `v2:paper:account_epoch:current`: `started_at`, `starting_equity_usd=3000`, epoch |

## 2. Objective definition (new)

Declared objective constants (objective DEFINITION, not tunables — echoed in
every payload and in the unit contract):

- `TERMINAL_HORIZON_DAYS = 90` measured from the current paper-account epoch
  pointer `started_at`.
- `TERMINAL_TARGET_MULTIPLE = 1000.0` of the epoch `starting_equity_usd`.
- The target is a research objective; every payload carries
  `target_guaranteed: false` and evidence-support fields.

### 2.1 TerminalWealthStateV1 (new pure contract, adaptive_system module)

Fingerprinted frozen dataclass carrying, per decision cycle:
current_equity_usd, starting_equity_usd, target_equity_usd, horizon_start_ms,
horizon_end_ms, decision_time_ms, remaining_ms, current_drawdown_fraction,
open_position_count + concentration effective count (reuse
`_concentration_effective_count`, calibration_v2.py:669), posterior bucket
evidence (alpha/beta/effective N/bucket identity), cost aggregates
(slippage/impact/funding/transaction medians), fill_probability (liquidity),
regime bucket, and online-learned cadence evidence (observed closes/day this
epoch with sample count). Missing evidence is carried explicitly
(prior-only flags), never guessed.

### 2.2 Terminal-equity distribution estimator (pure, deterministic, stdlib)

Posterior-predictive analytic projection per feasible trade plan:

- Win prob p ~ Beta(α, β) from the hierarchical posterior bucket
  (`_statistics`, adaptive_policy_shadow_v2.py:493-515).
- Per-trade equity log-step from plan notional-fraction f (= notional/equity),
  calibrated win/loss magnitudes (after-cost expectancy + MAE/tail quantiles,
  bps of notional), fill probability, cost drag:
  - g_w = f·win_bps/1e4, g_l = f·loss_bps/1e4
  - μ_step(p) = fill_p·(p·ln(1+g_w) + (1−p)·ln(1−g_l))
  - within-step variance from the win/loss mixture; parameter (edge)
    uncertainty via law of total variance — persistent across trades:
    Var_total(n) = n·E[var_within] + n²·(∂μ/∂p)²·Var(p)
- Remaining trade count n = cadence_per_day · remaining_days, with cadence
  learned online from current-epoch authenticated closes (NOT a fixed
  frequency target); cadence uncertainty adds n-variance which propagates.
- Terminal log-equity ≈ Normal(ln E_now + n·μ_step, Var_total) →
  - `terminal_target_probability` = P(ln W_T ≥ ln target) via math.erf
  - `expected_terminal_log_growth`
  - terminal-equity quantiles (0.05/0.25/0.5/0.75/0.95)
  - `terminal_downside_probability` = P(W_T ≤ downside floor derived from the
    catastrophic-loss envelope fraction of current equity)
  - `horizon_liquidation_probability` = 1 − (1 − liq_prob_per_trade)^n
- Every output carries sample-count/evidence fields; prior-only posterior →
  honest wide distribution, never fabricated precision.

### 2.3 Utility integration (replaces info-gain primacy)

Extend `ActionObjectiveInputsV2` (schema bump `action_objective_inputs_v3`)
with per-action deltas vs the flat baseline of the SAME state:
`terminal_target_probability_delta` (finite, signed),
`terminal_log_growth_delta_nats` (finite, signed),
`terminal_downside_probability_delta` (nonneg).

Extend `LearnedObjectiveWeightsV2` (schema bump `learned_objective_weights_v3`)
with strictly-positive fitted weights:
`terminal_target_probability_reward`, `terminal_log_growth_reward`,
`terminal_downside_penalty`.

New utility (adaptive_objective_v2.py `_derive_score_values`):

```
utility = w_ttp·ΔP_target + w_tlg·Δlog_growth            # PRIMARY (horizon-aware)
        + w_ret·after_cost_return_bps                     # per-step anchor
        + w_ig·E[info_gain]                               # useful info acquisition (tertiary)
        − existing penalties (drawdown, tail, liq, impact, funding, turnover, concentration)
        − w_tdp·Δdownside_probability                     # terminal downside tail
```

Exploration eligibility (both evaluator and reference mirror): exploration
requires utility>0 AND (terminal-wealth contribution>0 OR
information_gain_contribution>0) — information alone remains admissible (it is
how the posterior that unlocks terminal estimation is bought), but it is no
longer the sole primary.

Bootstrap designation ranking (paper loop): primary key becomes
`terminal_wealth_contribution_per_expected_loss_usd` where the contribution
includes the LEARNED value-of-information term (w_ig·gain), i.e. the policy
prices information in terminal-wealth units instead of ranking on raw
nats-per-dollar. Selection-rule string updated; info-gain retained as the
recorded secondary evidence.

### 2.4 Online learning of all multipliers (no fixed knobs)

`_learned_weights` (calibration_v2.py:1137) is extended in the same
positive-projected-logistic family:
- three new coefficients fitted on matured-outcome features: realized per-trade
  log-equity contribution ln(1 + pnl/equity_at_entry), realized target-progress
  (log-distance closed toward target), realized downside excursion;
- data-derived scales exactly as the existing fitter (means/medians of rows);
- cadence + step-moment estimates fitted from current-epoch matured closes into
  a new `terminal_wealth_projection` calibration section (PIT windows, row
  digests, fingerprints — same evidence discipline as `learned_objective_weights`).
No fixed position percentages, leverage, trade counts, confidence cutoffs, or
frequency targets are introduced; horizon/target/multiple are objective
definitions, not allocation knobs.

### 2.5 Publication after every completed outcome

The calibration publisher (`v2_candidate_outcome_calibration_publisher.py`,
runs per outcome batch) additionally publishes
`v2:adaptive_system:terminal_wealth:status`:
schema `terminal_wealth_status_v1` — terminal_target_probability,
terminal-equity distribution quantiles, expected log-growth, downside/
liquidation probabilities, evidence (posterior buckets used, cadence sample
count, matured-close count, fit receipts), `target_guaranteed: false`,
paper_only/live-blocked flags. The paper loop attaches the per-cycle
projection to intents for Signal Explainability.

## 3. What does NOT change (preserved invariants)

- Hard-constraint validator, its Ed25519 receipts, and all seven canonical
  checks (accounting/reservation, authorization/paper-only, catastrophic-loss
  envelope, PIT data integrity, identity/lineage, position transitions, venue
  feasibility) — the objective still only ranks among already-hard-valid
  actions (`_derive_score_values` returns ineligible for hard-fail).
- Execution-causality authentication (typed action decision instant), fill
  throttles, duplicate suppression, session scoping, reservation conservation,
  mandatory-protection stops, liquidation guards.
- Asynchronous learning: posterior/maturation state has no authorization
  authority; closes maturing never block the next decision (existing design,
  paper loop :41473-41477 and shadow :2113-2119).
- Champion flat-baseline requirement; parity reference discipline; all
  paper_only/live-gate constants.

## 4. Schema/versioning & deployment

- Version STRING constants bump in place (class names keep V2 to avoid a
  62k-line rename): `adaptive_portfolio_objective_v3`,
  `action_objective_inputs_v3`, `action_objective_score_v3`,
  `learned_objective_weights_v3`, extended UNIT_CONTRACT; calibration artifact
  version bumps; `validate_candidate_outcome_calibration_v2` extended.
- Producer/consumer deploy order: calibration publisher restarts FIRST (writes
  the v3 artifact with new weight fields + terminal projection), then the
  paper loop. The shadow `_weights` reader stays fail-closed (strict KeyError →
  candidate blocked with evidence) during any skew window; current runtime is
  REMAIN_FLAT anyway (serving trust gate keystone, Codex v4 in flight).

## 5. Implementation phases

A. `terminal_wealth_v1.py` estimator + contracts + isolated unit tests.
B. Calibration fitter/validator/publisher: v3 weights, terminal_wealth_projection,
   status key publication + tests.
C. Objective contracts (inputs/weights/score/evaluation) + reference parity + tests.
D. Shadow service wiring (`_objective_action`, terminal state assembly, venue
   comparisons, selection) + runtime CLI + tests.
E. Paper loop: designation re-rank, intent projections, outcome-time publication
   + tests.
F. Full affected suites, adversarial review workflow, worklog, per-phase commits
   (explicit paths only — Codex has uncommitted files on this branch).
