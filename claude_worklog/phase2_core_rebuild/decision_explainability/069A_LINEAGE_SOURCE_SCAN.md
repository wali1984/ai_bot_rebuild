# 069A — Decision Lineage Source Scan

Lane: explainability_ui (Lane B, decision-lineage tied to real V2 contracts).
MVP relevance: enumerates the V2 domain records that already carry lineage IDs so the 069B evidence-packet builder, 069C dashboard payload integration, and 069D validation/Codex packet have a verified inventory to consume.
Blocked by: original 069 stale_running_no_output (split into 069A→069D).
Next gate: `069A_GO_NO_GO.md` body `PHASE2HA0_069A_SOURCE_SCAN_READY`.
Legacy evidence consulted: legacy_readonly_audit, historical_pnl_audit, operator proof artifacts (raw lineage IDs already emitted by `claude_worklog/final_readiness/non_live_operational_proof/latest/*.json`).
Legacy failure addressed: opaque legacy decision/risk/trade records that had no `prediction_id`/`feature_snapshot_id`/`decision_id`/`risk_decision_id` chain and no replay-step linkage — operators could not reconstruct why a trade opened, why it was closed, or why a hedge was unwound.
V2 proof gate: this scan is the structural prerequisite for the lineage evidence packet that the 069 sequence will validate end-to-end against the operator proof harness output already produced under `claude_worklog/final_readiness/non_live_operational_proof/latest/`.

Hard safety: documentation only. No legacy mutation, no Redis writes, no live restarts, no exchange actions, no leverage/margin changes, no live-trading enablement, no deploy, no secret exposure, no V2 source modification.

## 1. Lineage ID Field Catalog

The V2 lineage chain is currently expressed as foreign-key-style identifier fields on each domain record. The chain proceeds:

```
feature_snapshot_id
  -> prediction_id
       -> decision_id
            -> risk_decision_id
                 -> paper_trade_id
                      -> replay_step_id (within replay_run_id)
```

Auxiliary chain elements:

- `replay_run_id`: container for an ordered sequence of `replay_step_id` values that mirror per-trade outcomes.
- `replay_summary_id`: aggregate identifier tied to a single `replay_run_id`; carries partitioned step counts.
- `model_version` and `checkpoint_id`: model-identity fields carried on the prediction record.
- `worker_id` and `worker_health_status`: operational provenance fields carried on the prediction record.

Runtime-context fields that gate the chain but are not per-trade IDs:

- `mode` on `PaperModeFlag` (`paper` vs `live_blocked`).
- `state` on `ShadowModeReadinessFlag` (`not_ready` vs `ready`).

## 2. Source File Inventory

All paths are V2-only (no legacy mutation). Sizes/line counts captured at this turn's HEAD.

### 2.1 Domain records carrying lineage IDs

| File | Lines | Exported lineage-bearing symbol | Lineage IDs carried |
|---|---:|---|---|
| `v2/backend/app/domain/trainer_prediction_output/record.py` | 168 | `TrainerPredictionRecord` (frozen dataclass, slots) | `prediction_id`, `feature_snapshot_id` |
| `v2/backend/app/domain/orchestrator_decision/record.py` | 204 | `OrchestratorDecisionRecord` (frozen dataclass, slots) | `decision_id`, `prediction_id`, `feature_snapshot_id` |
| `v2/backend/app/domain/risk_gateway/record.py` | 218 | `RiskDecisionRecord` (frozen dataclass, slots) | `risk_decision_id`, `decision_id`, `prediction_id`, `feature_snapshot_id` |
| `v2/backend/app/domain/paper_execution_ledger/record.py` | 223 | `PaperExecutionLedgerEntry` (frozen dataclass, slots) | `paper_trade_id`, `risk_decision_id`, `decision_id`, `prediction_id`, `feature_snapshot_id` |
| `v2/backend/app/domain/replay_backtest_runner/run.py` | 82 | `ReplayBacktestRun` (frozen dataclass, slots) | `replay_run_id` |
| `v2/backend/app/domain/replay_backtest_runner/step.py` | 200 | `ReplayBacktestStep` (frozen dataclass, slots) | `replay_step_id`, `replay_run_id`, `paper_trade_id`, `risk_decision_id`, `decision_id`, `prediction_id`, `feature_snapshot_id` |
| `v2/backend/app/domain/replay_backtest_runner/summary.py` | 116 | `ReplayBacktestSummary` (frozen dataclass, slots) | `replay_summary_id`, `replay_run_id` |

### 2.2 Domain runtime-context flags

| File | Lines | Exported symbol | Field |
|---|---:|---|---|
| `v2/backend/app/domain/paper_mode/flag.py` | 55 | `PaperModeFlag` (frozen dataclass, slots) | `mode` ∈ {`paper`, `live_blocked`} |
| `v2/backend/app/domain/shadow_mode_readiness/flag.py` | 69 | `ShadowModeReadinessFlag` (frozen dataclass, slots) | `state` ∈ {`not_ready`, `ready`} |

### 2.3 Lineage namespace placeholders (no implementation yet)

| File | Lines | Status |
|---|---:|---|
| `v2/backend/app/domain/lineage/ids.py` | 1 | Docstring-only placeholder: `"""UUIDv7 generators placeholder. Pure module; never imports DB."""` |
| `v2/backend/app/domain/lineage/chain.py` | 1 | Docstring-only placeholder: `"""Canonical lineage chain definition placeholder."""` |
| `v2/backend/app/domain/lineage/validators.py` | 1 | Docstring-only placeholder: `"""Lineage validators placeholder. Pure functions; no I/O."""` |

These three placeholders are the natural target for a future centralized lineage-chain registry; today there is no shared canonical definition, only the per-record fields above.

### 2.4 Empty / scaffold-only domain namespaces (no exports)

| Path | Status |
|---|---|
| `v2/backend/app/domain/decisions/` | Only `__init__.py`; no domain symbols. |
| `v2/backend/app/domain/predictions/` | Only `__init__.py`; no domain symbols. |
| `v2/backend/app/domain/signals/` | Only `__init__.py`; no domain symbols. |
| `v2/backend/app/domain/execution/__init__.py` | Empty (zero bytes). |
| `v2/backend/app/domain/execution/intent.py` | 015A docstring-only placeholder: `"""Execution intent domain placeholder. Pure module."""` |
| `v2/backend/app/domain/execution/paper.py` | 015A docstring-only placeholder: `"""Paper-execution domain placeholder. Pure module."""` |

These confirm that the lineage chain is currently materialized only inside the records listed in §2.1–§2.2; no parallel or shadow-only execution-intent record exists yet.

## 3. Domain Action / Reason Code Inventory

The lineage chain also carries discriminator strings that explain *why* a step took the value it did. The decision-explainability cockpit must surface these alongside the IDs.

### 3.1 Trainer prediction output (`trainer_prediction_output/record.py`)

Direction codes:
- `PREDICTION_DIRECTION_LONG = "long"`
- `PREDICTION_DIRECTION_SHORT = "short"`
- `PREDICTION_DIRECTION_FLAT = "flat"`

Freshness codes:
- `PREDICTION_FRESHNESS_FRESH = "fresh"`
- `PREDICTION_FRESHNESS_STALE = "stale"`
- `PREDICTION_FRESHNESS_MISSING = "missing"`

Worker health domain (validated, not exported as named constants in this module): `{HEALTHY, DEGRADED, CRITICAL, UNKNOWN}`.

Confidence fields: `confidence_raw`, `confidence_calibrated` (both validated to the closed unit interval).

Top-feature attribution: `top_positive_feature_codes`, `top_negative_feature_codes` (each a tuple of up to 8 unique non-whitespace codes; the two tuples must be disjoint).

### 3.2 Orchestrator decision (`orchestrator_decision/record.py`)

Action codes:
- `DECISION_ACTION_OPEN_LONG = "open_long"`
- `DECISION_ACTION_OPEN_SHORT = "open_short"`
- `DECISION_ACTION_HOLD = "hold"`
- `DECISION_ACTION_ABSTAIN = "abstain"`

Reason codes:
- `DECISION_REASON_PROCEED_LONG = "proceed_long"`
- `DECISION_REASON_PROCEED_SHORT = "proceed_short"`
- `DECISION_REASON_HOLD_FLAT_DIRECTION = "hold_flat_direction"`
- `DECISION_REASON_ABSTAIN_LOW_CONFIDENCE = "abstain_low_confidence"`
- `DECISION_REASON_ABSTAIN_FRESHNESS_STALE = "abstain_freshness_stale"`
- `DECISION_REASON_ABSTAIN_FRESHNESS_MISSING = "abstain_freshness_missing"`
- `DECISION_REASON_ABSTAIN_WORKER_DEGRADED = "abstain_worker_degraded"`
- `DECISION_REASON_ABSTAIN_WORKER_CRITICAL = "abstain_worker_critical"`
- `DECISION_REASON_ABSTAIN_WORKER_UNKNOWN = "abstain_worker_unknown"`

Cross-field rules: the action/reason pair is constrained (e.g. `open_long` requires `proceed_long` + `long` input direction; `abstain` requires any reason with the `abstain_` prefix). `live_blocked` is required to be exactly `True`.

### 3.3 Risk gateway (`risk_gateway/record.py`)

Action codes:
- `RISK_DECISION_ACTION_ALLOW = "allow"`
- `RISK_DECISION_ACTION_DENY = "deny"`

Reason codes:
- `RISK_DECISION_REASON_ALLOW_PROCEED_LONG = "allow_proceed_long"`
- `RISK_DECISION_REASON_ALLOW_PROCEED_SHORT = "allow_proceed_short"`
- `RISK_DECISION_REASON_DENY_ORCHESTRATOR_ABSTAINED = "deny_orchestrator_abstained"`
- `RISK_DECISION_REASON_DENY_ORCHESTRATOR_HELD = "deny_orchestrator_held"`
- `RISK_DECISION_REASON_DENY_DEFAULT = "deny_default"`

Cross-field rules: the `allow_*` and `deny_*` prefixes must match the `risk_action`; `deny_default` requires a tradable input action (`open_long` or `open_short`); `live_blocked` is required to be exactly `True`.

### 3.4 Paper execution ledger (`paper_execution_ledger/record.py`)

Action codes:
- `PAPER_LEDGER_ACTION_RECORD_ALLOW = "record_allow"`
- `PAPER_LEDGER_ACTION_RECORD_DENY = "record_deny"`

Reason codes:
- `PAPER_LEDGER_REASON_MIRROR_ALLOW_PROCEED_LONG = "mirror_allow_proceed_long"`
- `PAPER_LEDGER_REASON_MIRROR_ALLOW_PROCEED_SHORT = "mirror_allow_proceed_short"`
- `PAPER_LEDGER_REASON_MIRROR_DENY_ORCHESTRATOR_ABSTAINED = "mirror_deny_orchestrator_abstained"`
- `PAPER_LEDGER_REASON_MIRROR_DENY_ORCHESTRATOR_HELD = "mirror_deny_orchestrator_held"`
- `PAPER_LEDGER_REASON_MIRROR_DENY_DEFAULT = "mirror_deny_default"`

Cross-field rules: each `mirror_*` reason must match the upstream risk reason exactly (e.g. `mirror_deny_default` requires upstream `deny_default`). `live_blocked` is required to be exactly `True`.

### 3.5 Replay/backtest step (`replay_backtest_runner/step.py`)

Action codes:
- `STEP_ACTION_RECORD_ALLOW = "step_record_allow"`
- `STEP_ACTION_RECORD_DENY = "step_record_deny"`

Reason codes:
- `STEP_REASON_MIRROR_ALLOW_PROCEED_LONG = "step_mirror_allow_proceed_long"`
- `STEP_REASON_MIRROR_ALLOW_PROCEED_SHORT = "step_mirror_allow_proceed_short"`
- `STEP_REASON_MIRROR_DENY_ORCHESTRATOR_HELD = "step_mirror_deny_orchestrator_held"`
- `STEP_REASON_MIRROR_DENY_ORCHESTRATOR_ABSTAINED = "step_mirror_deny_orchestrator_abstained"`
- `STEP_REASON_MIRROR_DENY_DEFAULT = "step_mirror_deny_default"`

Cross-field rules: each `step_mirror_*` reason must mirror the upstream paper-ledger reason exactly. `live_blocked` is required to be exactly `True`.

### 3.6 Replay/backtest run + summary

`ReplayBacktestRun` carries `run_mode ∈ {replay, backtest}` and an interval `[run_started_ts_ms, run_ended_ts_ms]` validated as `run_ended_ts_ms >= run_started_ts_ms`.

`ReplayBacktestSummary` carries partitioned step counts that must satisfy:
- `record_allow_steps_count + record_deny_steps_count == total_steps_count`
- `mirror_allow_proceed_long_steps_count + mirror_allow_proceed_short_steps_count == record_allow_steps_count`
- `mirror_deny_orchestrator_held_steps_count + mirror_deny_orchestrator_abstained_steps_count + mirror_deny_default_steps_count == record_deny_steps_count`

These invariants are the ground truth for any aggregate explainability widget that summarizes a replay run.

## 4. Service / Composition Surface (Lineage Producers)

The records above are produced and validated through these layers (read-only inventory; this scan does not modify them):

| Layer | Path | Notes |
|---|---|---|
| Service | `v2/backend/app/services/trainer_prediction_output/{__init__.py,errors.py,service.py}` | Emits `TrainerPredictionRecord`. |
| Service | `v2/backend/app/services/orchestrator_decision/{__init__.py,errors.py,service.py}` | Consumes prediction; emits `OrchestratorDecisionRecord`. |
| Service | `v2/backend/app/services/risk_gateway/{__init__.py,errors.py,service.py}` | Consumes orchestrator decision; emits `RiskDecisionRecord`. |
| Service | `v2/backend/app/services/paper_execution_ledger/{__init__.py,errors.py,service.py}` | Consumes risk decision; emits `PaperExecutionLedgerEntry`. |
| Service | `v2/backend/app/services/replay_backtest_runner/{__init__.py,errors.py,service.py}` | Iterates over paper-ledger entries; emits `ReplayBacktestStep` and `ReplayBacktestSummary`. |
| Service | `v2/backend/app/services/paper_mode/{__init__.py,errors.py,service.py}` | Emits `PaperModeFlag` runtime context. |
| Service | `v2/backend/app/services/shadow_mode_readiness/{__init__.py,errors.py,service.py}` | Emits `ShadowModeReadinessFlag` runtime context. |
| Composition | `v2/backend/app/composition/{trainer_prediction_output,orchestrator_decision,risk_gateway,paper_execution_ledger,replay_backtest_runner,paper_mode,shadow_mode_readiness}/runtime.py` | Wires services into the proof harness without touching live runtimes. |

Aggregate proof artifacts (already emitted, not modified by 069A) live under:
- `claude_worklog/final_readiness/non_live_operational_proof/latest/replay_backtest_result.json`
- `claude_worklog/final_readiness/non_live_operational_proof/latest/paper_ledger_result.json`
- `claude_worklog/final_readiness/non_live_operational_proof/latest/risk_gateway_result.json`
- `claude_worklog/final_readiness/non_live_operational_proof/latest/decision_explainability_result.json`
- `claude_worklog/final_readiness/non_live_operational_proof/latest/shadow_comparison_result.json`
- `claude_worklog/final_readiness/non_live_operational_proof/latest/aggregate_non_live_proof_rollup.md`
- `claude_worklog/final_readiness/non_live_operational_proof/latest/GO_NO_GO.md` (`NON_LIVE_OPERATOR_PROOF_HARNESS_READY`)

These artifacts are the reference oracle the 069B evidence-packet builder will consume — every lineage ID present in those JSON outputs must be derivable from one of the records inventoried in §2.1.

## 5. Observed Gaps for Subsequent 069 Steps

These are observations only; remediation is the scope of 069B/069C/069D, not 069A.

1. `v2/backend/app/domain/lineage/{ids.py,chain.py,validators.py}` are docstring-only placeholders. The canonical lineage chain (§1) is implicit across seven dataclasses; there is no single authoritative chain definition to import.
2. There is no `execution_intent_id` in the current chain. `v2/backend/app/domain/execution/{intent.py,paper.py}` are 015A scaffold placeholders. Live-execution lineage is intentionally absent; the chain stops at `paper_trade_id` and is mirrored into `replay_step_id`.
3. There is no `signal_id` in the current chain. The orchestrator decision binds directly to the prediction without a separate signal layer; `v2/backend/app/domain/signals/` contains no exports.
4. `shadow_decision_id` does not exist as a distinct lineage ID. Shadow mode is currently expressed as a runtime-context flag (`ShadowModeReadinessFlag.state`) with no per-decision identifier. Shadow comparison evidence is produced via the proof harness's `shadow_comparison_result.json` rather than a per-record domain artifact.
5. Worker-health and freshness inputs to the decision are carried on the orchestrator record (`input_worker_health_status`, `input_prediction_freshness_flag`). The risk-gateway and paper-ledger records do not re-carry these fields; an explainability projection that exposes "why was confidence trusted at decision time" must join back to the prediction record via `prediction_id`.

## 6. Allowed Outputs Posture for the 069 Series

069A emits only:
- `claude_worklog/phase2_core_rebuild/decision_explainability/069A_LINEAGE_SOURCE_SCAN.md` (this file)
- `claude_worklog/phase2_core_rebuild/decision_explainability/069A_GO_NO_GO.md`

No V2 source is modified. No supervisor/scheduler/watchdog tool is modified. No legacy file is touched. No Redis command is issued. No live process is restarted. No exchange action is taken.

## 7. Verdict

All records and exported symbols required to assemble a per-trade lineage chain from `feature_snapshot_id` through `replay_step_id` are present in V2 source today and are constrained by frozen-dataclass validators that require `live_blocked = True` on every step. Centralized lineage helpers under `v2/backend/app/domain/lineage/` remain placeholder-only; the chain is currently expressed by foreign-key fields on each record. The 069B evidence-packet builder has a stable surface to consume.

`069A` is `READY`.
END_FILE: claude_worklog/phase2_core_rebuild/decision_explainability/069A_LINEAGE_SOURCE_SCAN.md
