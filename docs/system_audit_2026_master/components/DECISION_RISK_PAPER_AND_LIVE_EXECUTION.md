# Decision, risk, paper and live-execution internals

> **2026-07-17 source/runtime addendum:** the ordinary A+ risk-authority defect and effective confidence fast paths described below have source-level mitigations; paper position generation, capital equations, and a deterministic account-wide current-cycle reservation pass were added. The trainer no longer writes canonical decision/index keys and labels its previews `TRAINER_NON_AUTHORITATIVE_PROPOSAL`; canonical risk belongs to the gateway, while paper-specific policy and canonical per-ID orchestrator persistence remain incomplete. Executed open-position notional and whole-position bracket maintenance evidence now govern margin; recommendation-only leverage cannot reduce it, and current reconciliation does not rewrite `adaptive_allocation`. Lifecycle maintenance is `max(0, mark_notional*maintMarginRatio-cum)` and same-side fills never weight per-fill rates. The margin pass is process-local—not a durable Redis transaction—and no account-wide margin-call/cascade engine is proven. Paper envelope risk never grows above base and leverage above the default 3x base requires positive after-cost/PIT/context evidence. Source now derives/wires that contract, but its receipt is incomplete/unpersisted, the envelope has no reason result, and no attributable restart proof shows >base flow. Halted-probe cycle-local token finalization/release is repaired, but exact-generation outcome/timing governance remains P0; unsafe deferred hedging is runtime-interlocked and produced a fresh disabled status. The connector itself is exact account/environment scoped and separately HMAC authenticated. Independent glue/PIT audits exposed high-water overshoot, lifecycle provenance, Tier-0 exit, cross/isolated, decision-time, alias, component-clock, and full-run defects. Current source blocks high-water/more-restrictive-tier violations, derives mark-to-liquidation distance, reconciles all paper execution to isolated simulation, requires complete structural/temporal bracket provenance, captures/checks 47 component clocks, and normalizes nested/raw/flat lifecycle schemas. It still lacks lifecycle cryptographic HMAC recomputation or a sealed typed receipt, advanced-indicator strict-receipt proof, full `run_once`, broad post-audit regression, poller, and runtime evidence. The canonical current delta, equations, Redis ownership map and remaining blockers are in [../ADAPTIVE_END_TO_END_CONTROL_AND_ACCOUNTING_2026-07-17.md](../ADAPTIVE_END_TO_END_CONTROL_AND_ACCOUNTING_2026-07-17.md). Keep the historical trace below because it explains the blast radius; do not read it as the current worktree's intended behavior.

**Audit basis:** source trace plus read-only runtime/Redis/log evidence on 2026-07-16

**Safety:** current deployment was non-live and disarmed. Real exchange mutation source exists. This document explains it; it does not authorize editing, enabling or testing it.

## 1. Control-plane overview

```text
native model prediction
  → trainer publisher / per-symbol-timeframe prediction
  → all-timeframe signal publisher
  → orchestrator candidate/arbitration
       ├─ emits proposal/paper signal with provisional risk ID/flags
       └─ risk gateway independently emits ALLOW/DENY record
  → paper loop joins proposal and risk record
  → strategy/pretrade/fee/A+/temporal/tier/sizing/churn/freeze gates
  → admission/lifecycle/accounting
  → open/closed positions, portfolio, outcome/replay/feedback

separate dormant live branch:
  exact approved decision/risk + release/live/armed/symbol/notional/filter/state
  → Binance WebSocket order.place
```

The intended architecture says risk is final authority. Current ordinary paper code does not enforce that invariant. The live transport is more fail-closed than the paper path.

## 2. Principal source authorities

| Role | Primary source |
|---|---|
| Prediction construction/publication | `services/native_trainer/hybrid_cuda_trainer/publisher.py`, `runtime.py` |
| Aggregation/public signal | `cli/v2_all_timeframe_prediction_signal_price_target_publisher.py` and related publisher services |
| Orchestrator | `cli/v2_orchestrator_arbitration_loop.py` |
| Risk gateway | `cli/v2_risk_gateway_live_loop.py` plus risk services/contracts |
| Paper owner | `cli/v2_trade_management_paper_loop.py` |
| Paper subservices | `services/paper_trade_management/*`, `services/trade_management_paper/*`, `services/paper_exploration/*` |
| Portfolio | `cli/v2_portfolio_state_publisher.py` |
| Cascade guard | `cli/v2_portfolio_cascade_guard_loop.py` |
| Edge guardian | `services/continuous_edge_guardian/guardian.py` |
| Position state machine | domain/execution/live-gate position validation services |
| Live transport | `services/live_gate/binance_live_order_transport.py` |

The paper loop is approximately 34,000 lines, has more than 500 top-level symbols and a `run_once` spanning thousands of lines. It is the highest behavioral blast-radius file in the system.

## 3. Prediction-to-proposal contract

A candidate should carry:

- symbol/timeframe/side/action;
- action probabilities, expected move and calibrated confidence;
- model/checkpoint/feature snapshot/tensor IDs;
- prediction and decision IDs;
- source event/available/cutoff/decision times;
- replay/archive write evidence;
- cost/edge and target prices;
- trust classification and block reasons;
- live-block/non-mutation declarations.

The publisher currently has a separate fail-open publication defect: failure mutations occur on a copied payload, its boolean is ignored, and original lineage can continue. Decision-plane consumers must therefore not equate a prediction/lineage ID with successful durable publication.

## 4. Orchestrator behavior

The orchestrator normalizes predictions, groups/arbitrates them and produces selected candidates. Source around `v2_orchestrator_arbitration_loop.py:744-812` constructs lineage including a provisional `risk_decision_id` and sets `paper_fill_allowed=True` before the risk gateway evaluates the proposal.

Correct semantic interpretation:

```text
orchestrator output = proposal selected for risk evaluation
risk_decision_id = correlation key for an expected/matched decision
paper_fill_allowed on proposal = upstream preference, not final approval
```

Current downstream code sometimes treats these as approval-like. Any schema correction must coordinate every paper/exploration/live/client consumer rather than merely rename a field.

## 5. Risk gateway behavior

The gateway loop around `v2_risk_gateway_live_loop.py:567-658` emits a distinct decision record. In the audited non-live state it creates deny results for live-disabled and missing/invalid market-state conditions. A risk record needs:

- exact proposal/prediction correlation;
- action `ALLOW` or `DENY`;
- reason set and evaluated policy version;
- decision/generated time;
- data/model/portfolio inputs and hashes;
- expiry/freshness;
- immutable identity.

An ID is not an allow. A complete lineage record with `action=DENY` is still denial.

## 6. Proven risk-to-paper authority defect

The trace is:

1. Orchestrator pre-creates a risk ID and upstream fill flag (`v2_orchestrator_arbitration_loop.py:744-812`).
2. Risk gateway independently writes `DENY` (`v2_risk_gateway_live_loop.py:567-658`).
3. `_paper_policy_intent_decision_dereference` correctly resolves the per-ID decision (`v2_trade_management_paper_loop.py:21938-22122`, called around `:28720-28732`). It records a denial-like `risk_controller_decision`.
4. The ordinary A+ gate builds a synthetic result around `:29193-29199` using:

   ```python
   bool(lineage.get("risk_decision_id")) and pre["allowed"] is True
   ```

5. `_classify_paper_opportunity_tier` (`:16738-17646`) does not require the resolved risk action. Its ordinary upstream A-grade branch around `:17167-17210` uses upstream paper-fill flag plus local gate truth.
6. The active owner-open guard around `:8541-8622` and general validators require identifiers/lineage but do not universally assert risk allow.
7. Exploration policy around `services/paper_exploration/policy.py:1434-1469` does explicitly require allow, so admission paths disagree.
8. Some owner checks recognize block/no-trade/reject strings but not a `DENY:*` value.

Result:

```text
risk_action = DENY
risk decision is matched and retained
ordinary paper risk_result.allowed = true because ID exists and pre-trade passed
fill can proceed
```

Runtime Redis evidence showed proposals marked paper-fill-allowed while matching risk records were deny. This is not merely a documentation mismatch.

## 7. Paper candidate processing sequence

The central `run_once` path conceptually performs:

1. read current paper/trainer/orchestrator/portfolio/guardian/runtime state;
2. normalize proposal and lineage;
3. dereference prediction/risk/policy state;
4. build strategy-router and pre-trade/cost results;
5. evaluate trust/runtime market evidence;
6. evaluate A+, one-minute and signal temporal gates;
7. classify opportunity tier and execution preference;
8. resolve sizing/leverage/margin/capital state;
9. reject direction concentration/churn/freeze/preemptive loss risk;
10. validate paper fill write and position transition;
11. materialize candidate/fill/lifecycle state;
12. reconcile/dedupe/net positions and exits;
13. compute accounting/outcome/PPO feedback fields;
14. write Redis/public/worklog status and evidence.

There are multiple early and late filters rather than one immutable admission decision. Broad exception handling and mutable dictionaries make proof difficult.

## 8. Current overrides in execution order

These were in the audited source; line numbers move as the active file changes.

| Order | Source area | Effective behavior | Consequence |
|---:|---|---|---|
| 1 | `:27773-27778` | exploration supply bridge replaced by `TEMPORARILY_DISABLED_TO_UNBLOCK_TRADING` status | supply/owner behavior differs from design |
| 2 | `:28225-28230` | confidence ≥0.70 converts strategy-router denial to allow | original strategy/risk reason can be discarded |
| 3 | `:28252-28306` | missing edge + confidence ≥0.70 allows pre-trade and directly assigns frozen fee result | repeated `FrozenInstanceError` observed |
| 4 | `:28307-28313` | confidence ≥0.70 converts general pre-trade denial | denial reason is not classified for relaxability |
| 5 | `:28314-28345` | confidence ≥0.75 expands allowed fee/edge ratio, mutating frozen object with `object.__setattr__` | economic policy changes by confidence |
| 6 | `:29211-29236` | failed A+ becomes true if entry gate passed and confidence ≥0.50 | stored A+ snapshot can remain false while effective result is true |
| 7 | `:29269-29274` | confidence ≥0.75 allows failed one-minute strict gate | strict timing/market rule relaxed |
| 8 | `:29275-29281` | confidence ≥0.75 clears the entire temporal-rejection list | not limited to “slight” staleness |
| 9 | `:29282-29300` | fee block logged but omitted from local conjunction | fee is advisory for strict local pass |
| 10 | `:29755-29798` | confidence ≥0.65 fast path accepts and `continue`s | skips downstream authorities/invariants |
| 11 | `:29828-29854` | confidence ≥0.70 overrides tier non-fill | often shadowed by earlier fast path |
| 12 | `:29908-29921` | directional guard blocks only below 0.70 | concentration protection relaxed |
| 13 | `:29922-29931` | incomplete sizing blocks only below 0.70 | fill can lack complete allocator evidence |
| 14 | `:29932-29943` | duplicate/churn blocks only below 0.70 | same prediction/signal/candle can re-enter |
| 15 | `:29967-30027` | portfolio entry freeze can be bypassed at ≥0.70 | new risk while portfolio truth says freeze |
| 16 | helper `:15447-15511` | missing loss probability ignored at ≥0.75 | preemptive evidence requirement relaxed |

The override thresholds are strategy/risk/training behavior. They are not harmless tuning or display settings.

## 9. Fast-path skipped checks

The confidence ≥0.65 branch appends an accepted row and exits the candidate path before:

- final upstream-strict versus permitted-local-tier enforcement;
- directional-collapse guard;
- allocator sizing-completeness guard;
- duplicate prediction, duplicate signal and same-candle/current-cycle churn checks;
- portfolio-truth new-entry freeze;
- `_paper_preemptive_admission_rejection_reasons`;
- `validate_paper_fill_write_invariant`;
- economic/accounting-blocker annotation;
- PPO entry-time old log probability, old value, rollout and trajectory stamping.

Later post-backfill churn filtering, lifecycle reconciliation, post-lifecycle churn and non-relaxable-entry quarantine remain around `:30330-30415`. They catch subsets; they do not re-execute every omitted gate, enforce general risk allow or reconstruct missing PPO fields.

Change impact:

- admitted positions/exposure;
- lifecycle/dedupe/netting;
- portfolio/PnL;
- closed outcomes and feedback;
- whether rows qualify as on-policy PPO;
- dashboard accepted/rejected counts;
- future model weights and promotion evidence.

## 10. Frozen fee-gate exception

`FeeRatioGateResult` is `@dataclass(frozen=True)` in `services/trade_management_paper/service.py:126-133`. The missing-edge override attempts normal assignment to `blocked`. That raises `dataclasses.FrozenInstanceError`; repeated tracebacks were present in the active error log.

Do not “fix” this by making the result mutable without reviewing the policy. The deeper question is whether a missing-edge or fee denial may be relaxed, which reasons are non-relaxable, and whether mutation should be represented as a new audited decision rather than rewriting evidence.

## 11. Temporal gates in paper execution

Paper runtime market-evidence validation separately checks important future/finality conditions. The confidence temporal override observed around `:29275` concerns signal temporal rejection output and should not be overstated as bypassing every core feature-future check.

Nevertheless, current feature enrichment can already lose upstream per-source availability, so a local paper gate cannot restore lineage that was never preserved.

Every admission must require:

```text
all source available_at <= model_decision_time
truthful feature_cutoff <= model_decision_time
model_decision_time <= paper_admission_decision_time
signal generated/available time <= paper_admission_decision_time < signal expiry/freshness deadline
paper_admission_decision_time <= execution_time
candle finality for every timeframe used
```

These are stage-specific fields, not interchangeable aliases. `model_decision_time`
is the time at which the model output/action was fixed; the paper loop derives it
from the model/entry-feature/prediction decision fields. `paper_admission_decision_time`
is the later paper admission and runtime-cost-capture instant. Signal age, current
source status, and expiry/freshness must be evaluated against that admission
instant. A generic mutable `decision_time` fallback must not erase either stage.
The current field derivation and signal-age checks are visible at
`v2/backend/app/cli/v2_trade_management_paper_loop.py:7585-7593`,
`:7922-7927`, `:7974-7978`, and `:25765-25818`.

## 12. Position state and lifecycle

The paper subsystem includes modules for:

- entry-gate and validity checks;
- lifecycle reconciliation;
- net position and direction state;
- exit policy;
- accounting/economic fill classification;
- dedupe/netting and side performance;
- outcome generation/updating;
- policy funding repair and telemetry.

The smaller `services/trade_management_paper/service.py` explicitly remains a partial port; hedge/DCA areas include fail-closed stubs.

Required state-machine invariant:

```text
FLAT → LONG/SHORT        valid open
LONG/SHORT → FLAT        valid close
LONG → LONG or SHORT → SHORT without defined add/replace transition  invalid
LONG ↔ SHORT without atomic close-then-open transition               invalid
duplicate fill/retry against same decision                            invalid
```

An invalid transition must fail before any paper or live order/fill boundary. Identifier presence does not prove transition validity.

## 13. Paper state writes and authority

The exact Redis key set is large and generated in `atlas/REDIS_KEY_USAGE_REGISTRY.json`. Contract families include:

- orchestrator proposals/decisions;
- risk gateway decisions and per-ID lookups;
- paper signals/intents;
- accepted/rejected candidate matrices and reasons;
- ledger/open/closed positions;
- lifecycle state and dedupe/churn indexes;
- portfolio state;
- feedback/trusted replay;
- status/heartbeat/public artifacts.

For every key define one writer authority, type/schema, IDs, temporal fields, TTL, atomicity and recovery. The current system often writes related surfaces independently, allowing partial state.

## 14. Portfolio and cascade guard

`v2_portfolio_state_publisher.py`:

- reads paper ledger/session/accepted-fill state;
- filters invalid-admission lineage;
- resolves current V2 prices;
- recomputes positions/equity/PnL;
- writes `v2:portfolio:state` with a 900-second TTL and a public artifact;
- falls back to nominal 10,000 initial capital if session truth is missing;
- uses a fixed UTC−4 object named EST, not a daylight-saving-aware zone.

Two identical publisher processes were observed, so last-writer behavior and duplicate work must be resolved.

`v2_portfolio_cascade_guard_loop.py` reads open paper positions and short-timeframe cascade state, emits `CLOSE` for losing/cascade or worst-case liquidation conditions and `RIDE_TIGHTEN` for some winners. It writes an intent key; lifecycle consumes close. Redis write errors are swallowed, so absence can mean “no event” or “write failed.”

## 15. Continuous edge guardian

`services/continuous_edge_guardian/guardian.py` is a large evidence aggregator. It reads many disk products, computes economic/model/strategy/capital/trajectory/holdout gates, mirrors artifacts and publishes status/A-grade Redis keys. It does not submit orders.

Disk artifacts and Redis can have different ages. Every guardian block/pass must include source generated time and provenance; otherwise a derived gate can lag current truth.

## 16. Outcomes, replay and trainer feedback impact

A filled/closed trade is not automatically a clean training row. Before feedback consumption require:

- no risk deny;
- no fast-path omission of required gates;
- valid position transition;
- complete fill/lifecycle/accounting receipt;
- feature/archive/replay durability;
- correct temporal lineage;
- cost/label schema version;
- on-policy entry fields if PPO is claimed;
- finalized outcome horizon;
- no holdout contamination.

Rows affected by current defects should remain immutable historical evidence but be quarantined from performance/promotion and training.

## 17. Live order transport

`services/live_gate/binance_live_order_transport.py` implements a real Binance WebSocket order path with:

- release/live-mode check;
- armed-state check;
- allowed symbol scope;
- decision/prediction/risk lineage validation;
- explicit risk-action validation;
- quantity/notional/order-type bounds;
- exchange step/tick/filter handling;
- position-state-machine validation;
- dedupe/idempotency/write guards;
- request timeout and response classification;
- runtime execution-state persistence;
- WebSocket `order.place` mutation.

At audit time:

- effective `V2_RELEASE_MODE` was absent/non-live;
- live gate was blocked/disarmed;
- no active service called real submit;
- no active process was authorized to place a real order.

But dormant CLI/API callers exist. `v2_trader_runtime_loop` defaults `dry_run=False` despite observer-like naming. The safety statement must be re-audited after any unit enablement, environment, release-mode or caller change.

## 18. Live boundary rules

No source/runtime change may weaken:

1. explicit release and armed state;
2. exact operator-approved symbol set;
3. matched, current risk `ALLOW` for exact proposal hash;
4. valid state-machine transition;
5. order/notional/filter limits;
6. dedupe/idempotency;
7. credential isolation;
8. audit/execution receipt;
9. kill/disarm behavior;
10. paper/live separation.

Any edit to this boundary or a caller requires explicit operator approval and fake-adapter/negative tests before any controlled external test.

## 19. Failure modes and observability

| Failure | Current risk | Required signal |
|---|---|---|
| prediction/archive write fails | lineage can continue | typed publication failure and zero downstream writes |
| risk decision missing | fallback/provisional IDs can obscure absence | explicit missing/mismatch denial |
| risk action deny | ordinary paper can ignore action | sole boundary counter/assertion |
| strategy/pre-trade denied | confidence can rewrite | original/effective decision with approved override policy |
| temporal rejection | whole list can be cleared | reason-specific non-relaxable classification |
| fee result mutation | frozen assignment crash | exception count/candidate quarantine |
| fast path | later checks absent | explicit path ID and skipped-stage bitmap; target should remove |
| partial Redis writes | truth planes diverge | transaction/result receipt and reconciliation |
| invalid transition | may reach late filters | pre-write state-machine assertion |
| guardian artifact stale | gate disagrees with runtime | source age/provenance |
| live caller activated | safety conclusion changes | installed/active caller inventory and release/armed audit |

Broad `except`/pass behavior in this subsystem means missing status cannot be assumed benign.

## 20. Change-impact guide

### Change orchestrator schema

Review all-timeframe publisher, orchestrator, risk gateway, paper dereference/classifier, exploration owner, live transport, lifecycle, Redis keys, API/UI and tests. Provisional flags must not retain approval-sounding names without compatibility handling.

### Change risk semantics

Review the matched record writer and every consumer. Require `ALLOW` at paper and live boundary. Test deny, missing, stale, wrong symbol/side/time, duplicate and mismatched hashes.

### Change confidence/edge/fee/A+/tier

This is strategy/risk behavior. Review every override and fast path, cost/label consistency, sizing/exposure, closed outcomes, feedback/replay, guardian and promotion. Explicit approval required.

### Change paper loop function

Use `atlas/CHANGE_IMPACT_INDEX.json`, but also trace mutable shared dictionaries and source order inside `run_once`; a direct caller graph alone cannot capture branch/continue effects. Run isolated branch-complete tests with fake Redis/state.

### Change lifecycle/position contract

Review paper entry/exit/netting/dedupe/accounting/portfolio/outcome and live transport state machine together. Test invalid transitions fail before all mutation boundaries.

### Change Redis key or TTL

Review writers/readers/scan patterns, partial-write reconciliation, public artifacts, memory/eviction, retention and recovery. Current Redis capacity makes unbounded additions high risk.

## 21. Required corrective design tests

Without prescribing an unauthorized implementation, closure evidence must include:

- risk `DENY` cannot materialize any ordinary/exploration/live fill;
- risk ID presence without record/action cannot pass;
- exact proposal/risk hash mismatch fails;
- every candidate reaches one fill invariant and state-machine validator;
- no confidence value bypasses non-relaxable temporal/risk/position/cost requirements;
- missing edge/fee/loss evidence follows explicit policy without mutating prior results;
- duplicate/current-candle/churn/freeze cases fail as specified;
- archive/replay/prediction partial failures emit no downstream lineage;
- PPO-designated fills contain complete entry fields before close feedback;
- partial Redis/lifecycle/accounting failures reconcile or fail closed;
- paper tests never touch real runtime state;
- real transport tests use fake adapters and cannot reach an exchange.

## 22. Reconstructing this subsystem

A faithful safe copy needs:

1. immutable `Prediction` with exact model/data identity;
2. immutable `OrchestratorProposal`, explicitly not approval;
3. immutable `RiskDecision` matched to proposal hash;
4. one `PaperAdmissionDecision` requiring risk allow and every policy/invariant;
5. one idempotent fill-write transaction/receipt;
6. one explicit position state machine shared by paper/live;
7. lifecycle/accounting/outcome transactions and reconciliation;
8. quarantine/versioning for historical defective rows;
9. dormant/masked live adapter with separate explicit authorization;
10. complete negative tests and audit telemetry.

Until that authority model is proven, current paper fills are research artifacts, not evidence that risk or strategy gates were obeyed.
