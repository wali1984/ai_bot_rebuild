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
owner=CODEX_ADVERSARIAL_AUDITOR_AND_CO_FIXER
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
| FP-020 | 1 | Classify every trading-affecting value and remove manual Category-E final authority | Claude/Codex | IN_PROGRESS | Scanner v2 `3f138f17e8` deterministically finds 25,416 worktree candidates across seven source kinds with 0 duplicates; all remain unclassified, runtime reachability and authority removal remain |
| FP-030 | 2 | Define and verify `AdaptivePolicyActionV2` | Claude/Codex | COMPLETE | Canonical contract `0980e69210`, duplicate removed `658d6fc760`; 45 tests and independent SHA review PASS |
| FP-040 | 3 | Convert component vetoes into calibrated continuous estimates | Claude/Codex | IN_PROGRESS | Shadow schema/projector accepted at `2934dcff31` + `5ce083874d`; calibrated producers and authority cutover remain |
| FP-050 | 4 | Implement portfolio after-cost objective and adaptive exploration allocation | Claude/Codex | IN_PROGRESS | Independently accepted shadow foundation `d12f418d3d`; authenticated hard-validation evidence, exact PIT/lineage/units, self-recomputing scores, nonterminal flat-collapse signals, and bounded positive-utility information seeking; runtime fitting and policy integration remain |
| FP-060 | 5 | Build `CandidateDecisionOutcomeV2` and point-in-time matured labels | Claude/Codex | IN_PROGRESS | Independently accepted contract foundation `289bb9911f`; runtime archive/maturation writers, CAS/idempotency, authenticity, and 100% coverage remain |
| FP-070 | 6 | Attribute gate performance and missed opportunity cost | Claude/Codex | PENDING | Exact segmented false-positive/negative, avoided-loss, and opportunity-cost evidence |
| FP-080 | 7 | Build complete eligible-data funnel and repair corpus utilization | Claude/Codex | PENDING | Funnel published; every exclusion exact; all eligible data used |
| FP-090 | 8 | Verify one shared, point-in-time-safe train/serve representation | Claude/Codex | PENDING | ABI/builder hashes and per-feature parity pass; leakage rejections pass |
| FP-100 | 9 | Train and compare diversified model and strategy challengers | Claude/Codex | PENDING | Evidence-backed comparison across declared algorithms and strategy families |
| FP-110 | 10 | Implement automatic adaptation-escalation state machine | Claude/Codex | PENDING | Negative edge, starvation, flat collapse, and drift advance the ladder automatically |
| FP-120 | 11 | Verify champion/challenger promotion, rollback, and serving independence | Claude/Codex | PENDING | Atomic receipts, superior-evidence promotion, rollback, trainer independence |
| FP-130 | 12 | Implement venue-executable bounded information-seeking exploration | Claude/Codex | IN_PROGRESS | Exact non-authoritative venue-minimum primitive through `2b7442e61a`; opportunity selection and runtime integration remain |
| FP-140 | 13 | Integrate unified policy with hard-only validator and paper portfolio engine | Claude/Codex | PENDING | Validator checks only authorization, integrity, physical, accounting, and outer limits |
| FP-150 | 14 | Remove duplicated policy authority and prove reference parity | Claude/Codex | PENDING | One final adaptive authority; production/reference disagreements 0 |
| FP-160 | 15 | Implement adaptive self-healing supervisor | Claude/Codex | PENDING | Every declared collapse/failure state produces a bounded repair or learning action |
| FP-170 | 16 | Record Claude implementation commits and acceptance claims | Claude | PENDING | Each material SHA and claim recorded in `CLAUDE_PROGRESS.jsonl` |
| FP-180 | 17 | Perform Codex adversarial audit, fixtures, co-fixes, and SHA review | Codex | PENDING | Required adversarial fixtures pass and reviewed SHAs have PASS records |
| FP-190 | 18 | Verify shadow-first immutable deployment and writer uniqueness | Codex | PENDING | Immutable SHAs, heartbeats, rollback, NRestarts, and one authority writer proven |
| FP-200 | 19 | Complete natural lifecycle, restart reconstruction, and two further cycles | Joint | PENDING | Natural fill/open/stop/restart/close/accounting predicates all pass |
| FP-210 | 20 | Pass frozen-cohort G03/G11/G12/G13/G14 with automatic challenger escalation | Joint | PENDING | Same cohort passes all gates without deleting, relabeling, or hiding losses |
| FP-220 | 21 | Decommission obsolete policy authority | Claude/Codex | PENDING | Temporary/static authorities disabled; safety validators and evidence preserved |
| FP-230 | Tests | Run changed-path, adversarial, G12, systemd, lint, compilation, and release checks | Codex | PENDING | Changed-path failures 0; errors 0; systemd diagnostics 0 |
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

## Current final status

This block must be updated whenever work stops or final acceptance changes.

```text
FINAL_PASS_STATUS=IN_PROGRESS
FINAL_ACCEPTANCE=NOT_YET_EVALUATED
FIRST_UNRESOLVED_STAGE=PHASE_1_TRADING_CONFIGURATION_CLASSIFICATION

CLAUDE_IMPLEMENTATION_COMPLETE=false
CODEX_INDEPENDENT_AUDIT_PASS=false

PAPER_SYSTEM_LIVE_END_TO_END=false
ADAPTIVE_LEARNING_LOOP_ACTIVE=NOT_YET_PROVEN
ADAPTIVE_POLICY_CONTROLS_TRADING_ACTIONS=NOT_YET_PROVEN
STATIC_TRADING_ACTION_THRESHOLDS_WITH_FINAL_AUTHORITY=NOT_YET_PROVEN_ZERO
TRAINING_USES_ALL_ELIGIBLE_DATA=NOT_YET_PROVEN
REJECTED_CANDIDATES_ARE_LABELED=NOT_YET_PROVEN
CHAMPION_CHALLENGER_LOOP_ACTIVE=NOT_YET_PROVEN
RESTART_RECONSTRUCTION_MATCH=false
NORMAL_PAPER_LIFECYCLE_COMPLETE=false
G03=NOT_EVALUATED_FOR_FINAL_PASS
G11=NOT_EVALUATED_FOR_FINAL_PASS
G12=LAST_RECORDED_PASS_17_OF_17_REVALIDATION_PENDING
G13=NOT_EVALUATED_FOR_FINAL_PASS
G14=NOT_EVALUATED_FOR_FINAL_PASS

V2_PERMANENT_RECOVERY_COMPLETE=false
LIVE_NO_GO_FOR_REAL_EXCHANGE=true
paper_only=true
live_gate=blocked_human_only
routes_to_live=false
places_real_order=false
exchange_action_taken=false

OPERATOR_ACTION_REQUIRED=NONE_WHILE_CONTROLLABLE_ENGINEERING_WORK_REMAINS
LATEST_REPOSITORY_CHECKPOINT=289bb9911f
LATEST_FOCUSED_FOUNDATION_TESTS=208_ADAPTIVE_FOUNDATIONS_PLUS_11_SCANNER_PASS
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
