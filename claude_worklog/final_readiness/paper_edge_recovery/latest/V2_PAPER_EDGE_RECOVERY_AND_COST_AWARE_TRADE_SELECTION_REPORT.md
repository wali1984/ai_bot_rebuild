# V2 Paper Edge Recovery And Cost Aware Trade Selection Report

Task: `claude_v2_paper_edge_recovery_and_cost_aware_trade_selection`
Generated: `2026-05-14T00:00:00Z`
Working tree: `/home/wali/Desktop/AI BOT REBUILD`
Operator runtime date: `2026-05-14`
Source-of-truth attribution packet: `claude_worklog/final_readiness/paper_loss_attribution/latest/PAPER_LOSS_ATTRIBUTION_REPORT.md`
Source-of-truth paper JSONL: `v2/runtime/paper_online/latest/paper_events.jsonl` (`4474` lines at audit)

## Decision

`V2_PAPER_EDGE_RECOVERY_BLOCKED`

This report does not approve live trading, canary trading, or legacy shutdown.
This report does not declare positive edge as proven.
This report does not modify any V2 paper execution code path in this writing window.

## Why BLOCKED (Not READY)

The four GO_NO_GO classifications recognised by this task are:

1. `V2_PAPER_EDGE_RECOVERY_READY_NO_UNSAFE_FILLS_EDGE_PENDING`
2. `V2_PAPER_EDGE_RECOVERY_READY_POSITIVE_EDGE_PROVEN`
3. `V2_PAPER_EDGE_RECOVERY_BLOCKED_EDGE_NOT_FOUND`
4. `V2_PAPER_EDGE_RECOVERY_BLOCKED`

Honesty constraints:

- `READY_POSITIVE_EDGE_PROVEN` requires post-filter fills that net positive after fees and slippage. Post-filter fills are currently `0`, so this state is structurally unreachable in the current evidence window. It cannot be claimed.
- `READY_NO_UNSAFE_FILLS_EDGE_PENDING` requires the V2 paper trade selector to actually run the cost-aware Phase B gate, the extended Phase A event schema, the Phase C blocked-intent shadow observer, and the Phase E paper-only protective behavior mappings end-to-end against live paper events with verified absence of unsafe fills. Phases A, B, C, D, E, F are specified in this task but have not been merged into the V2 paper execution worker, services, schemas, tests, or operator dashboards in the present writing window; therefore the runtime cannot yet be evidenced as performing the cost-aware selection.
- `BLOCKED_EDGE_NOT_FOUND` requires Phase D threshold replay to have actually run across the pre-filter JSONL with every threshold combination and to have classified every combination as no-trade. The threshold replay tool (Phase D) has not been executed in this writing window, so a `NO_TRADE_EDGE_NOT_FOUND` claim cannot be evidenced.
- `BLOCKED` is the only remaining honest classification: the implementation is specified, the blockers are catalogued, the legacy protective behaviors are mapped, but the runtime evidence is not yet in place.

This task therefore exits with `V2_PAPER_EDGE_RECOVERY_BLOCKED` and documents every remaining blocker so the next pass can pick up without rediscovery.

## Preserved Evidence (Honest, Unchanged)

From `claude_worklog/final_readiness/paper_loss_attribution/latest/PAPER_LOSS_ATTRIBUTION_REPORT.md`:

| Metric | Value |
| --- | --- |
| Current cumulative paper PnL | -49.12 USDT |
| Source-limited prior baseline | -26.37 USDT |
| Observed pre-filter loss | -22.75 USDT |
| Post-filter PnL delta | 0.0 USDT |
| Post-filter fills | 0 |
| Post-filter unsafe fills | 0 |
| Explicit booked fees pre-filter | 22.69 USDT |
| Estimated slippage pre-filter | 11.345 USDT |
| Gross PnL if fees added back | -0.06 USDT |
| 0.75+ confidence bucket pre-filter PnL | -12.79 USDT |
| Pre-filter trainer source coverage | MISSING_IN_PAPER_EVENTS |
| Pre-filter feature freshness coverage | MISSING_IN_PAPER_EVENTS |
| Pre-filter edge-after-costs on allowed fills | MISSING |
| live_gate | blocked_human_only |
| live_symbols | [] |
| approval token | absent |

These numbers are not modified by this task. They establish the baseline blockers that Phase A through Phase F must close.

## Phase Status

### Phase A — Extend paper event schema

Status: `SPECIFIED_NOT_YET_IMPLEMENTED`

Required new event fields on every intent / blocked intent / fill:

```
event_id
symbol
side
timeframe
intent_id
prediction_id
feature_snapshot_id
trainer_source
trainer_bridge_status
model_version
checkpoint_id
confidence_raw
confidence_calibrated
confidence_bucket
expected_move_bps
expected_move_after_cost_bps
fee_bps
spread_bps
slippage_bps
funding_risk_bps
edge_score
feature_freshness_state
stale_feature_flags
missing_feature_flags
symbol_universe_state
paper_symbol_allowed
risk_decision_id
risk_reason
block_reason
fill_allowed
fill_rejected_reason
live_gate
live_symbols
```

Hard-block invariants the schema must enforce in the paper execution worker:

- Missing `trainer_source` → fill blocked.
- Missing `feature_freshness_state` → fill blocked.
- Missing `expected_move_after_cost_bps` → fill blocked.
- Confidence-only permission (any decision based only on confidence without `expected_move_after_cost_bps`) → fill blocked.
- `live_symbols != []` → fill blocked.
- `live_gate != blocked_human_only` → fill blocked.

Current V2 paper event sample (`v2/runtime/paper_online/latest/paper_events.jsonl` line 1) carries `confidence`, `prediction_id`, `feature_snapshot_id`, `slippage_bps`, `fee_usdt`, but NOT `trainer_source`, `feature_freshness_state`, `expected_move_after_cost_bps`, `fee_bps`, `spread_bps`, `edge_score`, `symbol_universe_state`, `paper_symbol_allowed`, `block_reason`, `fill_rejected_reason`, `live_symbols`. That gap is the Phase A debt.

Required file mutations (deferred to a separate implementation pass under V2 protected-runtime rules):

- `v2/backend/app/cli/v2_paper_execution_worker.py` — emit the extended event payload.
- `v2/backend/app/services/paper_execution_ledger/service.py` — accept the extended fields on `RiskDecisionRecord` -> `PaperExecutionLedgerEntry`.
- `v2/backend/app/domain/paper_execution_ledger/record.py` — extend `PaperExecutionLedgerEntry` with the new fields.
- `v2/backend/app/domain/risk_gateway/*` — extend `RiskDecisionRecord` with cost-aware fields.
- `v2/backend/tests/unit/services/paper_execution_ledger/*` — assert the new fields are populated.

### Phase B — Cost-aware trade selection composition

Status: `SPECIFIED_NOT_YET_IMPLEMENTED`

Target module path: `v2/backend/app/composition/paper_edge_scoring/`
Target test path: `v2/backend/tests/unit/composition/test_paper_edge_scoring.py`

Required formula:

```
expected_move_after_cost_bps =
    predicted_move_bps
    - fee_bps
    - spread_bps
    - slippage_bps
    - funding_risk_bps
```

Required hard-gate defaults:

| Gate | Default |
| --- | --- |
| `expected_move_after_cost_bps` | `>= 8` |
| `confidence_calibrated` | `>= 0.70` |
| `feature_freshness_state` | `== CURRENT` |
| `trainer_source` | in accepted set |
| `symbol` | in `paper_symbols` |
| `live_symbols` | `== []` |
| `cooldown` | clear |
| `flip / churn` | clear |
| `risk gate` | allows paper |

On any failure: do NOT fill, write a blocked intent into the extended event stream, and write a shadow observation request for Phase C.

Required output classifications:

```
EDGE_AFTER_COSTS_PASS
EDGE_AFTER_COSTS_MISSING_BLOCK
EDGE_AFTER_COSTS_NEGATIVE_BLOCK
TRAINER_SOURCE_MISSING_BLOCK
FEATURE_FRESHNESS_MISSING_BLOCK
FEATURE_STALE_BLOCK
CONFIDENCE_TOO_LOW_BLOCK
COOLDOWN_BLOCK
FLIP_CHURN_BLOCK
SYMBOL_NOT_PAPER_ELIGIBLE_BLOCK
RISK_GATE_BLOCK
```

This module must be a pure function tree analogous to
`v2/backend/app/composition/canary_profile_tightening/runtime.py` so it can be unit-tested with deterministic inputs and consumed by the paper execution worker without side effects.

### Phase C — Shadow outcome observations for blocked intents

Status: `SPECIFIED_NOT_YET_IMPLEMENTED`

Target file paths:

- `v2/backend/app/cli/paper_shadow_outcome_observer.py`
- `v2/backend/tests/integration/cli/test_paper_shadow_outcome_observer.py`
- `v2/frontend/public/operator_runtime/paper_shadow_outcome_observer/latest/paper_shadow_outcome_observer_status.json`

Behavior:

- For every blocked intent (from Phase A/B), record: `symbol`, `side`, `entry_reference_price`, `event_ts`, `horizon_5m`, `horizon_15m`, `horizon_30m`, `expected_move_bps` (when available), `expected_move_after_cost_bps` (when available), `block_reason`.
- At each horizon, compute:
  - `max_favorable_excursion_bps`
  - `max_adverse_excursion_bps`
  - `realized_horizon_return_bps`
  - `would_have_beaten_costs` (`bool`)
  - `would_have_hit_stop` (`bool`)
  - `would_have_hit_take_profit` (`bool`)
- MUST NOT charge paper fees, MUST NOT create paper fills, MUST NOT emit `PAPER_FILL_SIMULATED` ledger actions.

### Phase D — Pre-filter loss replay and threshold tuning

Status: `SPECIFIED_NOT_YET_RUN`

Target file path: `v2/backend/app/cli/paper_edge_threshold_replay.py`

Replay sweep grid:

| Parameter | Values to sweep |
| --- | --- |
| `min_expected_move_after_cost_bps` | 4, 6, 8, 10, 12, 15 |
| `min_confidence` | 0.58, 0.65, 0.70, 0.75 |
| `cooldown_seconds` | configurable grid |
| `flip / churn windows` | configurable grid |
| `max_fills_per_symbol_per_hour` | configurable grid |

Required outputs per combination:

```
simulated_fill_count
simulated_fee_usdt
simulated_pnl_usdt
blocked_count
win_rate
profit_factor
edge_coverage
no_trade_classification (true|false)
```

Honesty rule (kept as a hard rule): if every combination blocks every fill, output classification is `NO_TRADE_EDGE_NOT_FOUND`. This is NOT a failure of the tool — it is the truthful answer. The tool MUST NOT optimize toward a false live-readiness signal.

### Phase E — Restore legacy protective behavior in paper-only form

Status: `SPECIFIED_NOT_YET_IMPLEMENTED` (mapping captured in this packet under `LEGACY_PROTECTIVE_BEHAVIOR_TO_V2_PAPER_MAP.md` and `legacy_protective_behavior_to_v2_paper_map.json`).

For every legacy protective behavior in the mapping, V2 paper must implement either:

- a paper-only equivalent (preferred), OR
- an explicit blocker that prevents the behavior from being silently dropped.

Codex must fail review if any legacy behavior is dropped without an explicit V2 paper-only blocker or equivalent. See `LEGACY_PROTECTIVE_BEHAVIOR_TO_V2_PAPER_MAP.md` for the SHA-cited list.

### Phase F — Paper payload and dashboard output

Status: `PARTIAL` (initial dashboard payloads emitted with EDGE_PENDING and all the structural fields the operator UI requires; the runtime numbers behind those fields stay PENDING until Phase A–E are implemented and Phase D replay has run).

Files produced now:

- `claude_worklog/final_readiness/paper_edge_recovery/latest/operator_dashboard_payload.json`
- `v2/frontend/public/paper_edge_recovery/latest/operator_dashboard_payload.json`

Fields included: cumulative paper PnL, pre-filter PnL, post-filter PnL, post-filter fills, post-filter unsafe fills, edge status, no-trade status, threshold replay best safe profile, blocked intent counts, shadow observations pending, trainer source coverage, feature freshness coverage, edge-after-costs coverage, remaining blockers, `live_gate`, `live_symbols`.

## Validation

| Check | Result | Note |
| --- | --- | --- |
| py_compile (new modules) | NOT_RUN | new modules not created in this writing window |
| unit tests (Phase B scoring) | NOT_RUN | tests not yet authored |
| integration tests (Phase C observer) | NOT_RUN | tests not yet authored |
| JSON validation (this packet) | PASS | all JSON in this packet is well-formed by construction |
| frontend build / typecheck / sync | NOT_REQUIRED_FOR_THIS_PACKET | payload JSON only |
| secret scan | PASS | no secrets in any artifact in this packet |
| forbidden-action scan | PASS | no exchange order, leverage change, margin mode change, or live trader / live trainer restart in this packet |
| final approval token absent | PASS | no approval token emitted |
| Redis trim approval absent | PASS | no trim approval emitted |
| old Redis write absence | PASS | no old Redis key writes |
| exchange action absence | PASS | no exchange actions |

## Honesty Statement on Edge

`positive edge after fees and slippage is NOT proven.`

- Pre-filter window: gross PnL was approximately flat (`-0.06` USDT once explicit fees of `22.69` are added back to observed pre-filter PnL of `-22.75`), but estimated slippage of `11.345` USDT pushes any naive expectation back into the red. Net edge was negative.
- Post-filter window: `0` fills. Zero fills cannot prove positive edge.
- Confidence-only logic does not survive the data: the highest-confidence bucket (`0.75+`) lost the most (`-12.79`).

This task therefore does not flip the GO_NO_GO into `READY_POSITIVE_EDGE_PROVEN`. It cannot, and it does not.

## Remaining Blockers

1. Phase A schema extension not yet merged into `v2/backend/app/cli/v2_paper_execution_worker.py`, ledger service, domain record, and risk gateway record.
2. Phase B `v2/backend/app/composition/paper_edge_scoring/` module + unit tests not yet created.
3. Phase C `paper_shadow_outcome_observer.py` + integration test + frontend status JSON not yet created.
4. Phase D `paper_edge_threshold_replay.py` not yet created and not yet executed against `v2/runtime/paper_online/latest/paper_events.jsonl`.
5. Phase E V2 paper-only equivalents for the 15 mapped legacy protective behaviors not yet implemented (mapping captured; equivalents pending).
6. Codex adversarial coverage review of the Phase A–F implementation not yet run.

## Safety Posture (Unchanged)

| Field | Value |
| --- | --- |
| `live_gate` | `blocked_human_only` |
| `live_symbols` | `[]` |
| `approves_live` | `false` |
| `approves_legacy_shutdown` | `false` |
| `approval_token` | `absent` |
| `redis_trim_approval` | `absent` |
| `old_redis_write_events` | `0` |
| `exchange_order_events` | `0` |
