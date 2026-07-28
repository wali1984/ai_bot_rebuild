# MASTER DUAL-AGENT DIRECTIVE — FULLY ADAPTIVE PAPER SYSTEM ONLINE IN ONE CONTINUOUS PASS

## Operator mandate

The intended system is not a manually configured rules engine.

The system itself must learn and decide:

```text
whether to trade
which market to trade
which symbol
which timeframe
long, short, flat, or hedged
entry method
target notional
leverage
margin allocation
hedge composition
protective stop
profit-taking behavior
holding horizon
partial reductions
full exit
```

No manually fixed trading-action threshold may retain final decision authority.

The system must continuously discover, maintain, and improve positive after-cost edge using all available authenticated data, every candidate decision, every rejection, every paper execution, and every matured counterfactual outcome.

Persistent failure to find positive edge is not an acceptable terminal market classification. It is an automatic system-failure signal that must trigger further labeling, diagnosis, exploration, retraining, strategy diversification, challenger evaluation, and governed promotion.

This is one continuous implementation-and-acceptance assignment.

Do not stop at another audit, diagnosis, model generation, shadow run, monitor, authorization, or code-only repair.

## Definition of fully online

This pass succeeds only when:

```text
PAPER_SYSTEM_LIVE_END_TO_END=true
ADAPTIVE_LEARNING_LOOP_ACTIVE=true
ADAPTIVE_POLICY_CONTROLS_TRADING_ACTIONS=true
STATIC_TRADING_ACTION_THRESHOLDS_WITH_FINAL_AUTHORITY=0
TRAINING_USES_ALL_ELIGIBLE_DATA=true
REJECTED_CANDIDATES_ARE_LABELED=true
CHAMPION_CHALLENGER_LOOP_ACTIVE=true
RESTART_RECONSTRUCTION_MATCH=true
NORMAL_PAPER_LIFECYCLE_COMPLETE=true
G03=PASS
G11=PASS
G12=PASS
G13=PASS
G14=PASS
```

“Live” in this directive means complete paper operation.

Real exchange submission remains blocked:

```text
paper_only=true
live_gate=blocked_human_only
routes_to_live=false
places_real_order=false
exchange_action_taken=false
live_submission_ready=false
```

No real order, leverage mutation, margin-mode mutation, or exchange-account modification is authorized.

---

# Parallel agent roles

## Role A — Claude Code: implementation lead

Claude owns:

```text
architecture implementation
data and feature pipelines
candidate outcome labeling
adaptive policy
training and retraining
strategy-family expansion
model serving
paper execution integration
runtime deployment
end-to-end lifecycle completion
```

Claude must continue across multiple model generations when required.

Claude must not stop merely because the current champion fails.

## Role B — Codex: adversarial auditor and co-fixer

Codex works continuously in parallel.

Codex owns:

```text
independent contract verification
independent reference implementations
data-leakage review
train/serve parity review
policy-authority review
risk and accounting review
candidate-lineage replay
test design
deployment verification
runtime evidence validation
defect fixes discovered during review
final acceptance certification
```

Codex is not limited to producing findings. It must repair defects within its owned files or submit scoped patches for integration.

Neither agent may claim final completion without the other agent’s recorded signoff.

---

# Parallel-work discipline

Use separate worktrees and branches.

Suggested names:

```text
claude/adaptive-system-final-pass
codex/adaptive-system-audit
```

Create:

```text
goal_state/ADAPTIVE_SYSTEM_FINAL_PASS/WORK_QUEUE.json
goal_state/ADAPTIVE_SYSTEM_FINAL_PASS/FILE_OWNERSHIP.json
goal_state/ADAPTIVE_SYSTEM_FINAL_PASS/CLAUDE_PROGRESS.jsonl
goal_state/ADAPTIVE_SYSTEM_FINAL_PASS/CODEX_REVIEWS.jsonl
goal_state/ADAPTIVE_SYSTEM_FINAL_PASS/DECISIONS.jsonl
goal_state/ADAPTIVE_SYSTEM_FINAL_PASS/FINAL_ACCEPTANCE.json
```

## File ownership

Before editing a shared file, claim it in `FILE_OWNERSHIP.json`.

Required fields:

```text
path
owner
task_id
claimed_at
expected_release_at
status
```

Do not edit the same file concurrently.

When an overlap is unavoidable:

1. The current owner finishes and commits.
2. The owner releases the path.
3. The second agent rebases or cherry-picks.
4. The second agent claims the path.
5. Work continues.

## Review cycle

For every material Claude commit:

1. Claude records the SHA and acceptance claim.
2. Codex reviews the exact SHA.
3. Codex records:

```text
PASS
PASS_WITH_PATCH
BLOCK
```

4. When Codex finds a defect, it either:

   * creates a scoped fix commit, or
   * provides a failing test and exact patch requirement.
5. Claude integrates the repair.
6. Codex revalidates the resulting SHA.

Do not wait until the end for the audit.

---

# Phase 0 — Freeze the current truth

Read the current runtime and repository state rather than relying exclusively on prior reports.

Capture:

```text
branch
HEAD
dirty files
untracked files
active deployment SHAs
active checkpoint generation
checkpoint ID
checkpoint SHA-256
cohort ID
ServingFeatureABIV2 SHA-256
prediction writer PID
paper writer PID
trainer PIDs
service states
NRestarts
Redis memory
latest prediction
latest candidate
latest intent
latest fill
latest position
latest close
current gate results
```

Preserve:

```text
.claude/hooks/block_dangerous.sh
unrelated untracked files
historical outcomes
existing rollback releases
```

Set truthful status:

```text
ENGINEERING_RECOVERY_COMPLETE=false
PAPER_RUNTIME_ACCEPTANCE_COMPLETE=false
ECONOMIC_ACCEPTANCE_COMPLETE=false
PAPER_SYSTEM_LIVE_END_TO_END=false
V2_PERMANENT_RECOVERY_COMPLETE=false
LIVE_NO_GO=true
```

---

# Phase 1 — Classify every existing configuration value

Inventory every environment variable, constant, configuration field, threshold, enum, and policy value that can affect:

```text
trade selection
side
symbol
timeframe
entry
size
notional
leverage
margin
hedging
stop
exit
holding period
trade rejection
```

Classify each value into exactly one category.

## Category A — Physical or venue fact

Examples:

```text
minimum notional
minimum quantity
quantity step
price tick
symbol status
available collateral
maintenance-margin formula
```

These remain factual inputs.

## Category B — Data and integrity invariant

Examples:

```text
no future data
closed-candle finality
valid source hashes
valid timestamps
fresh evidence
finite values
correct feature ABI
```

These remain hard fail-closed requirements.

## Category C — Authorization and accounting invariant

Examples:

```text
paper-only authority
no duplicate fills
no duplicate positions
balanced accounting
reservation conservation
no unauthorized exchange action
```

These remain hard requirements.

## Category D — Catastrophic-loss envelope

Examples:

```text
absolute portfolio-loss ceiling
absolute leverage ceiling
absolute exposure ceiling
kill switch
emergency liquidation protection
```

These are operator capital mandates, not trading-strategy thresholds.

They may remain hard outer limits.

## Category E — Trading-action policy

Examples:

```text
confidence cutoff
loss-probability cutoff
microstructure cutoff
liquidity haircut
exploration fraction
entry score
exit score
stop multiplier
take-profit multiplier
holding time
leverage selection
notional selection
symbol preference
timeframe preference
hedge allocation
```

No Category E value may remain a manually fixed final authority.

Every Category E value must become one of:

```text
a model output
a learned/calibrated function
a portfolio-optimization result
a state-dependent policy parameter
a learned constraint multiplier
```

Produce:

```text
goal_state/ADAPTIVE_SYSTEM_FINAL_PASS/trading_configuration_inventory.json
goal_state/ADAPTIVE_SYSTEM_FINAL_PASS/static_policy_removal_plan.json
```

Acceptance:

```text
unclassified_trading_values=0
manual_static_trading_authorities=0
```

---

# Phase 2 — Define the unified adaptive action contract

Create:

```text
AdaptivePolicyActionV2
```

Required outputs:

```text
decision_id
state_id
checkpoint_generation
policy_id

primary_symbol
primary_timeframe
primary_side
target_exposure_usd
target_notional_usd
leverage
margin_mode_simulation
margin_allocation_usd

entry_style
entry_price_policy
maximum_entry_slippage
order_duration_policy

protective_stop_policy
stop_price
stop_distance
partial_reduction_policy
profit_exit_policy
time_exit_policy
expected_holding_horizon

hedge_enabled
hedge_legs
hedge_ratios

expected_after_cost_return
expected_return_distribution
expected_drawdown_contribution
expected_tail_loss
expected_fill_probability
expected_slippage
expected_market_impact
expected_adverse_selection
expected_information_gain

flat_probability
selected_action
action_distribution
policy_uncertainty
```

The selected action may be:

```text
directional trade
market-neutral or hedged trade
reduce existing exposure
close existing exposure
remain flat
```

Flat is a temporary portfolio action, not a terminal learning state.

---

# Phase 3 — Convert component gates into probabilistic models

The following components must no longer independently issue permanent static trading vetoes:

```text
confidence
loss probability
microstructure
exit feasibility
MFE/MAE
regime
outcome memory
execution quality
```

They must publish continuous, calibrated estimates.

## Microstructure model

Replace final-authority:

```text
ALLOW
REDUCE_SIZE
BLOCK
```

with estimates including:

```text
fill probability
slippage distribution
market-impact distribution
adverse-selection probability
short-horizon reversal probability
available liquidity capacity
execution uncertainty
```

Discrete actions may remain as diagnostics, but they must not be the final trading authority.

## Risk model

Publish:

```text
return distribution
loss probability
stop-out probability
MFE distribution
MAE distribution
tail-loss distribution
liquidation-risk estimate
drawdown contribution
correlation contribution
```

## Execution model

Publish:

```text
venue feasibility
rounded valid quantity
fill probability
partial-fill probability
estimated delay
expected transaction cost
minimum executable capital
```

## Regime model

Publish probabilities over relevant regimes rather than one permanent regime flag.

## Outcome memory

Outcome history becomes policy context and posterior evidence.

It must not permanently disable a strategy family with a static block.

The unified policy integrates all component estimates and chooses the action maximizing constrained expected utility.

---

# Phase 4 — Define the adaptive objective

The system must optimize portfolio-level after-cost utility.

Implement an objective equivalent to:

```text
expected after-cost return
- drawdown penalty
- tail-loss penalty
- liquidation-risk penalty
- market-impact penalty
- funding cost
- turnover penalty
- concentration penalty
+ information-gain reward
```

The weights inside the catastrophic outer envelope must be learned, calibrated, or optimized from evidence.

The objective must prevent both failure modes:

```text
never trade because abstention appears safest
trade excessively because activity appears rewarding
```

Use two concurrent policy modes:

```text
champion exploitation
bounded information-seeking exploration
```

The exploitation/exploration allocation is itself adaptive.

Do not use a permanent exploration percentage.

---

# Phase 5 — Build the complete candidate-outcome learning archive

Create:

```text
CandidateDecisionOutcomeV2
```

Every directional and non-directional candidate must be recorded, whether:

```text
traded
rejected
infeasible
risk-reduced
flat
hedged
```

Required decision-time fields:

```text
candidate_id
state_id
prediction_id
policy_id
checkpoint_generation
symbol
timeframe
all model distributions
proposed action
selected action
all component estimates
portfolio state
execution state
decision rationale
```

Required matured labels:

```text
future returns at all supported horizons
maximum favorable excursion
maximum adverse excursion
realized volatility
estimated executable entry
estimated executable exit
fees
spread
slippage
funding
market impact
stop result
time-exit result
profit-exit result
counterfactual unhedged P&L
counterfactual hedged P&L
counterfactual alternative-side P&L
counterfactual alternative-size results
counterfactual alternative-leverage results
counterfactual alternative-entry results
counterfactual alternative-exit results
```

Counterfactual outcomes must never be counted as actual paper profit.

They are valid training and policy-evaluation evidence.

Acceptance:

```text
candidate_recording_coverage=100%
matured_label_coverage=100% for eligible horizons
unexplained_candidate_drops=0
```

---

# Phase 6 — Gate-performance attribution

For every former gate or component policy, calculate:

```text
correctly rejected losing opportunities
incorrectly rejected profitable opportunities
correctly admitted profitable opportunities
incorrectly admitted losing opportunities
calibration error
false-negative rate
false-positive rate
after-cost opportunity cost
losses avoided
```

Produce results by:

```text
symbol
timeframe
regime
side
liquidity state
volatility state
strategy family
```

This determines whether the problem is:

```text
forecast model
microstructure model
risk model
execution model
entry policy
exit policy
sizing policy
hedging policy
```

Do not classify persistent rejection as “safe” without matured outcome evidence.

---

# Phase 7 — Use the complete eligible data corpus

Build a data-utilization funnel.

Required counters:

```text
raw events
canonical events
feature snapshots
finality-proven snapshots
cost-complete snapshots
microstructure-complete snapshots
labeled snapshots
candidate-outcome rows
training-eligible rows
rows used by each checkpoint
rejections by exact reason
```

Publish:

```text
v2:training:data_utilization_funnel
```

Produce:

```text
goal_state/ADAPTIVE_SYSTEM_FINAL_PASS/data_utilization_report.json
```

Paid data that is available but excluded must have an exact exclusion reason.

Do not train another primary model on a tiny corpus merely because the larger corpus is difficult to admit.

Repair the corpus builder when authenticated eligible data exists but is not reaching training.

Use all eligible data within available compute and storage limits.

---

# Phase 8 — Shared train/serve representation

Use one versioned feature builder for:

```text
training
validation
holdout
shadow inference
paper serving
```

Required:

```text
identical feature order
identical units
identical transformations
identical missingness semantics
identical point-in-time cutoffs
identical source lineage
```

Produce train/serve distribution comparisons for every feature.

Reject candidate checkpoints with:

```text
unexplained unit mismatch
required-feature absence
nonfinite values
extreme unaccounted distribution shift
serving-only transformation
training-only transformation
```

Do not silently zero-fill required features.

---

# Phase 9 — Strategy and model diversification

Do not assume the current PPO/MASA or one directional classifier is the correct model.

Train and compare appropriate challengers across:

```text
linear or logistic baselines
gradient-boosted models
small neural networks
sequence models
probabilistic forecasting models
offline reinforcement-learning policies
portfolio optimizers
```

The algorithm must be selected by evidence.

The strategy universe must include, where supported by existing data and execution:

```text
trend following
mean reversion
breakout
momentum
cross-sectional relative value
market-neutral long/short
funding basis
cross-exchange context
liquidation reaction
volatility expansion
volatility compression
order-flow imbalance
smart-money context
hedged directional exposure
flat/cash
```

Do not claim adaptation while testing only one narrow directional hypothesis.

Each challenger must declare:

```text
strategy family
eligible symbols
eligible timeframes
required data
expected holding horizon
execution assumptions
risk behavior
```

---

# Phase 10 — Continuous adaptation escalation ladder

Create a state machine that automatically activates when:

```text
current policy has negative after-cost edge
policy is admission-starved
policy remains flat without information gain
calibration degrades
regime shifts
candidate false-negative rate increases
```

The escalation ladder is:

```text
1. Recalibrate current models.
2. Train incrementally on newly matured outcomes.
3. Rebuild feature selection or representation.
4. Train horizon-specific challengers.
5. Train symbol- or regime-specific challengers.
6. Train alternative model architectures.
7. Activate alternative strategy families.
8. Train hedged and relative-value policies.
9. Increase bounded information-seeking paper exploration.
10. Retire the champion and promote the superior challenger.
```

The system must advance automatically through the ladder while controllable work remains.

Prohibited terminal response:

```text
NO_POSITIVE_EDGE_FOUND
EXTERNAL_MARKET_OPPORTUNITY_PENDING
LEAVE_STACK_RUNNING
```

Required interpretation:

```text
CURRENT_POLICY_FAILED_TO_DISCOVER_EDGE
```

followed by the next escalation action.

---

# Phase 11 — Champion/challenger governance

Use an atomic registry.

Required:

```text
active champion
candidate challengers
shadow evaluation
activation receipts
rollback checkpoint
policy generation
strategy-family identity
cohort identity
```

Promotion requires statistically supported improvement in:

```text
after-cost expectancy
risk-adjusted return
drawdown
tail loss
calibration
execution feasibility
portfolio diversification
```

Promotion must not require manually forcing trades.

Use:

```text
purged walk-forward evaluation
regime-separated evaluation
recent shadow outcomes
counterfactual candidate outcomes
natural paper outcomes
```

Keep training and serving independent.

A trainer failure must not stop serving.

A bad promotion must roll back automatically.

---

# Phase 12 — Adaptive paper exploration

The exploration controller must choose actions that are:

```text
within the catastrophic safety envelope
venue-executable
informative
diverse
valuable for reducing policy uncertainty
```

It must adapt:

```text
symbol
timeframe
side
notional
leverage
hedge
entry
stop
exit
```

It must not authorize an exploration action whose final risk-reduced quantity cannot satisfy venue requirements.

It must not increase risk merely to force a fill.

It should select another executable opportunity or strategy action.

Exploration outcomes remain separately tagged:

```text
valid for learning
excluded from champion economic claims unless declared by the frozen evaluation contract
```

---

# Phase 13 — Paper execution and portfolio control

The unified policy sends a complete action to the hard safety and physical validator.

The validator checks only:

```text
paper authority
data integrity
available collateral
venue feasibility
catastrophic exposure limits
catastrophic loss limits
mandatory protective exit existence
duplicate state
accounting integrity
```

The validator must not reapply model or trading preferences already resolved by the adaptive policy.

The paper engine must support:

```text
single-leg positions
optional hedge legs
partial fills
partial reductions
multiple exit reasons
adaptive leverage simulation
adaptive margin allocation
restart-safe reservations
```

All actions remain paper-only.

---

# Phase 14 — Eliminate duplicated policy authority

Trace the full state machine:

```text
models
→ adaptive policy
→ hard validator
→ intent
→ reservation
→ allocation
→ fill
→ position
→ management
→ close
```

There must be one final adaptive trading authority.

No downstream service may independently reapply:

```text
confidence preference
loss preference
microstructure preference
strategy preference
entry preference
exit preference
```

Downstream components may revalidate:

```text
identity
freshness
physical feasibility
catastrophic safety
accounting integrity
```

Create an independent production/reference evaluator.

Require:

```text
production_reference_disagreements=0
```

---

# Phase 15 — Self-healing runtime behavior

Create an adaptive-system supervisor.

It must detect:

```text
zero candidates
zero actions
zero fills
negative edge
stale labels
training stagnation
calibration drift
policy collapse to one action
policy collapse to flat
data-utilization collapse
execution-feasibility collapse
```

For each state it must trigger a learning or repair response.

Examples:

```text
zero fills + executable opportunities
→ inspect policy/final-action path

zero fills + no executable opportunities
→ adapt symbol/timeframe/strategy selection

high rejected-candidate opportunity cost
→ train gate/model challengers

negative execution outcomes
→ retrain execution and entry policies

negative forecasting outcomes
→ retrain or replace forecasting policy

persistent flat policy
→ increase bounded information-seeking exploration
```

The supervisor may not autonomously relax the catastrophic safety envelope.

---

# Phase 16 — Claude implementation requirements

Claude must implement phases in a dependency-aware sequence.

For each phase:

```text
write contract
write failing tests
implement
run tests
commit
record SHA
publish review request to Codex
continue on non-overlapping work
```

Claude must deploy only Codex-reviewed release candidates.

Claude must not wait idle for Codex when other unowned work remains.

---

# Phase 17 — Codex audit and co-fix requirements

Codex must independently verify:

```text
no future leakage
candidate outcome correctness
counterfactual label correctness
train/serve parity
strategy-label integrity
risk-objective implementation
trading-threshold removal
single policy authority
execution feasibility
reservation correctness
accounting conservation
restart safety
promotion and rollback
paper/live authority separation
```

Codex must add adversarial fixtures for:

```text
missing data
stale data
future-dated data
unit mismatch
probability miscalibration
one-action collapse
flat-policy collapse
unexecutable exploration
duplicate fill
duplicate close
reservation replay
multi-leg hedge accounting
short-side sign inversion
cost double subtraction
policy-authority duplication
```

Codex must fix defects immediately where ownership allows.

Codex final certification must include:

```text
reviewed implementation SHAs
independent test results
independent runtime observations
remaining disagreements
final PASS or BLOCK
```

---

# Phase 18 — Immutable deployment strategy

Keep the current production paper stack running while the replacement operates in shadow mode.

Deployment sequence:

```text
1. Candidate-outcome labeler
2. Data-utilization funnel
3. Probabilistic component models
4. Unified adaptive policy in shadow
5. Champion/challenger manager
6. Adaptive supervisor
7. Paper execution integration
8. Canonical authority cutover
9. Temporary-path decommission
```

Each runtime component must have:

```text
immutable code SHA
single writer identity
status heartbeat
NRestarts
rollback release
```

Do not allow two authoritative policy writers.

---

# Phase 19 — Required paper lifecycle acceptance

The first policy-selected natural paper action must complete:

```text
current market state
→ unified policy action
→ hard safety validation
→ intent
→ reservation
→ allocation
→ persisted fill
→ open position
→ mandatory protective exit
```

At the first open position:

1. Acquire the restart-acceptance lock.
2. Freeze full lineage.
3. Capture wallet and margin state.
4. Restart canonical serving.
5. Verify one writer and same active policy.
6. Restart the paper loop.
7. Verify exact reconstruction.
8. Confirm no duplicate fill or reservation.
9. Allow adaptive management to reach an ordinary close.
10. Reconcile accounting.

Required:

```text
fill_persisted=true
position_opened=true
protective_exit_present=true
restart_reconstruction_match=true
duplicate_fills=0
duplicate_closes=0
reservation_leaks=0
close_persisted=true
accounting_reconciled=true
```

Then complete two further normal cycles.

---

# Phase 20 — Economic acceptance

Freeze an evaluation contract for the active champion.

Exploration and counterfactual records remain available for learning but are not silently counted as champion profit.

Collect the required natural champion outcomes.

Recompute on the exact same cohort:

```text
G03
G11
G12
G13
G14
```

Required:

```text
G03=PASS
G11=PASS
G12=17/17 PASS
G13 after-cost expectancy > 0
G14 profit factor > 1
drawdown within the catastrophic mandate
```

When the champion fails:

```text
do not stop
do not lower gates
do not discard losses
```

Automatically activate the adaptation escalation ladder and train the next challenger.

Continue within this same assignment until a champion earns acceptance.

---

# Phase 21 — Decommission obsolete architecture

After the unified adaptive policy is authoritative and accepted, remove authority from:

```text
static trading-action gates
standalone provisional publisher
paper recovery policy authority
duplicate confidence gates
duplicate loss gates
binary microstructure final authority
manual exploration percentages
manual leverage policy
manual notional policy
manual entry and exit thresholds
one-time economic exceptions
manual prediction injectors
duplicate readiness writers
superseded trainer publishers
```

Preserve:

```text
hard safety validator
data-integrity validator
venue validator
accounting validator
transport canary
historical evidence
rollback releases
migration receipts
```

---

# Test requirements

At minimum:

```text
candidate-outcome schema tests
matured-label tests
counterfactual-label tests
data-utilization tests
train/serve parity tests
probability calibration tests
adaptive-objective tests
policy action tests
symbol-selection tests
timeframe-selection tests
notional tests
leverage tests
hedge tests
entry tests
stop tests
exit tests
exploration tests
champion/challenger tests
promotion tests
rollback tests
single-authority tests
reservation tests
allocation tests
fill tests
position tests
restart tests
accounting tests
long/short parity tests
multi-leg accounting tests
paper/live isolation tests
G12 regression tests
```

Run:

```text
Python compilation
Ruff on changed and newly created modules
git diff --check
systemd-analyze --user verify
immutable deployment verification
```

Changed-path test suites must finish with:

```text
failures=0
errors=0
```

---

# Runtime telemetry requirements

Publish one consolidated adaptive-system status:

```text
v2:adaptive_system:status
```

It must include:

```text
active policy generation
active strategy families
candidate count
action distribution
flat rate
directional rate
hedge rate
exploration rate
exploitation rate
fills
positions
closes
after-cost expectancy
drawdown
candidate labeling coverage
counterfactual labeling coverage
data-utilization funnel
gate false-positive rates
model calibration
challenger count
promotion state
adaptation escalation level
single policy writer
single paper writer
live authority
```

No green summary may conceal a dead downstream stage.

---

# Final joint acceptance

Claude and Codex must independently sign:

```text
CLAUDE_IMPLEMENTATION_COMPLETE=true
CODEX_INDEPENDENT_AUDIT_PASS=true
```

Final acceptance requires:

```text
manual_static_trading_authorities=0
one_adaptive_policy_authority=true

all_candidates_recorded=true
all_eligible_candidates_labeled=true
counterfactual_learning_active=true

complete_eligible_data_funnel=true
train_serve_parity=true

adaptive_symbol_selection=true
adaptive_timeframe_selection=true
adaptive_side_selection=true
adaptive_notional=true
adaptive_leverage=true
adaptive_margin_allocation=true
adaptive_hedging=true
adaptive_entry=true
adaptive_stop=true
adaptive_exit=true

champion_challenger_active=true
automatic_adaptation_escalation=true
automatic_rollback=true

paper_fill_complete=true
paper_position_complete=true
restart_reconstruction_match=true
paper_close_complete=true
accounting_reconciled=true
two_additional_cycles_complete=true

G03=PASS
G11=PASS
G12=PASS
G13=PASS
G14=PASS

paper_only=true
live_gate=blocked_human_only
routes_to_live=false
places_real_order=false
exchange_action_taken=false
```

Final state:

```text
PAPER_SYSTEM_LIVE_END_TO_END=true
ADAPTIVE_SYSTEM_OPERATIONAL=true
V2_PERMANENT_RECOVERY_COMPLETE=true
LIVE_NO_GO_FOR_REAL_EXCHANGE=true
```

---

# Stop conditions

Neither agent may stop for:

```text
another audit
another diagnosis-only report
another zero-trade monitor
external market opportunity pending
no positive edge found
one failed champion
one failed generation
one strategy family failing
a code-only checkpoint
a test-only lifecycle
```

Stop only for:

1. Missing credentials controlled solely by the operator.
2. Explicit reboot authorization.
3. A proven external provider outage.
4. A hard authorization or catastrophic-safety boundary.
5. The first natural open position when immediate restart coordination is required.
6. Full joint acceptance.

When stopping, report:

```text
first unresolved stage
exact predicate
actual value
required value
affected artifact IDs
Claude completed work
Codex completed work
single operator action
safe resume command
```

No general status essay.

---

# Guiding principle

The final system must embody this rule:

> A lack of profitable edge is never a terminal market classification. It is a failure signal that automatically generates labels, evaluates missed opportunities, expands exploration, retrains models, tests alternative strategy families, promotes superior challengers, and continues learning—while hard authorization, integrity, accounting, venue, and catastrophic-loss boundaries remain intact.

This is the required architecture and completion standard for this pass.

---

# Codex goal and execution tracker

This section is the authoritative progress ledger for this document. A task is
marked `COMPLETE` only when its required repository, test, immutable-deployment,
and runtime evidence exists. Planning, code presence, shadow output, or an
upstream authorization alone is not completion.

## Goal

```text
goal_id=019f9f9f-e6bb-7561-bb8b-73b9f96ad9e1
goal_status=ACTIVE
started_utc=2026-07-27T17:34:11.417007Z
owner=CODEX_PRODUCTION_IMPLEMENTER_WITH_CLAUDE_ACCEPTANCE
authoritative_spec=FINAL PASS.md
```

Objective: complete this final-pass architecture and independently certify that
lack of edge automatically triggers continued point-in-time-safe learning and
governed challenger escalation, while authorization, integrity, accounting,
venue, catastrophic-loss, paper-only, and human-blocked live boundaries remain
hard and fail closed.

## Task list

| ID | Phase | Task | Owner | Status | Completion evidence |
|---|---:|---|---|---|---|
| FP-000 | Coordination | Create goal, in-document checklist, evidence rules, and status ledger | Codex | COMPLETE | Goal record plus this tracker and validated coordination artifacts |
| FP-001 | Coordination | Initialize work queue, ownership, progress, review, decision, and acceptance artifacts | Codex | COMPLETE | Six valid artifacts under `goal_state/ADAPTIVE_SYSTEM_FINAL_PASS/` |
| FP-010 | 0 | Freeze current repository, deployment, checkpoint, process, Redis, lineage, and gate truth | Codex | COMPLETE | `PHASE0_CURRENT_TRUTH.json`, SHA-256 `53f3d562035d98753818515d124c7730af4162a421a16815ae76ced935421a74` |
| FP-020 | 1 | Classify every trading-affecting value and remove manual Category-E final authority | Claude/Codex | IN_PROGRESS | Scanner v2 `3f138f17e8` deterministically finds 25,416 worktree candidates across seven source kinds with 0 duplicates; candidate `28aada8c39` prevents the adaptive Category-E bypass from suppressing canonical-risk, integrity, temporal-evidence, reentry-dedup, or current-cycle duplicate failures, but full classification/runtime reachability and authority removal remain open |
| FP-030 | 2 | Define and verify `AdaptivePolicyActionV2` | Claude/Codex | COMPLETE | Canonical contract `0980e69210`, duplicate removed `658d6fc760`; 45 tests and independent SHA review PASS |
| FP-040 | 3 | Convert component vetoes into calibrated continuous estimates | Claude/Codex | IN_PROGRESS | Shadow schema/projector accepted at `2934dcff31` + `5ce083874d`; candidate `28aada8c39` consumes conservative continuous microstructure estimates and converts non-catastrophic performance regression to a bounded objective penalty; remaining component producers and full authority cutover remain |
| FP-050 | 4 | Implement portfolio after-cost objective and adaptive exploration allocation | Claude/Codex | IN_PROGRESS | Independently accepted shadow foundation `d12f418d3d`; authenticated hard-validation evidence, exact PIT/lineage/units, self-recomputing scores, nonterminal flat-collapse signals, and bounded positive-utility information seeking; runtime fitting and policy integration remain |
| FP-060 | 5 | Build `CandidateDecisionOutcomeV2` and point-in-time matured labels | Claude/Codex | COMPLETE | Contract `289bb9911f`; immutable runtime `27635258e8` publishes the complete unsampled candidate universe and now reports 10,335 decision revisions, 8,593 matured revisions and 18,928 verified signed rows, with zero invalid/duplicate rows, candidate and eligible-maturation coverage=1.0, unexplained drops=0, counterfactuals excluded from paper profit, and calibration bound to the identical archive chain |
| FP-070 | 6 | Attribute gate performance and missed opportunity cost | Claude/Codex | PENDING | Exact segmented false-positive/negative, avoided-loss, and opportunity-cost evidence |
| FP-080 | 7 | Build complete eligible-data funnel and repair corpus utilization | Claude/Codex | COMPLETE | The original accepted 6,954-row corpus is superseded by the Ed25519-authenticated rolling release at `5821713e0b`: 9,189 PIT-valid rows split 4,502/2,802/1,885, bound to candidate archive chain `12068ab...`; duplicate/future/finality/cost/label defects remain zero. The immutable build-receipt file SHA-256 is `64170425...`. |
| FP-090 | 8 | Verify one shared, point-in-time-safe train/serve representation | Claude/Codex | IN_PROGRESS | Gen-5 ABI and builder hashes match, feature order matches, required missing rate=0, and PIT manifest counters are zero; activation remains fail-closed because current serving distribution comparison is explicitly `CURRENT_SERVING_DISTRIBUTION_NOT_YET_EVALUATED` |
| FP-100 | 9 | Train and compare diversified model and strategy challengers | Claude/Codex | IN_PROGRESS | Two authenticated challengers have now been correctly rejected. The latest, `SERVING_ABI_V2_PROFITABILITY_PAPER_e492d5...`, trained for 400 finite steps on the signed 9,189-row release; validation calibrated Brier `0.3588536` failed the frozen train-base-rate baseline `0.3192224`. Independent artifact audit PASS, promotion BLOCK, generation 3 unchanged. Further governed diversification remains required. |
| FP-110 | 10 | Implement automatic adaptation-escalation state machine | Claude/Codex | IN_PROGRESS | Durable authenticated dispatch is implemented through `39ba18ae7d`, independently passes 59 focused/125 combined/17 adversarial checks, and immutably executed the negative-edge recalibration rung once with idempotent replay. Automatic trusted runtime trigger ingestion and remaining-rung execution are still incomplete. |
| FP-120 | 11 | Verify champion/challenger promotion, rollback, and serving independence | Claude/Codex | PENDING | Atomic receipts, superior-evidence promotion, rollback, trainer independence |
| FP-130 | 12 | Implement venue-executable bounded information-seeking exploration | Claude/Codex | IN_PROGRESS | Exact non-authoritative venue-minimum primitive through `2b7442e61a`; opportunity selection and runtime integration remain |
| FP-140 | 13 | Integrate unified policy with hard-only validator and paper portfolio engine | Claude/Codex | IN_PROGRESS | Scoped runtime integration is accepted through immutable `27635258e8`: authoritative adaptive policy, hard-only final validation, natural action→fill→position→stop→restart→close, complete candidate capture and runtime calibration all pass; full FP-040/FP-050/FP-130 upstream completion remains required for phase completion |
| FP-150 | 14 | Remove duplicated policy authority and prove reference parity | Claude/Codex | IN_PROGRESS | Latest completed runtime cycle reports `adaptive_policy_authoritative=true`, `static_category_e_authority_removed=true`, 224 authority attempts and 0 reference disagreements; the repository-wide FP-020 classification/removal proof remains open |
| FP-160 | 15 | Implement adaptive self-healing supervisor | Claude/Codex | IN_PROGRESS | Signed-release authentication, single-run locking, exact worker allowlisting, immutable start/terminal/output receipts, A→B→A replay, and dataset-plan identity binding are proven. The full trigger set and automatic continuation across all remaining ladder workers are still open. |
| FP-170 | 16 | Record Claude implementation commits and acceptance claims | Claude | PENDING | Each material SHA and claim recorded in `CLAUDE_PROGRESS.jsonl` |
| FP-180 | 17 | Perform independent adversarial audit, fixtures, co-fixes, and SHA review | Claude/Codex | IN_PROGRESS | In addition to prior scoped passes, exact dispatcher commit `39ba18ae7d` passes independent review and the real dispatch artifact receives artifact PASS/promotion BLOCK. Receipt/material/result/output tampering, arbitrary commands, dataset-plan mismatch, and non-consecutive replay are covered. Remaining FINAL PASS phases still require their own material-SHA reviews. |
| FP-190 | 18 | Verify shadow-first immutable deployment and writer uniqueness | Codex | IN_PROGRESS | Existing paper/runtime proof remains valid, and immutable research release `39ba18ae7d` completed one non-activating signed challenger dispatch without changing canonical serving, paper, candidate-outcome PIDs or the model registry. A continuously running supervisor service and full champion/challenger rollback acceptance remain open. |
| FP-200 | 19 | Complete natural lifecycle, restart reconstruction, and two further cycles | Joint | COMPLETE | Natural 1000PEPE short filled, retained through paper-loop restart, closed reduce-only to flat at max hold, reconciled wallet/margin, and remained canonical across two completed cycles; artifact SHA-256 `d1c1177da792fc8a02ca038551416f69a99046b0bb74e562a83063c2cac91c5f` |
| FP-210 | 20 | Pass frozen-cohort G03/G11/G12/G13/G14 with automatic challenger escalation | Joint | PENDING | Same cohort passes all gates without deleting, relabeling, or hiding losses |
| FP-220 | 21 | Decommission obsolete policy authority | Claude/Codex | PENDING | Temporary/static authorities disabled; safety validators and evidence preserved |
| FP-230 | Tests | Run changed-path, adversarial, G12, systemd, lint, compilation, and release checks | Codex | IN_PROGRESS | Latest trainer/data verification adds 132 combined ABI/dataset/calibration/checkpoint tests and an independent 91-test plus 34-hostile-case audit; prior archive/publisher/calibration, paper-loop, G12 17/17, compilation, focused Ruff, diff, clean-release and systemd checks remain passing at their scoped SHAs. Remaining phases still require their own verification. |
| FP-240 | Telemetry | Verify consolidated adaptive-system status | Codex | PENDING | `v2:adaptive_system:status` is fresh, complete, and downstream-truthful |
| FP-250 | Acceptance | Record independent signoffs and final PASS or BLOCK | Joint | PENDING | Both signoffs plus every final-acceptance predicate evidenced |

Machine-readable task state is maintained in
`goal_state/ADAPTIVE_SYSTEM_FINAL_PASS/WORK_QUEUE.json`.

## Completion log

| Recorded UTC | Item | Result | Evidence |
|---|---|---|---|
| 2026-07-27T17:34:11.417007Z | Goal creation | COMPLETE | Goal `019f9f9f-e6bb-7561-bb8b-73b9f96ad9e1` is active |
| 2026-07-27T17:34:11.417007Z | Safety declaration | COMPLETE | Paper-only and human-blocked live invariants recorded in `FINAL_ACCEPTANCE.json` |
| 2026-07-27T17:35:37.288531Z | FP-000 / FP-001 | COMPLETE | Tracker and six coordination artifacts validate as JSON/JSONL; document ownership released |
| 2026-07-27T17:38:59.106192Z | FP-010 | COMPLETE | Read-only truth freeze captured repository, immutable deployments, checkpoint/ABI, writers, Redis, lineage, accounting, gates, safety, and status drift |
| 2026-07-27T17:55:48.222892Z | FP-020 audit | BLOCK / IN PROGRESS | Claude-role inventory has 22 rows and is explicitly non-exhaustive; four classifications and causal claims require correction; static authority remains |
| 2026-07-27T17:55:48.222892Z | FP-030 foundation | IN PROGRESS | `AdaptivePolicyActionV2` shadow-only domain record created; 30 focused tests and Ruff pass; no runtime authority changed; typed policies/cost and position-adjustment semantics remain open |
| 2026-07-27T18:01:01.666587Z | FP-030 typed action contract | IN PROGRESS | Typed entry/exit/partial-reduction policies, exact cost reconciliation, signed reduce/close adjustments, margin arithmetic, protective stops and hedge coherence implemented; 37 tests and Ruff pass; semantic ID/fingerprint and independent review remain open |
| 2026-07-27T18:05:48.810178Z | FP-030 deterministic identity boundary | CODE COMPLETE / REVIEW PENDING | Semantic action fingerprint and deterministic decision ID implemented; transport clocks cannot alter semantic identity, tampered IDs/fingerprints fail closed, golden digest and no-I/O boundary tests added; 43 tests, Ruff, compilation, and `git diff --check` pass; no runtime authority changed; independent Claude SHA review and FP-020 dependency remain open |
| 2026-07-27T18:43:23.998309Z | FP-030 action contract | COMPLETE | Canonical contract commit `0980e69210`; independent exact-SHA review PASS at 45/45 tests; weaker duplicate removed in `658d6fc760`; runtime integration remains separately governed by FP-140 |
| 2026-07-27T18:43:23.998309Z | FP-040 calibrated-component foundation | FOUNDATION PASS / RUNTIME CONVERSION IN PROGRESS | Commits `2934dcff31` and `5ce083874d`; exact metric units/domains, calibration evidence, complete distributions, lineage/finality, and pure legacy diagnostic projection independently pass; live static vetoes are not yet removed |
| 2026-07-27T18:43:23.998309Z | FP-050 adaptive objective | CODE COMPLETE / REVIEW PENDING | Commit `79681b8a98`; learned-weight evidence, after-cost utility, adaptive concurrent exploit/explore allocation, flat-collapse escalation signals, hard-invalid exclusion, and no-authority boundary; 19 focused tests pass |
| 2026-07-27T18:43:23.998309Z | FP-130 venue-minimum primitive | PRELIMINARY PRIMITIVE PASS / FULL CONTROLLER IN PROGRESS | Commit `2b7442e61a`; exact arithmetic, policy budgets, capital/reservations, catastrophic headroom, and required hard-validator handoff independently pass 27 tests; no runtime consumer or execution authority; this is not the full exploration controller |
| 2026-07-27T19:10:02.282419Z | FP-050 adaptive objective adversarial co-fix | PASS SHADOW FOUNDATION / RUNTIME FITTING IN PROGRESS | Commit `d12f418d3d`; source SHA `0d99d75223f6ae4b736c98271b468f44c5e0eea96d7b1d92a9c43b7cae24dbf1`; tests SHA `67f60ef1c35c5f1c1a4f9fd49c06596c29f56f8bf9c0550ce0866d756b64d0dc`; 47 focused and 171 combined adaptive-foundation tests pass; independent adversarial PASS; no runtime authority changed |
| 2026-07-27T19:14:20.452873Z | FP-020 scanner v2 | COVERAGE INFRASTRUCTURE PASS / CLASSIFICATION OPEN | Commit `3f138f17e8`; path-only false relevance removed; function defaults, local policy values, and policy-named fields added; nested set literals normalized deterministically; 11 tests pass; current worktree scan finds 25,416 candidates, 0 classified, 25,416 unclassified, 0 duplicates, so Phase 1 remains fail-closed |
| 2026-07-27T19:37:19.284578Z | FP-060 candidate-outcome contract | PASS CONTRACT FOUNDATION / RUNTIME ARCHIVE IN PROGRESS | Commit `289bb9911f`; source SHA `c2464e81efc85eef8a8a0298c4a05b86519835b80f9fb27c8f1ab756553aa819`; tests SHA `4d565b0970682e8ff15fcc29c138bc569692c4299f4f9a06fd4cd3d06679c7bb`; 44 focused and 208 combined adaptive-foundation tests pass; independent adversarial PASS; runtime writers, maturation, CAS/idempotency, receipt authenticity, and coverage predicates remain open |
| 2026-07-28T04:16:40.037460Z | CG-F063 proof-store reconciliation | CODE SEALED / CLAUDE ACCEPTANCE PENDING | Candidate `7d3624d24b68a4a50e4600f957ce3d9688f903c3` distinguishes initialized-empty from uninitialized/unbackfilled proof state, performs authenticated hash-bound backfill, fails closed on absence, and permits destructive reconciliation only with positive corroboration; Claude-owned exact-SHA fixtures pass 14/14; paper-loop restart remains prohibited pending Claude acceptance |
| 2026-07-28T04:16:40.037460Z | CG-F057 integrity and continuous microstructure | CODE SEALED / CLAUDE ACCEPTANCE PENDING | `feed_integrity_pass=false` rejects every typed disposition; conservative continuous fill/slippage/impact/adverse-selection values are consumed by `AdaptivePolicyActionV2`; Claude-owned exact-SHA fixtures pass 14/14 |
| 2026-07-28T04:16:40.037460Z | P3/P4/P6 paper integration | CODE SEALED / RUNTIME PROOF PENDING | Durable feature clock/hash/finality evidence is replayed at allocation and final admission; performance regression is a bounded objective penalty; typed action or typed BLOCK disposition and cycle authorization lineage persist through fills, positions, reconstruction, and closes |
| 2026-07-28T04:16:40.037460Z | Candidate verification | PARTIAL PASS / BASELINE DEBT OPEN | 28/28 Claude-owned CG fixtures and 347/347 changed-path tests pass; compilation, focused Ruff, `git diff --check`, systemd verification, and G12 17/17 pass. Full legacy paper-loop module is 592 passed, 13 failed, 31 errors, matching the inherited 13/31 failure/error family |
| 2026-07-28T04:16:40.037460Z | Runtime safety boundary | STOPPED / NO DEPLOYMENT | Paper loop has `MainPID=0`; repair approval sentinel is absent. The last forced stop recorded `Result=timeout`, `ExecMainStatus=9`, and `MemoryPeak=608399360`; no restart or runtime acceptance is claimed. Pre-stop book was flat: positions=0, accepted fills=0, used margin=0, wallet/equity=`2985.59472051`; proof manifest was absent and therefore uninitialized, not initialized-empty |
| 2026-07-28T04:20:25.605120Z | PaperAccountEpochV1 SHA `bad88d5409` | BLOCK | Nominal DB-15 tests pass 13/13 and production dry preflight remains blocked without mutation, but adversarial probes prove mutation before the atomic guard, malformed-critical-JSON fail-open behavior, ignored reservations, incomplete archive hash verification, unenforced predecessor identity, and a `v2:paper:session` split brain. Rotation was not executed; see `claude_worklog/codex/PAPER_ACCOUNT_EPOCH_V1_CODEX_REVIEW_2026_07_28.md` |
| 2026-07-28T04:27:59.841885Z | Static Category-E hard-boundary repair | CODE SEALED / CLAUDE ACCEPTANCE PENDING | Commit `a124df529b` prevents an authorized adaptive economic decision from bypassing canonical risk, market integrity, reentry deduplication, thesis/feature-time evidence, runtime market evidence, or current-cycle duplicate prediction/signal/candle checks. This does not restore economic veto authority and does not claim all Category-E authority is removed. |
| 2026-07-28T04:27:59.841885Z | Immutable candidate reproducibility | PASS / DEPLOYMENT PROHIBITED | Exact candidate `28aada8c391adcee996035abc834d824d5c70af7` restores the byte-identical pre-existing growth-receipt fixture dependency from audited snapshot `d61c2acdc2`; its detached worktree is clean. Exact-tree checks are 222/222 focused adaptive/CG PASS, 64/64 scoped hard-boundary PASS, compile/Ruff/diff PASS, and the full paper-loop module is 595 passed, 13 failed, 31 errors—the same inherited 13/31 family. Independent Claude acceptance is still absent, so no deployment or restart occurred. |
| 2026-07-28T04:34:58.447203Z | Material SHA `0050eccd78` ledger-clock review | PASS SCOPED | Exact candidate tests are 9/9 for the reconstructed-ledger PIT repair and 85/85 across proof, integrity, router, and adaptive paths. The actual missing `paper_ledger_generated_at` defect is fixed using the producer reconstruction clock. A real non-flat position, missing reservation derivation, zero-size blocked intent, and exhausted exposure remain correct fail-closed rails/consequences and were not weakened. |
| 2026-07-28T04:34:58.447203Z | Continuous-learning runtime | PASS AT LAST SOURCE CYCLE / SOURCE NOW STOPPED | Candidate-outcome publisher is active; its last complete source cycle records 171/171 candidates, while its verified signed archive contains 8,471 decisions and 7,854 matured revisions with zero invalid/duplicate rows, 100% eligible maturation coverage, zero unexplained drops, and no counterfactual paper profit. The paper source is intentionally stopped, so this is not an end-to-end operational claim. |
| 2026-07-28T04:34:58.447203Z | Adaptive paper authority | HISTORICAL RUNTIME PASS / CURRENTLY STOPPED | Last paper authority status contains 171 typed decisions, 155 directional authorizations, 16 FLAT decisions, zero authority blocks, zero reference disagreements, `adaptive_policy_authoritative=true`, and `static_category_e_authority_removed=true`. The paper loop and shadow evaluator are currently stopped under the review boundary; lifecycle acceptance remains absent. |
| 2026-07-28T04:34:58.447203Z | G12 evidence-root distinction | PASS WITH AUTHORITATIVE RUNTIME EVIDENCE | Repository runtime evidence yields 17 PASS / 0 WARNING / 0 FAIL. A bare detached source tree yields 14 PASS plus three missing-external-evidence warnings for S13/S15/S16; runtime evidence was not misrepresented as an immutable source artifact. |
| 2026-07-28T04:48:53.029Z | FP-080 identity-scoped utilization collector | CODE SEALED / REVIEW AND INTEGRATION PENDING | Commit `c956ec46b8`; 19/19 focused tests, compile, scoped Ruff, real read-only collection, and `git diff --check` pass. Included source paths are internally consistent and hash/receipt verified. The generated v3 report is correctly `BLOCK`: gen-5 has 382 training rows but zero exact identity overlap with the 7,854 matured typed outcomes, and the wider paid-source inventory is not yet authenticated into the frozen scope. No Redis publication, service deployment, trainer change, paper restart, or exchange action occurred. |
| 2026-07-28T11:13:19.636056Z | FP-140 / FP-190 / FP-200 natural adaptive runtime acceptance | PASS SCOPED | Commit `4eb85c11fb` was independently accepted and immutably deployed with one writer. Natural 1000PEPE short `v2h_9de687c8976c12b33f84a627ab698fd6` retained exact proof/accounting state through restart, closed reduce-only `SHORT_TO_FLAT` at the governed time exit, booked net P&L `$0.05716304487747147`, reconciled wallet/equity/free margin to `$2,985.65188356`, released used/reserved margin to zero, and remained one canonical close with zero target quarantine across two further cycles. Evidence SHA-256 `d1c1177da792fc8a02ca038551416f69a99046b0bb74e562a83063c2cac91c5f`; broader data, challenger, supervisor and economic phases remain open. |
| 2026-07-28T12:00:17.029Z | FP-060 / FP-180 / FP-190 candidate-outcome runtime acceptance | PASS SCOPED | Commits `f3fd227ad1` and `27635258e8` remove matrix truncation and stream-verify the full signed archive before selecting matured revisions. Independent review first BLOCKED and then PASSed the repaired calibration boundary. Three immutable cycles published 685/685 candidates with no sampling or drops; the final archive has 10,335 decisions, 8,593 matured revisions and 18,928 verified rows, and calibration consumes its exact terminal chain. All three PIDs remain stable with zero restarts; proof/accounting/live boundaries are unchanged. Evidence SHA-256 `b1b699410185482518074bb7183d7731fcdff038b16fc6a6e5656ce77e825e6e`; broader adaptation and economics remain open. |
| 2026-07-28T12:40:30.554Z | FP-080 authenticated adaptive dataset | COMPLETE | Reconciled gen-5 backfill and typed-outcome corpus produce 6,954 authenticated serving-compatible rows with deterministic chronological splits 4,453/1,321/1,180, 161 symbols, four timeframes, no duplicate/future/finality/cost/label defects, and exact ABI/builder parity. Evidence SHA-256 `0d072b34e91752828b9f7ce362fbe006f15da2d4ef6ebbe10da10dc41fbb9399`. |
| 2026-07-28T13:24:06.705216Z | FP-100 authenticated challenger attempt | GOVERNED REJECTION / ESCALATION REQUIRED | Commit `7e8a153b78` independently passes 91 focused tests and rejects 34/34 coherent hostile mutations. The real GPU run completes 400 finite steps on all 6,954 authenticated rows and emits immutable checkpoint `419c65e206e0...`; it is not superior because validation calibrated Brier `0.2660115` exceeds baseline `0.1934555`. Generation 3 remains active and untouched. Evidence SHA-256 `b66859b8110ac6ef28aa3a549768789e397c01f95d0480915361088da6d49b91`. |
| 2026-07-28T14:19:08.391836Z | FP-080 / FP-100 / FP-110 authenticated rolling escalation | DISPATCH PASS / CHALLENGER REJECTED / CONTINUE LADDER | Commits `5821713e0b`, `8973b38140`, and `39ba18ae7d` authenticate the 9,189-row rolling release and execute one exact paper-only recalibration worker with immutable receipts and idempotent replay. Independent code and artifact audits PASS; checkpoint `e492d5c052...` is promotion-BLOCKED because validation calibrated Brier `0.3588536` is worse than baseline `0.3192224`. Generation 3 and runtime PIDs are unchanged. Evidence SHA-256 `605a46ab47d1980fcb5c692345f806a7f2254b317632ec10a4d48dedf750a63f`. |

## Current final status

This block must be updated whenever work stops or final acceptance changes.

```text
FINAL_PASS_STATUS=IN_PROGRESS
FINAL_ACCEPTANCE=BLOCKED_PENDING_REMAINING_ARCHITECTURE_AND_ECONOMIC_PHASES
FIRST_UNRESOLVED_STAGE=PHASE_1_TRADING_CONFIGURATION_CLASSIFICATION
CURRENT_SEGMENT=AUTHENTICATED_ADAPTIVE_DATASET_AND_GOVERNED_CHALLENGER_EVALUATION
CURRENT_SEGMENT_IMPLEMENTATION_SHA=7e8a153b78f26e51d19dad8ab5d7d7edd57b98a0
CURRENT_SEGMENT_CODE_SEALED=true
CURRENT_SEGMENT_CLAUDE_EXACT_SHA_ACCEPTANCE=PASS
CURRENT_SEGMENT_IMMUTABLE_ARTIFACTS=true
CURRENT_SEGMENT_RUNTIME_ACTIVATION=false
PAPER_LOOP_RUNTIME_STATE=ACTIVE_PAPER_ONLY
PAPER_LOOP_RESTART_RECONSTRUCTION=PASS
PAPER_ACCOUNT_EPOCH_ROTATION_SHA=bad88d5409dc33c7d30a191bde235a12fe1e7d7e
PAPER_ACCOUNT_EPOCH_ROTATION_CODEX_REVIEW=BLOCK
PAPER_ACCOUNT_EPOCH_ROTATION_EXECUTED=false

CLAUDE_IMPLEMENTATION_COMPLETE=false
CODEX_PRODUCTION_IMPLEMENTATION_COMPLETE_FOR_SCOPED_SEGMENT=true
CLAUDE_INDEPENDENT_RUNTIME_AUDIT_PASS=true

PAPER_SYSTEM_LIVE_END_TO_END=false
ADAPTIVE_LEARNING_LOOP_ACTIVE=PAPER_SOURCE_PUBLISHER_MATURER_AND_CALIBRATION_RUNTIME_PASS
ADAPTIVE_POLICY_CONTROLS_TRADING_ACTIONS=PROVEN_LATEST_RUNTIME_224_AUTHORITY_ATTEMPTS_0_REFERENCE_DISAGREEMENTS
STATIC_TRADING_ACTION_THRESHOLDS_WITH_FINAL_AUTHORITY=PAPER_ENTRY_PATH_REMOVED_FULL_REPOSITORY_CLASSIFICATION_OPEN
TRAINING_USES_ALL_ELIGIBLE_DATA=true
DATA_UTILIZATION_COLLECTOR_SHA=c956ec46b8
DATA_UTILIZATION_PATHS_CONSISTENT=true
DATA_UTILIZATION_REPORT_STATUS=PASS_AUTHENTICATED_ADAPTIVE_DATASET_BUILT
GEN5_TRAINING_ELIGIBLE_ROWS=382
ADAPTIVE_TRAINING_DATASET_ROWS=6954
ADAPTIVE_TRAINING_TYPED_OUTCOME_ROWS=6572
ADAPTIVE_TRAINING_SPLITS=4453_TRAIN_1321_VALIDATION_1180_HOLDOUT
TYPED_CANDIDATE_DECISIONS=10335
TYPED_MATURED_CANDIDATE_OUTCOMES=8593
CANDIDATE_OUTCOME_ARCHIVE_ROWS=18928
CANDIDATE_OUTCOME_ARCHIVE_VERIFIED=true
CANDIDATE_RECORDING_COVERAGE=1.0
UNEXPLAINED_CANDIDATE_DROPS=0
UNEXPLAINED_MATURATION_DROPS=0
CANDIDATE_OUTCOME_CALIBRATION_RUNTIME=PASS_EXACT_ARCHIVE_CHAIN
GEN5_TYPED_OUTCOME_JOIN=COMPLETE_AUTHENTICATED_COMPOSITE_CORPUS
FULL_PAID_SOURCE_INVENTORY_BOUND=false
DATA_UTILIZATION_REDIS_PUBLISHED=false
REJECTED_CANDIDATES_ARE_LABELED=PROVEN_100_PERCENT_LAST_COMPLETE_SOURCE_CYCLE
AUTHENTICATED_CHALLENGER_TRAINED=true
AUTHENTICATED_CHALLENGER_SUPERIOR=false
AUTHENTICATED_CHALLENGER_ACTIVATED=false
AUTHENTICATED_CHALLENGER_CHECKPOINT_ID=SERVING_ABI_V2_PROFITABILITY_PAPER_202aff0bb36baad9a4c8884f
AUTHENTICATED_CHALLENGER_EVIDENCE_SHA256=b66859b8110ac6ef28aa3a549768789e397c01f95d0480915361088da6d49b91
ACTIVE_PAPER_REGISTRY_GENERATION=3
ACTIVE_PAPER_CHECKPOINT_UNCHANGED=true
CHAMPION_CHALLENGER_LOOP_ACTIVE=NOT_YET_PROVEN
RESTART_RECONSTRUCTION_MATCH=true
NORMAL_PAPER_LIFECYCLE_COMPLETE=true
NATURAL_PAPER_CLOSE_ID=paper_close_paper_pos_1000PEPEUSDT_a38a3a3e790e11be_1_43703
NATURAL_PAPER_CLOSE_NET_PNL_USD=0.05716304487747147
POST_CLOSE_CONFIRMATION_CYCLES=2_OF_2_PASS
NATURAL_LIFECYCLE_ACCEPTANCE_ARTIFACT_SHA256=d1c1177da792fc8a02ca038551416f69a99046b0bb74e562a83063c2cac91c5f
CANDIDATE_OUTCOME_RUNTIME_ACCEPTANCE_ARTIFACT_SHA256=b1b699410185482518074bb7183d7731fcdff038b16fc6a6e5656ce77e825e6e
G03=NOT_EVALUATED_FOR_FINAL_PASS
G11=NOT_EVALUATED_FOR_FINAL_PASS
G12=PASS_17_OF_17_REVALIDATED_2026_07_28
G13=NOT_EVALUATED_FOR_FINAL_PASS
G14=NOT_EVALUATED_FOR_FINAL_PASS

V2_PERMANENT_RECOVERY_COMPLETE=false
LIVE_NO_GO_FOR_REAL_EXCHANGE=true
paper_only=true
live_gate=blocked_human_only
routes_to_live=false
places_real_order=false
exchange_action_taken=false

OPERATOR_ACTION_REQUIRED=NONE
NEXT_CODEX_ACTION=CONTINUE_AUTOMATIC_CHALLENGER_ESCALATION_AND_FP020_FP070_FP090_FP110_FP120
NEXT_CLAUDE_ACTION=REVIEW_NEXT_MATERIAL_SHA_AND_RUNTIME_EVIDENCE
LATEST_REPOSITORY_CHECKPOINT=7e8a153b78f26e51d19dad8ab5d7d7edd57b98a0
LATEST_CANDIDATE_TESTS=132_COMBINED_TRAINER_DATA_PASS_91_INDEPENDENT_PASS_34_OF_34_HOSTILE_REJECT
LEGACY_PAPER_LOOP_SUITE=691_PASS_13_FAIL_31_ERROR_UNCHANGED_INHERITED_FAMILY
```

## Prior current-segment handoff and command ledger (superseded)

Exact blocker: candidate SHA `28aada8c391adcee996035abc834d824d5c70af7`
has not received Claude's independent exact-SHA acceptance or immutable runtime
verification. Actual paper-loop state is stopped with `MainPID=0`; required
state before restart is a Claude PASS for CG-F063/CG-F057, the hard local-gate
boundary, and approval of that same immutable SHA. No operator credential or
reboot blocker exists.

Separately, paper-account epoch commit `bad88d5409` is blocked from execution by
the scoped Codex review. It is not a substitute for accepting and restarting the
paper loop, and no epoch/session rotation is authorized from this state.

The later four-item allocation diagnosis is now split correctly. Commit
`0050eccd78` repairs the genuine missing ledger-generation timestamp. The
ordinary-router non-flat result, missing `reservation.derived`, zero-size
blocked intent, and `BLOCK_EXPOSURE_BUDGET` were consequences of unproved open
inventory and remain required hard rails. Current Redis is flat (positions=0,
proofs=0, used margin=0); the proof manifest is absent, so the next reviewed
startup must initialize an authenticated empty proof set rather than infer it.

Phase 7 now has a production collector at commit `c956ec46b8`. Its real
read-only run revalidates the frozen snapshot byte hashes, SQLite integrity,
backfill reconciliation, serving-dataset reproducibility, signed candidate
archive counts, checkpoint bundle identities, and paper/live boundaries. It
does not flatten unlike identity domains. The generated local report is
internally consistent but remains `BLOCK` for two exact reasons:

```text
TYPED_CANDIDATE_OUTCOMES_NOT_JOINED_TO_GEN5_TRAINING_ROWS
FULL_PAID_SOURCE_INVENTORY_NOT_BOUND_TO_FROZEN_GEN5_SCOPE
```

Actual typed/gen-5 exact identity overlap is `0`; required full join is `382`.
The broader legacy/paid-source archives exist, but no authenticated one-to-one
transform into the frozen corpus has been proven. The report was written to the
required ignored goal-state path for review but was intentionally not published
to Redis and no runtime unit was deployed.

Claude's next owned action is to review the exact paper-loop SHA, record PASS or
a failing fixture, and—only on PASS—point the immutable release drop-in at that
SHA and run the owned runtime acceptance harness. In parallel without touching
those paper-loop files, Codex continues the paid-source inventory binding and
typed-outcome training join. The safe Claude inspection command is:

```bash
git -C /home/wali/ai_bot_local_data/deployments/ai_bot_rebuild/28aada8c391adcee996035abc834d824d5c70af7 rev-parse HEAD
```

Commands executed for this segment, with no real exchange mutation:

```text
systemctl --user show ai-bot-v2-trade-management-paper-loop.service -p <scoped-properties>
systemctl --user daemon-reload
systemctl --user stop ai-bot-v2-trade-management-paper-loop.service
systemd-analyze --user verify ai-bot-v2-stack.target default.target timers.target ai-bot-v2-trade-management-paper-loop.service
redis-cli --raw GET <scoped-paper-state-key> | jq <scoped-projection>
redis-cli EXISTS v2:paper:open_position_fill_proofs:manifest
git status --short --branch
git log -8 --oneline --decorate
git diff --stat -- <scoped-files>
git diff --check
git add -- <eight-scoped-files>
git commit -m "Fail closed paper proof reconciliation"
git commit -m "Keep adaptive policy behind hard local gates"
git commit -m "Restore committed paper growth fixture dependency"
git rev-parse HEAD
git worktree add --detach <immutable-candidate-path> 7d3624d24b
git worktree add --detach <immutable-candidate-path> a124df529b
git worktree add --detach <immutable-candidate-path> 28aada8c39
git worktree move <initial-candidate-path> <exact-SHA-candidate-path>
.venv/bin/python -m py_compile <five-changed-production-files>
.venv/bin/ruff check --select E902,F821,F822,F823 <changed-files>
.venv/bin/pytest -q v2/backend/tests/unit/cli/test_cg_f063_proof_store_reconciliation.py v2/backend/tests/unit/services/microstructure_trust/test_cg_f057_completion_acceptance.py
.venv/bin/pytest -q <changed-path-test-selection>
.venv/bin/pytest -q --tb=no v2/backend/tests/unit/cli/test_v2_trade_management_paper_loop.py
.venv/bin/pytest -q <exact-candidate-focused-adaptive-and-CG-selection>
.venv/bin/pytest -q <exact-candidate-scoped-hard-boundary-selection>
.venv/bin/python scripts/guardian_phase10_rare_event_tests.py
.venv/bin/pytest -q v2/backend/tests/test_paper_epoch_rotation.py
.venv/bin/python tools/paper_epoch_preflight.py
.venv/bin/python - <in-memory PaperAccountEpochV1 adversarial probe>
sha256sum v2/backend/app/services/paper_session/epoch.py v2/backend/tests/test_paper_epoch_rotation.py tools/paper_epoch_preflight.py tools/paper_epoch_rotate.py
git status --short --branch
git log --oneline --decorate <scoped-history>
git show --stat/--format <material-SHA>
git branch --all --contains <material-SHA>
git merge-base --is-ancestor <material-SHA> HEAD
rg -n <allocation-proof-authority-runtime-patterns> v2/backend goal_state claude_worklog FINAL\ PASS.md
systemctl --user show/cat/list-units/list-unit-files <paper/adaptive/candidate-units>
systemctl --user list-dependencies ai-bot-v2-stack.target
systemd-analyze --user verify <scoped-units-and-targets>
redis-cli --raw GET <paper-proof/account/adaptive/candidate-status-key> | jq <scoped-projection>
jq <scoped-projection> /home/wali/ai_bot_local_data/gen5_snapshot_backfill_v1/evidence/*.json
jq <scoped-projection> /home/wali/ai_bot_local_data/gen5_snapshot_backfill_v1/*report.json
.venv/bin/pytest -q v2/backend/tests/unit/cli/test_paper_allocation_reconstructed_ledger_generated_at.py
.venv/bin/pytest -q <exact-proof-integrity-router-adaptive-selection>
.venv/bin/python -m py_compile <paper/adaptive/router-production-files>
.venv/bin/ruff check --select E902,F821,F822,F823 <paper/adaptive/router-and-ledger-test-files>
.venv/bin/python scripts/guardian_phase10_rare_event_tests.py
.venv/bin/python -m py_compile <data-utilization-production-files>
.venv/bin/pytest -q <data-utilization-focused-selection>
.venv/bin/ruff check --select E902,F821,F822,F823 <data-utilization-files>
.venv/bin/ruff check --ignore E501,UP017,UP038 <data-utilization-files>
.venv/bin/python -B -m v2.backend.app.cli.v2_data_utilization_funnel_publisher --no-publish --no-write-report
.venv/bin/python -B -m v2.backend.app.cli.v2_data_utilization_funnel_publisher --no-publish
sqlite3 -readonly <frozen-feature-or-label-store> <scoped-count/finality/source-label-query>
wc -l <legacy-feature-snapshot-manifest>
git add -- <six-data-utilization-files>
git commit -m "Publish identity-scoped data utilization truth"
```

Files changed by the sealed production candidate:

```text
v2/backend/app/cli/v2_paper_provisional_prediction_publisher.py
v2/backend/app/cli/v2_trade_management_paper_loop.py
v2/backend/app/services/adaptive_system/adaptive_policy_shadow_v2.py
v2/backend/app/services/paper_trade_management/outcomes.py
v2/backend/app/services/paper_trade_management/position_state.py
v2/backend/tests/unit/cli/test_v2_trade_management_paper_loop.py
v2/backend/tests/unit/services/adaptive_capital_allocator/growth_receipt_test_utils.py
v2/backend/tests/unit/services/adaptive_system/test_adaptive_policy_shadow_v2.py
v2/backend/tests/unit/services/paper_trade_management/test_lifecycle.py
FINAL PASS.md (status ledger only; separate from the production candidate)
```

Runtime-only safety boundary (outside the repository):

```text
/run/user/1000/systemd/user/ai-bot-v2-trade-management-paper-loop.service -> /dev/null
/run/user/1000/systemd/user/ai-bot-v2-trade-management-paper-loop.service.d/00-codex-repair-boundary.conf
/home/wali/ai_bot_local_data/deployments/ai_bot_rebuild/28aada8c391adcee996035abc834d824d5c70af7/ (clean detached candidate worktree)
```

The pre-existing `.claude/hooks/block_dangerous.sh` modification was preserved,
excluded from the candidate commit, and not edited by this segment.

Additional evidence-only files updated during the ledger/runtime reconciliation:

```text
FINAL PASS.md
goal_state/ADAPTIVE_SYSTEM_FINAL_PASS/CODEX_REVIEWS.jsonl (ignored local coordination ledger)
goal_state/ADAPTIVE_SYSTEM_FINAL_PASS/WORK_QUEUE.json (ignored local coordination ledger)
goal_state/ADAPTIVE_SYSTEM_FINAL_PASS/data_utilization_report.json (ignored generated v3 report)
```

Phase-7 production files added or changed after the sealed paper candidate:

```text
v2/backend/app/cli/v2_data_utilization_funnel_publisher.py
v2/backend/app/services/adaptive_system/data_utilization_funnel_v2.py
v2/backend/app/services/adaptive_system/data_utilization_report_v3.py
v2/backend/tests/unit/cli/test_v2_data_utilization_funnel_publisher.py
v2/backend/tests/unit/services/adaptive_system/test_data_utilization_funnel_v2.py
v2/backend/tests/unit/services/adaptive_system/test_data_utilization_report_v3.py
```

---

# Claude Role-A implementation status (complements the Codex tracker above)

Codex (Role B) owns the coordination ledger, goal record, and audit signoff above.
This section is the Claude (Role A) implementation-lane truth. Both agents agree the
directive is a full re-architecture (static Category-E gates → one unified learned
adaptive policy) and that it is **NOT complete**. Machine-readable Claude progress lives in
`goal_state/ADAPTIVE_SYSTEM_FINAL_PASS/CLAUDE_PROGRESS.jsonl`.

## Honest scope reality

This is a multi-week dual-agent program, not a one-session task. The in-flight
generation-4 challenger attempt advanced a *slice* (FP-080 data corpus and FP-100
one challenger) but was not superior and was correctly rejected; generation 3
remains active. That attempt did **not** deliver the core of the directive:
FP-020 (remove all static Category-E final authorities), FP-040 (calibrated
component producers and cutover), FP-050 (runtime adaptive objective), FP-110
(persistent escalation ladder), FP-130 (full venue-aware adaptive exploration),
or FP-150 (single policy authority). FP-030 is now independently complete, and
shadow foundations exist for FP-040, FP-050, and the arithmetic portion of FP-130.

## Implementation truth established this session

| Phase | Item | State | Evidence |
|---|---|---|---|
| 0 | Runtime/repo truth frozen | DONE | `goal_state/PERMANENT_SYSTEM_RECOVERY/final_pass_frozen_contract.json` (gen 3, cohort, ABI `1dac8c33…`, flat book, invariant holds) |
| 12/19 | **Fill deadlock root-caused to an exact predicate** | DIAGNOSED | `final_target_notional $0.65–1.59 < minimum_executable_notional $5.0–5.62` on 13/13 live symbols; cause = gen-3 confidence too low → every admissible candidate lands in the 5%-risk-cap exploration lane, and 5% × a $20–60 normal notional is below the venue minimum. This is exactly the Phase-12 prohibition (exploration must not authorize sub-venue-minimum actions). `final_pass_terminal_blockers.json` |
| 7/9/11/20 | **Generation-4 serving challenger** | REJECTED / GEN-3 RETAINED | The challenger completed evaluation but did not prove superiority, so governed activation did not occur. Corpus growth/repair continues; no cohort rotation or lifecycle/economic completion is claimed. |
| 2 | `AdaptivePolicyActionV2` | DONE | Canonical commit `0980e69210`; 45 tests and independent review PASS; weaker duplicate removed in `658d6fc760` |
| 3/4 | Component-estimate and objective contracts | SHADOW FOUNDATIONS | Component schema/projector independently accepted through `5ce083874d`; objective foundation independently accepted at `d12f418d3d`; neither controls runtime |
| 5 | `CandidateDecisionOutcomeV2` | CONTRACT FOUNDATION PASS | Commit `289bb9911f`; immutable decision/label revisions, exact PIT/finality, planned counterfactuals, accounting and no-live boundaries independently pass; runtime archive and coverage remain open |
| 12 | Exact venue-minimum proposal | PRELIMINARY PRIMITIVE PASS | Commit `2b7442e61a`; independent adversarial review PASS at 27 tests; explicitly non-authoritative and not the complete exploration controller |

## Static Category-E final authorities still in force (FP-020 target list)

`PAPER_RISK_CONTROLLER_EXPLORATION_LOSS_PROBABILITY_BOUND=0.72`,
`..._MIN_EXIT_FEASIBILITY=0.50`, `POSITIVE_EDGE_PROBATION_MIN_EXIT_FEASIBILITY=0.55`,
`..._MAX_RISK_FRACTION_OF_NORMAL=0.05`, `B_GRADE_EXPLORATION_MAX_RISK_FRACTION_OF_NORMAL=0.25`,
`CONSERVATIVE_LOSS_PROBABILITY_THRESHOLD`, fail-closed `adaptive_confidence_threshold=1.0`,
discrete microstructure `ALLOW/REDUCE_SIZE/BLOCK`, exit-feasibility `0.25/0.35/0.40/0.45` caps,
MFE half-stop rule. Each must become a model output / learned function / optimizer result — none removed yet.

## Claude Role-A final status

```text
CLAUDE_ROLE_A_IMPLEMENTATION_STATUS=IN_PROGRESS
CLAUDE_IMPLEMENTATION_COMPLETE=false
core_adaptive_rearchitecture_FP020_FP040_FP050_FP110_FP130_FP150=in_progress
FP030_action_contract=complete_independently_reviewed
FP040_component_schema_projector=foundation_pass_runtime_conversion_pending
FP050_adaptive_objective=shadow_foundation_independently_reviewed_runtime_fitting_pending
FP130_venue_minimum_primitive=independently_reviewed_full_controller_absent
gen4_retrain_FP080_FP100=rejected_not_superior_gen3_retained
fill_lifecycle_FP200=blocked_on_governed_policy_reaching_a_fillable_tier
economic_acceptance_FP210=blocked_on_FP200
paper_only=true
live_gate=blocked_human_only
routes_to_live=false
places_real_order=false
exchange_action_taken=false
catastrophic_envelope_relaxed=false
block_dangerous_hook_modified=false
```

---

## CG-F063 / CG-F057 immutable runtime acceptance — 2026-07-28

This is the latest authoritative status for the scoped paper-loop recovery
segment. It supersedes older candidate-SHA and restart-pending entries above;
it does not supersede the broader unfinished FINAL PASS architecture phases.

### Completed task list

- [x] Distinguish `EMPTY_INITIALIZED_PROOF_SET` from
  `PROOF_STORE_UNINITIALIZED_OR_UNBACKFILLED` and fail closed without deleting
  positions or mutating wallet/margin when proof state is absent.
- [x] Backfill and hash-bind authenticated accepted fills, position identity,
  checkpoint/prediction lineage, quantity, price, notional and margin.
- [x] Require positive invalidity evidence before destructive reconciliation;
  preserve legitimate long/short positions and make reconciliation idempotent.
- [x] Atomically persist entry proofs, proof manifest, close receipts,
  partial-close transition proofs, positions, fills, closes and accounting.
- [x] Validate every partial-close ancestor and successor link for identity,
  hash, quantity, capital, paper-only authority, exact reduce-only receipt,
  complete finite nonnegative cost basis and cross-generation cost continuity.
- [x] Preserve hard `feed_integrity_pass=false` rejection for every typed action
  and consume conservative continuous microstructure estimates in
  `AdaptivePolicyActionV2` (`CG-F057`: 14/14 focused tests PASS).
- [x] Independently review exact production commit
  `d3635a8c10ef02f0a8c553e0a7d69feb780cef60`; paper-loop SHA-256
  `1c234a4f297745e8bfcf5bb45b325a230a58b7600916bd6eed62871c6e324f10`.
- [x] Deploy one clean detached immutable paper-loop release, verify credential
  file presence/mode without reading contents, restart only the paper loop and
  preserve the human-blocked live boundary.
- [x] Observe three completed runtime cycles with no wipe, phantom, duplicate
  fill/close, reservation leak, wallet mutation or accounting drift.
- [x] Revalidate S15 `8/8`, S16 `5/5`, G12 `17/17`, systemd diagnostics `0`,
  focused Ruff, Python compilation and `git diff --check`.
- [ ] Observe a natural accepted paper fill and proof-backed open position.
- [ ] Perform restart reconstruction while that natural position remains open.
- [ ] Observe ordinary adaptive reduce-only close, accounting reconciliation and
  two additional completed cycles.
- [ ] Accumulate the required natural economic cohort and close G03/G11/G13/G14.

### Runtime evidence

The immutable runtime acceptance artifact is
`goal_state/PERMANENT_SYSTEM_RECOVERY/d3635a8c_paper_runtime_acceptance_20260728.json`;
the pre-restart snapshot is
`goal_state/PERMANENT_SYSTEM_RECOVERY/d3635a8c_paper_runtime_acceptance_pre_restart_20260728.json`.

Across the three completed cycles, accepted fills, open positions, phantoms,
duplicate fills, duplicate closes and reservation leaks were all zero. Wallet,
equity and free margin remained exactly `$2,985.59472051`; used and reserved
margin remained zero. The authenticated proof manifest initialized as
`EMPTY_INITIALIZED_PROOF_SET` with `completed=true`. Historical closes remained
92/92 unique with the same canonical hash. Cycle 3 evaluated 397 paper
signals/intents; all 397 were rejected by the unchanged governed path, so no
natural position existed for restart reconstruction.

One post-boundary confirmation cycle completed from
`2026-07-28T06:20:54.912Z` through `06:21:31.846Z`: 59 additional intents,
zero accepted fills/positions, and unchanged paper-only/no-live authority. The
final runtime artifact SHA-256 is
`312421554d0e26ca8120014661c31b6801b501c1669eec57a2eba7d0454518b9`.

### Scoped command ledger

The following command families were run from the repository root, with the
focused test/static commands rerun after each adversarial fixture commit and
production repair SHA:

```text
rg -n <partial-close/proof-chain/status-patterns> v2/backend FINAL\ PASS.md claude_worklog/codex
sed -n <scoped-ranges> v2/backend/app/cli/v2_trade_management_paper_loop.py v2/backend/tests/unit/cli/test_cg_f063_proof_store_reconciliation.py
git status --short --branch
git log -6 --oneline --decorate
git diff -- <scoped-file>
git diff --check
git add -- <scoped-file>
git commit -m <scoped-message>
git rev-parse HEAD
sha256sum v2/backend/app/cli/v2_trade_management_paper_loop.py goal_state/PERMANENT_SYSTEM_RECOVERY/d3635a8c_paper_runtime_acceptance_20260728.json
.venv/bin/pytest -q v2/backend/tests/unit/cli/test_cg_f063_proof_store_reconciliation.py
.venv/bin/pytest -q v2/backend/tests/unit/cli/test_v2_trade_management_paper_loop.py -k 'open_position_fill_proof or position_fill_reconciliation or critical_paper_state_uses_one_redis_transaction'
.venv/bin/pytest -q v2/backend/tests/unit/services/paper_trade_management/test_partial_close_restart_reconstruction.py v2/backend/tests/unit/services/paper_trade_management/test_lifecycle.py
.venv/bin/pytest -q v2/backend/tests/unit/services/microstructure_trust/test_cg_f057_completion_acceptance.py
.venv/bin/pytest -q v2/backend/tests/unit/services/adaptive_system/test_adaptive_policy_shadow_v2.py
.venv/bin/pytest -q --tb=no v2/backend/tests/unit/cli/test_v2_trade_management_paper_loop.py
.venv/bin/python -m py_compile v2/backend/app/cli/v2_trade_management_paper_loop.py
.venv/bin/ruff check --select E902,F821,F822,F823 v2/backend/app/cli/v2_trade_management_paper_loop.py
systemctl --user show ai-bot-v2-trade-management-paper-loop.service -p <scoped-properties>
systemd-analyze --user verify ai-bot-v2-stack.target default.target timers.target ai-bot-v2-trade-management-paper-loop.service
redis-cli --raw GET/MGET <scoped-paper-state-keys> | jq <scoped-projection>
jq <scoped-projection> goal_state/PERMANENT_SYSTEM_RECOVERY/generation_acceptance_status.json
jq . goal_state/PERMANENT_SYSTEM_RECOVERY/d3635a8c_paper_runtime_acceptance_20260728.json
.venv/bin/python scripts/s15_stale_feature_injection_test.py
.venv/bin/python scripts/s16_redis_resilience_test.py
.venv/bin/python scripts/guardian_phase10_rare_event_tests.py
```

Claude's runtime lane additionally used `git worktree add --detach`, credential
metadata-only `stat`, read-only Redis/Python projections,
`systemctl --user daemon-reload/restart/is-active/is-enabled`, journal/status
inspection and completed-cycle polling. It restarted only the paper loop and
did not read credential contents or touch a real exchange.

### Truthful final status for this segment

```text
CG_F063_CODE_AND_ADVERSARIAL_FIXTURES=PASS_58_OF_58
CG_F063_EMPTY_BOOK_RUNTIME_ACCEPTANCE=PASS_3_OF_3_CYCLES
CG_F057=PASS_14_OF_14
G12=PASS_17_OF_17
CURRENT_SEGMENT_CONTROLLABLE_ENGINEERING_COMPLETE=true
IMMUTABLE_PAPER_RELEASE_ACTIVE=true
NATURAL_PAPER_FILL_OBSERVED=false
PROOF_BACKED_OPEN_POSITION_OBSERVED=false
RESTART_RECONSTRUCTION_MATCH=false
NORMAL_PAPER_LIFECYCLE_COMPLETE=false
ECONOMIC_ACCEPTANCE_PENDING=true
PAPER_SYSTEM_LIVE_END_TO_END=false
V2_PERMANENT_RECOVERY_COMPLETE=false
LIVE_NO_GO=true
paper_only=true
live_gate=blocked_human_only
routes_to_live=false
places_real_order=false
exchange_action_taken=false
NEXT_TRIGGER=FRESH_GENERATION_3_PERSISTED_NATURAL_FILL_WITH_OPEN_POSITION
```

## Natural adaptive lifecycle acceptance — authoritative update 2026-07-28

This section supersedes the restart-pending and natural-fill-pending statements
in the historical segment immediately above. It closes the controllable
CG-F063/CG-F057/P3/P4/P6 runtime chain and FP-200; it does not mark the broader
FINAL PASS or permanent recovery complete.

### Completed in this segment

- [x] Independently accept the scoped CG-F063 and CG-F057 implementation and
  adversarial fixtures.
- [x] Deploy one clean immutable paper-loop release at
  `4eb85c11fb5af467edf6ca4371880c5bb6ef5529`.
- [x] Prove exactly one canonical paper writer, zero forbidden/duplicate
  writers, and `NRestarts=0` for paper and canonical serving.
- [x] Observe a natural generation-3 adaptive short action, accepted fill,
  proof-bound open position, mandatory stop and governed max-hold exit.
- [x] Capture accounting and proof state, restart only the paper loop, and
  retain the exact position/fill/proof lineage with no duplicate or release.
- [x] Close ordinarily and reduce-only from `SHORT_TO_FLAT`, consume all
  `26,300` units, release all margin, create one canonical close/outcome, and
  keep the target out of the unproved-close quarantine.
- [x] Recompute the nested authenticated admission envelope, typed policy
  action, authorization and cycle receipt successfully.
- [x] Reconcile cumulative realized P&L to wallet/equity/free margin and prove
  used margin, reserved margin and unrealized P&L are zero.
- [x] Complete two additional paper cycles with the close stable and no new
  fill, proof, position, quarantine, duplicate or reservation leak.
- [x] Obtain an independent Claude-role runtime `PASS` on the exact immutable
  release and both post-close cycles.

### Frozen natural lifecycle evidence

The authoritative artifact is
`goal_state/PERMANENT_SYSTEM_RECOVERY/4eb85c11_1000pepe_lifecycle_acceptance_20260728.json`
with SHA-256
`d1c1177da792fc8a02ca038551416f69a99046b0bb74e562a83063c2cac91c5f`.

The natural lineage is:

```text
prediction/fill/intent=v2h_9de687c8976c12b33f84a627ab698fd6
signal=sig_v2h_9de687c8976c12b33f84a627ab698fd6
orchestrator=dec_v2h_9de687c8976c12b33f84a627ab698fd6
risk=rd_dec_v2h_9de687c8976c12b33f84a627ab698fd6
allocation=alloc_6bbbb576c4eb8e5c6a1fed6c
position=paper_pos_1000PEPEUSDT_a38a3a3e790e11be
close=paper_close_paper_pos_1000PEPEUSDT_a38a3a3e790e11be_1_43703
checkpoint_generation=3
checkpoint_id=SERVING_ABI_V2_PAPER_f2f6e3b4c67a42b6c13880a4
cohort_id=paper_serving_abi_v2:541f38b82f5261b5176bbf5f
```

The short entered `26,300 × 0.0028115 = $73.94245` at 1× leverage,
therefore allocated margin was exactly `$73.94245`. It closed at `0.0028089`
at `2026-07-28T11:06:38.250082Z` for the governed
`TIER_3_ADAPTIVE_POLICY_TIME_EXIT`. Gross P&L was `$0.06838`; after
`$0.007390826` fees, `$0.0013802411974931552` slippage and
`-$0.002445887925039896` funding P&L, net P&L was
`$0.05716304487747147`. The close admission envelope declared and recomputed
SHA-256 is `ec15ba029d6bb2ebf5b229231deb8cf7b92b1e2ee50dd18ccc926835f9e84f4a`;
the canonical close SHA-256 is
`43c4aec88d999d3795770f27cc5004c76d30656a09fd353df104356ce7b6ea3d`.

Canonical portfolio accounting after the close is:

```text
starting_equity_usd=3000.00000000
cumulative_realized_net_pnl_usd=-14.34811644
wallet_balance_usd=2985.65188356
equity_usd=2985.65188356
free_margin_usd=2985.65188356
used_margin_usd=0.00000000
reserved_margin_usd=0.00000000
unrealized_pnl_usd=0.00000000
equity_reconciliation_difference_usd=0.00000000
accounting_invariant=PASS
```

Post-close cycle 1 ran from `2026-07-28T11:08:15.552085Z` through
`11:09:13.980510Z`; cycle 2 ran from `11:10:17.845454Z` through
`11:12:15.002163Z`. Both ended with 93 canonical closes, zero open positions,
zero accepted fills, zero open fill proofs and the pre-existing quarantine
count unchanged at two; the target quarantine count remained zero. The final
proof manifest is completed `EMPTY_INITIALIZED_PROOF_SET`, which is distinct
from an uninitialized proof store and has `absence_is_invalidity=false`.

### Independent verdict

The Claude-role audit independently recomputed the close, nested admission,
typed-action, authorization, cycle-receipt and accounting hashes and returned
`PASS`. It also verified the release is clean, the service remains PID
`3597757` with `NRestarts=0`, the close is unique globally, both confirmation
cycles are stable, the MORPH invalidated bucket remains a zero-trade
nonblocking tombstone, and every runtime authority flag remains paper-only.

### Current truthful status

```text
CG_F063=PASS
CG_F057=PASS
FP_140=SCOPED_RUNTIME_CHAIN_PASS_FULL_PHASE_IN_PROGRESS
FP_190=SCOPED_IMMUTABLE_DEPLOYMENT_PASS_FULL_PHASE_IN_PROGRESS
FP_200=COMPLETE
ADAPTIVE_POLICY_AUTHORITATIVE=true
STATIC_CATEGORY_E_PAPER_ENTRY_AUTHORITY_REMOVED=true
REFERENCE_PARITY_DISAGREEMENT_COUNT=0
NATURAL_PAPER_FILL_OBSERVED=true
PROOF_BACKED_OPEN_POSITION_OBSERVED=true
RESTART_RECONSTRUCTION_MATCH=true
NORMAL_PAPER_LIFECYCLE_COMPLETE=true
ACCOUNTING_RECONCILED=true
POST_CLOSE_CONFIRMATION_CYCLES=2_OF_2_PASS
G12=PASS_17_OF_17

ENGINEERING_RECOVERY_COMPLETE_FOR_SCOPED_SEGMENT=true
FULL_FINAL_PASS_ENGINEERING_COMPLETE=false
ECONOMIC_ACCEPTANCE_PENDING=true
PAPER_SYSTEM_LIVE_END_TO_END=false
V2_PERMANENT_RECOVERY_COMPLETE=false
LIVE_NO_GO=true
paper_only=true
live_gate=blocked_human_only
routes_to_live=false
places_real_order=false
exchange_action_taken=false

FIRST_UNRESOLVED_STAGE=PHASE_1_TRADING_CONFIGURATION_CLASSIFICATION
NEXT_CONTROLLABLE_WORK=VERIFY_CANDIDATE_OUTCOME_RUNTIME_HEALTH_THEN_COMPLETE_TYPED_OUTCOME_TO_GEN5_JOIN_AND_REMAINING_ADAPTATION_PHASES
```

FP-020, FP-040, FP-050, FP-070 through FP-130, FP-150, FP-160, FP-170,
FP-180, FP-210, FP-220, FP-230, FP-240 and FP-250 remain open according to
their task predicates. Five generation-scoped eligible natural closes and the
frozen-window G03/G11/G13/G14 evaluation are still required; this single close
must not be inflated into economic acceptance.

## Candidate-outcome runtime acceptance — authoritative update 2026-07-28

This section supersedes the candidate-outcome publisher health-recheck language
above. It completes FP-060 and adds scoped FP-180/FP-190 evidence; it does not
complete the wider data join, adaptation supervisor, challenger, economic, or
real-exchange acceptance phases.

### Completed in this segment

- [x] Repair the candidate decision matrix so the authoritative finalized
  universe is complete and unsampled, including when a cycle exceeds the prior
  250-row diagnostic limit.
- [x] Keep the consumer fail closed on malformed/truncated matrices, count or
  identity drift, duplicate identities, prediction/checkpoint mismatch, and any
  live-authority flag.
- [x] Stream-verify every signed archive row, nested contract, content hash,
  chain link, CAS transition, timestamp and paper-only authority invariant while
  retaining only the matured revisions used by calibration.
- [x] Repair the independent-review blocker proving that a coherently rehashed,
  rechained and resigned invalid unselected revision must still be rejected.
- [x] Deploy paper loop, outcome publisher and calibration from one clean
  immutable release at `27635258e87ba434c2c001887337db31972f1969`.
- [x] Observe three completed post-release paper cycles and require the publisher
  and calibration receipt to catch up to each signed archive chain.
- [x] Preserve initialized-empty proof semantics, canonical accounting, one
  writer, zero restarts, zero duplicates/leaks and all paper-only/no-live flags.

### Runtime proof

The authoritative evidence is
`goal_state/PERMANENT_SYSTEM_RECOVERY/27635258_candidate_outcome_runtime_acceptance_20260728.json`
with SHA-256
`b1b699410185482518074bb7183d7731fcdff038b16fc6a6e5656ce77e825e6e`.

The post-release cycles completed at `11:53:17.180332Z`,
`11:55:42.589900Z` and `11:59:12.183121Z`. Their matrices were respectively
359/359, 102/102 and 224/224, for an aggregate 685/685 candidates with
`matrix_complete=true` and `sampling_applied=false`. Every cycle retained the
same 93 canonical closes, zero accepted fills, zero open positions, zero open
fill proofs and the same two historical unproved-close quarantine records.

Wallet, equity and free margin stayed exactly `$2,985.65188356`; used and
reserved margin, destructive reconciliation releases and wallet mutation stayed
zero. The proof store remained the valid `EMPTY_INITIALIZED_PROOF_SET`, not an
uninitialized proof store. Reconciliation was idempotent and reported zero
phantom, unresolved or rejected positions.

The final publisher receipt records:

```text
status=PASS
source_candidate_count=224
recorded_candidate_count=224
candidate_recording_coverage=1.0
unexplained_candidate_drops=0
archive_decision_revisions=10335
archive_matured_revisions=8593
archive_rows=18928
archive_invalid_rows=0
archive_duplicate_rows=0
eligible_matured_label_coverage=1.0
unexplained_maturation_drops=0
counterfactual_counts_as_paper_profit=false
terminal_chain_sha256=60f670cece79fb6a94d083d32afb38ece363444ddc40c8c90f265763b5076df7
```

The final calibration receipt consumes that exact terminal chain, uses 6,301
fit and 2,292 validation samples for generation 3, and has calibration SHA-256
`d15e30fa16df2b29ad744bcea22264e8fdb44ac9a5a09cae61a38e4b6120a617`.
Counterfactual outcomes remain excluded from realized paper profit.

The services remain active at paper PID `3710798`, publisher PID `3710826` and
calibration PID `3710851`, all with `NRestarts=0`. Peak memory was bounded at
1,390,624,768, 1,956,245,504 and 1,113,534,464 bytes respectively. The publisher
has a 2,500-MiB high/3-GiB max boundary; calibration has a 1,280-MiB high/
1,536-MiB max boundary. These deployment limits repair deterministic cold-scan
capacity only; no strategy, threshold, admission, risk or execution authority
changed.

### Independent verdict and verification

The Claude-role complete-matrix review returned `PASS`: all 302 reference
identities and the >250 regression universe were retained, while malformed,
truncated, duplicate, drifted and live-authority fixtures rejected. The
streaming-calibration review initially returned `BLOCK` for an invalid
unselected revision that had been coherently re-signed; after every streamed row
was made subject to nested-contract validation, the adversarial fixture rejected
with `record:nested_contract_invalid:record_generated_at_ms:must_be_positive_int`
and the final exact-SHA review returned `PASS`.

Verification on the immutable tree is 58/58 archive/publisher/calibration tests
and 27/27 matrix/paper focused tests. The previously completed CG-F057/adaptive/
lifecycle selection remains 144/144. G12 is 17/17 PASS; Python compilation,
focused Ruff, `git diff --check`, immutable-tree cleanliness and systemd
verification all pass. The full paper-loop result is 691 passed, 13 failed and
31 setup errors: the same inherited 13/31 legacy fixture family, plus this
segment's new passing regression.

### Current truthful status

```text
FP_060=COMPLETE
FP_180=SCOPED_REVIEW_PASS_FULL_PHASE_IN_PROGRESS
FP_190=SCOPED_IMMUTABLE_RUNTIME_PASS_FULL_PHASE_IN_PROGRESS
FP_200=COMPLETE
CANDIDATE_OUTCOME_RUNTIME_INTEGRATED=true
CANDIDATE_OUTCOME_MATURER_RUNTIME_INTEGRATED=true
CANDIDATE_OUTCOME_CALIBRATION_RUNTIME=PASS
CANDIDATE_RECORDING_COVERAGE=1.0
UNEXPLAINED_CANDIDATE_DROPS=0
UNEXPLAINED_MATURATION_DROPS=0
ARCHIVE_INVALID_ROWS=0
ARCHIVE_DUPLICATE_ROWS=0
COUNTERFACTUAL_COUNTS_AS_PAPER_PROFIT=false
ADAPTIVE_POLICY_AUTHORITATIVE=true
REFERENCE_PARITY_DISAGREEMENT_COUNT=0
NORMAL_PAPER_LIFECYCLE_COMPLETE=true
RESTART_RECONSTRUCTION_MATCH=true
ACCOUNTING_RECONCILED=true
G12=PASS_17_OF_17

FULL_FINAL_PASS_ENGINEERING_COMPLETE=false
ECONOMIC_ACCEPTANCE_PENDING=true
PAPER_SYSTEM_LIVE_END_TO_END=false
V2_PERMANENT_RECOVERY_COMPLETE=false
LIVE_NO_GO=true
paper_only=true
live_gate=blocked_human_only
routes_to_live=false
places_real_order=false
exchange_action_taken=false

FIRST_UNRESOLVED_STAGE=PHASE_1_TRADING_CONFIGURATION_CLASSIFICATION
NEXT_CONTROLLABLE_WORK=COMPLETE_TYPED_OUTCOME_TO_GEN5_JOIN_AND_REMAINING_ADAPTATION_PHASES
```

FP-020, FP-040, FP-050, FP-070 through FP-130, FP-150, FP-160, FP-170,
FP-180, FP-210, FP-220, FP-230, FP-240 and FP-250 remain open under their full
phase predicates. The typed-outcome→generation-5 exact identity overlap remains
0/382, and the required five-close economic cohort is still incomplete; those
facts prohibit a FINAL PASS or live-readiness claim.

## Authenticated adaptive dataset and challenger evaluation — authoritative update 2026-07-28

This section supersedes earlier statements that the typed-outcome/gen-5 corpus
join and FP-080 remain open. The completed design is an authenticated composite
corpus: gen-5 observations and independently matured typed candidate outcomes do
not need to share the same source identity, but every admitted row must satisfy
the same `ServingFeatureABIV2` builder, ordering, point-in-time, finality, cost,
label, lineage and receipt contracts. It does not supersede the open FP-020,
FP-070, FP-090 through FP-130, FP-150/160, FP-210/220/240/250 work.

### Completed task list

- [x] Reconcile the frozen gen-5 backfill: 386 rich-binding imports and 11
  exact sequence-bound rejections, with zero conflicting duplicates, no skipped
  source sequence, verified snapshot loads and serving-row construction.
- [x] Build the serving-compatible composite dataset from 382 authenticated
  gen-5 rows and 6,572 matured typed-outcome rows.
- [x] Authenticate all raw dataset, manifest, parity, base-dataset, terminal
  archive-chain and build-receipt bytes before tensor construction.
- [x] Bind exact row schemas, nested archive/high-water/split records, action and
  source counters, decision-group purge/embargo arithmetic, low-variance units,
  derivation semantics and candidate source/label lineage.
- [x] Reject duplicate JSON keys, non-finite values, symlink substitution,
  coherent public rehash/receipt-repin forgeries and immutable output collisions.
- [x] Make training deterministic, train-only calibrated, holdout-frozen,
  paper-only, non-promotable and non-live by construction.
- [x] Obtain independent Claude PASS on exact implementation SHA
  `7e8a153b78f26e51d19dad8ab5d7d7edd57b98a0`: 91 focused tests pass and
  34/34 coherent hostile mutations reject.
- [x] Run one real GPU challenger on the authenticated 6,954-row corpus without
  stopping trainers, restarting runtime services, or writing either model
  registry lane.
- [x] Reject the challenger under the frozen validation rule and retain the
  generation-3 paper checkpoint.

### Frozen evidence and decision

The FP-080 acceptance artifact is
`goal_state/ADAPTIVE_SYSTEM_FINAL_PASS/FP080_TYPED_OUTCOME_DATASET_ACCEPTANCE.json`
with SHA-256
`0d072b34e91752828b9f7ce362fbe006f15da2d4ef6ebbe10da10dc41fbb9399`.
The corpus contains 6,954 rows, split chronologically into 4,453 training,
1,321 validation and 1,180 holdout rows. It spans 161 symbols, 5m/15m/1h/4h,
2026-07-22 through 2026-07-28, and 1,472 LONG / 4,394 SHORT / 1,088 HOLD
targets. Duplicate rows, future-time violations, unproven finality, missing cost
evidence, missing label evidence and required-feature missingness are all zero.

The FP-100 attempt is frozen in
`goal_state/ADAPTIVE_SYSTEM_FINAL_PASS/FP100_AUTHENTICATED_CHALLENGER_EVALUATION.json`
with SHA-256
`b66859b8110ac6ef28aa3a549768789e397c01f95d0480915361088da6d49b91`.
Checkpoint
`SERVING_ABI_V2_PROFITABILITY_PAPER_202aff0bb36baad9a4c8884f` completed 400
optimizer steps with finite loss, exact ABI/builder parity, zero required-feature
missingness, both directional actions and train-only calibration containing
3,826 positive and 5,080 negative examples. Its immutable weight SHA-256 is
`419c65e206e0cf642daf4464c45f1a4f8b9cd6e109675bccc2e0d9c85ba5abf7`.

The challenger is not superior. Validation calibrated profitability Brier is
`0.26601150341700663`, worse than the frozen training-base-rate Brier
`0.1934555023908615`. The generated report therefore carries all three exact
blocks:

```text
RESEARCH_CHALLENGER_NOT_GOVERNED_FOR_ACTIVATION
VALIDATION_PROFITABILITY_BRIER_NOT_ABOVE_BASELINE
FRESH_GENERATION_SCOPED_ECONOMIC_CERTIFICATION_REQUIRED
```

`activation_eligible=false`, `checkpoint_promotable=false` and
`live_eligible=false`. The paper candidate registry remained empty, the active
registry remained generation 3 with checkpoint
`SERVING_ABI_V2_PAPER_f2f6e3b4c67a42b6c13880a4`, and canonical serving/paper
PIDs remained `3541449`/`3710798` with `NRestarts=0`. No runtime service or real
exchange path was touched.

### Verification and scoped command ledger

```text
git status --short --branch
git diff --check
git diff -- <scoped-loader-and-test-files>
git add -- <scoped-loader-and-test-files>
git diff --cached --check
git commit -m "Bind candidate derivation method semantics"
git rev-parse HEAD
sha256sum <loader/test/dataset/manifest/parity/receipt/checkpoint/report/bundle/evidence-files>
.venv/bin/python -m py_compile <loader/trainer/CLI/test-files>
.venv/bin/pytest -q <adaptive-dataset/calibration/ABI/model/trainer/CLI-selection>
.venv/bin/ruff check --select E902,F821,F822,F823 <scoped-files>
.venv/bin/python scripts/train_serving_profitability_v3_checkpoint.py --dataset <dataset> --manifest <manifest> --parity <parity> --build-receipt <receipt> --model-dir <unique-model-dir> --evidence-dir <unique-evidence-dir>
/usr/bin/time -v <same-training-command>
jq <scoped-training/dataset/registry/status-projections> <artifact>
nvidia-smi --query-gpu=index,name,memory.total,memory.used,utilization.gpu --format=csv,noheader
redis-cli --raw GET v2:model_registry:paper:active
redis-cli --raw GET v2:model_registry:paper:candidate
systemctl --user show ai-bot-v2-canonical-prediction-serving.service ai-bot-v2-trade-management-paper-loop.service -p Id -p ActiveState -p SubState -p MainPID -p NRestarts -p ExecMainCode -p ExecMainStatus
```

Combined local verification is 132/132 PASS. Independent verification is
91/91 PASS plus 34/34 hostile cases rejected. Python compilation, focused Ruff
and `git diff --check` pass. The unrelated pre-existing modification to
`.claude/hooks/block_dangerous.sh` remains preserved and uncommitted.

### Current truthful status after this attempt

```text
FP_080=COMPLETE
FP_090=IN_PROGRESS_CURRENT_SERVING_DISTRIBUTION_COMPARISON_OPEN
FP_100=IN_PROGRESS_FIRST_AUTHENTICATED_CHALLENGER_REJECTED_NOT_SUPERIOR
FP_180=SCOPED_TRAINER_AND_ARTIFACT_AUDIT_PASS_FULL_PHASE_IN_PROGRESS
AUTHENTICATED_ADAPTIVE_DATASET_ROWS=6954
AUTHENTICATED_TRAINING_ROWS=4453
AUTHENTICATED_VALIDATION_ROWS=1321
AUTHENTICATED_HOLDOUT_ROWS=1180
AUTHENTICATED_CHALLENGER_TRAINED=true
AUTHENTICATED_CHALLENGER_SUPERIOR=false
AUTHENTICATED_CHALLENGER_ACTIVATED=false
ACTIVE_PAPER_REGISTRY_GENERATION=3
ACTIVE_PAPER_CHECKPOINT_UNCHANGED=true
CHAMPION_CHALLENGER_LOOP_ACTIVE=false
AUTOMATIC_ESCALATION_LADDER_COMPLETE=false

FULL_FINAL_PASS_ENGINEERING_COMPLETE=false
ECONOMIC_ACCEPTANCE_PENDING=true
PAPER_SYSTEM_LIVE_END_TO_END=false
V2_PERMANENT_RECOVERY_COMPLETE=false
LIVE_NO_GO=true
paper_only=true
live_gate=blocked_human_only
routes_to_live=false
places_real_order=false
exchange_action_taken=false

FIRST_UNRESOLVED_STAGE=PHASE_1_TRADING_CONFIGURATION_CLASSIFICATION
NEXT_CONTROLLABLE_WORK=IMPLEMENT_AUTOMATIC_CHALLENGER_ESCALATION_AND_CONTINUE_FP020_FP070_FP090_FP110_FP120
```

## Authenticated rolling escalation dispatch — authoritative update 2026-07-28

This section supersedes the 6,954-row corpus as the latest training release and
records the second authenticated challenger attempt. It does not supersede the
open automatic-trigger, remaining-ladder, promotion, economic, or final
acceptance predicates.

### Completed task list

- [x] Create a domain-separated Ed25519-signed v3 build receipt over the exact
  rolling dataset, manifest, parity report, base dataset and candidate archive
  terminal chain.
- [x] Build and independently load the immutable 9,189-row release with
  chronological purge/embargo splits of 4,502 training, 2,802 validation and
  1,885 holdout rows.
- [x] Require exact plan/dataset identity and exact allowlisted worker descriptor
  before creating dispatch state or starting a process.
- [x] Persist private immutable start, terminal, stdout and stderr evidence under
  a content-addressed dispatch identity and a single-run lock.
- [x] Make non-consecutive A→B→A replay return A's immutable terminal evidence
  without executing a third process or overwriting the latest B state.
- [x] Recompute terminal result consistency and stdout/stderr hashes before an
  immutable receipt can advance the learning baseline.
- [x] Obtain independent PASS on exact commit `39ba18ae7d`: 59 focused, 125
  combined and 17 explicit adversarial cases pass.
- [x] Execute the negative-after-cost-edge recalibration rung once from immutable
  release `39ba18ae7d`; repeat invocation returned the same terminal receipt with
  `idempotent_replay=true` and did not train twice.
- [x] Independently audit the generated checkpoint and retain generation 3 after
  the governed superiority test failed.

### Signed release and dispatch evidence

The signed release is
`/home/wali/ai_bot_local_data/adaptive_candidate_dataset_v3/release_5821713e_20260728T1353Z`.
Its semantic dataset SHA-256 is
`d3183a5c52c8182b407d666a098e382caedcf5f56eccd34cd7081d9cec03b19a`,
manifest SHA-256 is
`d9ae369b475f28f5b678fde1ddff8f017561f0350502ffece89e7e991942b6d3`,
and signed build-receipt file SHA-256 is
`64170425f548424499cae457b3cdaca56fbbb6338ffc4dc456962c7e275ce624`.
Duplicate rows, future-time violations, unproven finality, missing cost evidence
and missing label evidence are all zero.

Dispatch `adaptive_dispatch_88f4524e45bc76f70b8585656e5eb5ae` completed
with return code zero, no timeout and no failure. The start and terminal receipt
SHA-256 values are `fcd11a340ffb17dcb7c2e5631126c7d7b0573cb27c7f60361fa6fd05796ef988`
and `e5b7150047112edc971f3e9a2fb6b13496389ea3bed004a43f88de8a33a2829e`.
The exact compact evidence artifact is
`goal_state/ADAPTIVE_SYSTEM_FINAL_PASS/FP110_AUTHENTICATED_ESCALATION_DISPATCH_20260728.json`,
SHA-256 `605a46ab47d1980fcb5c692345f806a7f2254b317632ec10a4d48dedf750a63f`.

### Truthful challenger decision

Checkpoint `SERVING_ABI_V2_PROFITABILITY_PAPER_e492d5c052d1c8d77c2e2028`
completed 400 optimizer steps with finite loss, exact ABI/builder parity, zero
required-feature missingness and train-only calibration containing both
directional actions, 3,862 positive outcomes and 5,142 negative outcomes.
Its checkpoint SHA-256 is
`7d5cc23cc5ba19befed966601bc9a5feb733f7edc07757942b8c97e1d7667c9e`.

The challenger is not superior. Calibration improves validation Brier from
`0.3614408` to `0.3588536`, but that remains worse than the frozen training
base-rate Brier `0.3192224`. Activation is therefore blocked by:

```text
RESEARCH_CHALLENGER_NOT_GOVERNED_FOR_ACTIVATION
VALIDATION_PROFITABILITY_BRIER_NOT_ABOVE_BASELINE
FRESH_GENERATION_SCOPED_ECONOMIC_CERTIFICATION_REQUIRED
```

The active registry remains generation 3 at checkpoint
`SERVING_ABI_V2_PAPER_f2f6e3b4c67a42b6c13880a4`; the paper candidate key does
not exist. Canonical serving, paper loop and candidate-outcome publisher retain
their prior PIDs with `NRestarts=0`. No runtime service was restarted.

### Current truthful status

```text
FP_080=COMPLETE_LATEST_SIGNED_ROWS_9189
FP_100=IN_PROGRESS_SECOND_AUTHENTICATED_CHALLENGER_REJECTED_NOT_SUPERIOR
FP_110=IN_PROGRESS_DURABLE_DISPATCH_PROVEN_AUTOMATIC_RUNTIME_TRIGGERING_INCOMPLETE
FP_120=PENDING_NO_SUPERIOR_CHALLENGER
FP_160=IN_PROGRESS_AUTHENTICATED_DISPATCH_PROVEN_FULL_SELF_HEALING_INCOMPLETE
FP_180=SCOPED_DISPATCH_AND_ARTIFACT_AUDIT_PASS_FULL_PHASE_IN_PROGRESS
AUTHENTICATED_CHALLENGER_ACTIVATED=false
ACTIVE_PAPER_REGISTRY_GENERATION=3
ACTIVE_PAPER_CHECKPOINT_UNCHANGED=true
AUTOMATIC_ESCALATION_LADDER_COMPLETE=false

FULL_FINAL_PASS_ENGINEERING_COMPLETE=false
ECONOMIC_ACCEPTANCE_PENDING=true
PAPER_SYSTEM_LIVE_END_TO_END=false
V2_PERMANENT_RECOVERY_COMPLETE=false
LIVE_NO_GO=true
paper_only=true
live_gate=blocked_human_only
routes_to_live=false
places_real_order=false
exchange_action_taken=false

NEXT_CONTROLLABLE_WORK=BIND_TRUSTED_RUNTIME_FAILURE_SIGNALS_AND_ADVANCE_REMAINING_ESCALATION_RUNGS
```

## d185 runtime stabilization and adaptive continuation — authoritative update 2026-07-28

This section supersedes the prior failed-oneshot and stale-boot state. It does
not supersede the incomplete frozen economic cohort or authorize live trading.
Exact machine-readable evidence is
`goal_state/PERMANENT_SYSTEM_RECOVERY/d185_runtime_stabilization_acceptance_20260728.json`
(SHA-256 `3bc771f3c9b16afeff622168ba8113fbc7592a08b4f83570618b158f0af5d56f`).

### Completed task list

- [x] Classify and rerun all three failed units only after their dependencies
  and evidence heartbeats were fresh.
- [x] Prove the boot-validator failure was a graceful-switch dependency race,
  then rerun unchanged validation to exit status 0 with no failures.
- [x] Prove the adaptive-escalation SIGTERM was the prior requested closeout
  interruption, then complete its authenticated bounded run with exit status 0.
- [x] Repair the replay miner's genuine OOM producer defect with bounded
  streaming projection/pruning and separate immutable-code/runtime-evidence
  roots; complete both migration and steady-state runs with exit status 0.
- [x] Restore both enabled evidence/adaptation timers.
- [x] Observe three new cycles anchored after the `d185c2a70d` paper-loop
  restart. All passed proof, duplicate, leak, conservation, epoch and safety
  predicates.
- [x] Prove 106/106 current intents preserve authenticated execution-trust
  projections into typed `AdaptivePolicyActionV2`; the independent shadow
  evaluated the same cycle with zero production/reference disagreements.
- [x] Re-run the directional conservative microstructure-consumption fixtures:
  2/2 selected tests pass. FLAT actions intentionally report zero execution
  cost because they submit nothing; directional actions consume the required
  conservative min/max estimates.
- [x] Re-run G12: 17 PASS, 0 FAIL, 0 WARNING.
- [x] Run user-unit verification over the changed services and timers: zero
  diagnostics and zero ordering cycles.
- [x] Confirm the failed-unit set is empty and all changed services have
  `NRestarts=0` after stabilization.
- [x] Keep the current-epoch lifecycle controller active and fail-closed while
  waiting for the first proof-backed natural position.

### Exact failure classification and final state

| Unit | Initial failure | Classification | Final state |
|---|---|---|---|
| `ai-bot-v2-boot-validator.service` | exit 1 while the paper loop was `deactivating/stop-sigterm` | transient dependency settling | successful oneshot, exit 0, failures `[]` |
| `ai-bot-v2-adaptive-escalation-runtime.service` | signal 15 from requested closeout interruption | transient dependency settling | successful oneshot, exit 0, peak 5,442,740,224 bytes, timer active |
| `ai-bot-v2-post-hoc-replay-outcome-miner.service` | OOM kill, signal 9, 12,884,901,888-byte peak | real producer defect | migration and steady-state runs successful, exit 0, timer active |

The replay defect was a 7,308,006,627-byte pending archive combined with
unbounded list materialization, duplicated authority matrices and whole-file
mirroring. Commits `849d44b53c56302a29f085ce3034e6845c5dfb4d` and
`f5f444bad8b2f283d44fa295ebcbd37801c0c0cd` repair the producer without
relaxing a validator or changing trading policy.

The adaptive run rebuilt a signed 18,914-row release (8,392 train, 4,061
validation, 6,461 holdout), with zero duplicate rows, future-time rejections,
unproven finality, missing cost evidence or missing label evidence. It completed
the representation, horizon-specific and symbol/regime challenger steps. The
next automatic rung is `TRAIN_ALTERNATIVE_MODEL_ARCHITECTURES`; no challenger
was promoted and generation 3 remains active.

### Current paper and safety truth

```text
paper_session_id=paper_session_140989e198032b94
paper_account_epoch=1
starting_equity_usd=3000.00
wallet_balance_usd=3000.00
equity_usd=3000.00
free_margin_usd=3000.00
used_margin_usd=0.00
reserved_margin_usd=0.00
accepted_fills=0
open_positions=0
current_session_closed_trades=0
pending_reservations=0
proof_store_initialized=true
proof_store_backfill_complete=true
unproved_positions=0
duplicate_fills=0
duplicate_closes=0
reservation_leaks=0
wallet_equity_margin_conservation=true

boot_validator=PASS_EXIT_STATUS_0
systemd_diagnostics=0
ordering_cycles=0
failed_user_units=0
changed_services_NRestarts=0
G12=PASS_17_OF_17

lifecycle_observer=ACTIVE_WAITING_FOR_NATURAL_CURRENT_EPOCH_POSITION
current_epoch_natural_lifecycles=0
economic_cohort_natural_closes=1
economic_cohort_required_closes=5
G03=FAIL
G11=FAIL
G13=FAIL
G14=FAIL

paper_only=true
live_gate=blocked_human_only
routes_to_live=false
places_real_order=false
exchange_action_taken=false
V2_PERMANENT_RECOVERY_COMPLETE=false
LIVE_NO_GO=true
```

The paper stack is stable and the lifecycle controller remains armed. A current
epoch natural lifecycle and four additional eligible frozen-cohort closes have
not occurred. Historical losses are unchanged and the clean $3,000 operational
epoch is not counted as economic certification.
