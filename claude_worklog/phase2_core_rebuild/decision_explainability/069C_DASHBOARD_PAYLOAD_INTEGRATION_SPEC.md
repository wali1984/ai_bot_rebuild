# 069C - Dashboard Payload Integration Spec

Task: `069C_decision_lineage_dashboard_payload_integration`
Mode: documentation only, non-live, operator dashboard payload contract.
Allowed output prefix: `claude_worklog/phase2_core_rebuild/decision_explainability/`

No legacy bot directory was modified. No V2 source was modified. No Redis data store was read or written. No service was restarted. No exchange order, leverage, margin, or live-trading setting was changed.

## 1. Input Authority

The dashboard payload contract must consume the 069A/069B lineage inventory and evidence packet as the current source of truth:

| Input | Required use |
|---|---|
| `claude_worklog/phase2_core_rebuild/decision_explainability/069A_LINEAGE_SOURCE_SCAN.md` | Defines concrete V2 lineage-bearing domain records and known scaffold-only stages. |
| `claude_worklog/phase2_core_rebuild/decision_explainability/069B_LINEAGE_EVIDENCE_PACKET.md` | Defines which IDs are authoritative, fixture-only, or missing from the latest proof payload. |
| `claude_worklog/final_readiness/non_live_operational_proof/latest/decision_explainability_result.json` | Provides per-scenario operator explanations and lineage IDs. |
| `claude_worklog/final_readiness/non_live_operational_proof/latest/replay_backtest_result.json` | Provides replay/backtest scenario counts, PnL summary, and scenario-level proof rows. |
| `claude_worklog/final_readiness/non_live_operational_proof/latest/paper_ledger_result.json` | Provides paper ledger event rows and non-live-only action evidence. |
| `claude_worklog/final_readiness/non_live_operational_proof/latest/shadow_comparison_result.json` | Provides shadow comparison fixture rows and divergence indicators. |

The dashboard must not infer a complete lineage stage when 069B marks that stage as scaffold-only, fixture-only, or absent from current proof rows.

## 2. Payload Envelope

The operator dashboard payload must expose a top-level non-live status envelope before any row data:

| Field | Requirement |
|---|---|
| `generated_at` | Timestamp from the payload builder run or the newest source artifact timestamp. |
| `lineage_contract_version` | Fixed string for this contract, recommended `phase2ha0_069c_v1`. |
| `source_markers` | Paths and marker values for `069A_GO_NO_GO.md` and `069B_GO_NO_GO.md`. |
| `live_gate_status` | Must be `blocked_human_only` for every non-live proof-derived payload. Any other value is a dashboard-blocking warning. |
| `non_live_only` | Must be `true`. |
| `human_input_required` | Must be `false` unless the selected action is the final live/capital gate. |
| `payload_status` | `ready_with_warnings` when lineage rows are present but one or more non-authoritative stages exist; `blocked` when required concrete IDs are missing. |
| `warning_count` | Count of row-level plus payload-level warning objects. |

Minimum envelope shape:

```json
{
  "generated_at": "ISO-8601",
  "lineage_contract_version": "phase2ha0_069c_v1",
  "source_markers": {
    "069A": {
      "path": "claude_worklog/phase2_core_rebuild/decision_explainability/069A_GO_NO_GO.md",
      "marker": "PHASE2HA0_069A_SOURCE_SCAN_READY"
    },
    "069B": {
      "path": "claude_worklog/phase2_core_rebuild/decision_explainability/069B_GO_NO_GO.md",
      "marker": "PHASE2HA0_069B_EVIDENCE_PACKET_READY"
    }
  },
  "live_gate_status": "blocked_human_only",
  "non_live_only": true,
  "human_input_required": false,
  "payload_status": "ready_with_warnings",
  "warning_count": 0,
  "lineage_rows": []
}
```

## 3. Required Row Fields

Each operator-visible decision row must expose the complete currently known chain, grouped by authority:

| Group | Field | Requirement |
|---|---|---|
| Scenario | `scenario_id` | Required. |
| Scenario | `symbol` | Required. |
| Scenario | `side` | Required when present in source row. |
| Scenario | `requested_action` | Required when present in source row. |
| Scenario | `v2_action` | Required when present in replay or paper evidence. |
| Concrete lineage | `feature_snapshot_id` | Required; authoritative. |
| Concrete lineage | `prediction_id` | Required; authoritative. |
| Concrete lineage | `decision_id` | Required; authoritative. |
| Concrete lineage | `risk_decision_id` | Required; authoritative. |
| Concrete lineage | `paper_trade_id` | Required for paper/replay rows; authoritative as paper evidence, with fixture-derivation warning when the ID does not match service formula. |
| Replay lineage | `replay_run_id` | Required for replay payload views. |
| Replay lineage | `replay_step_id` | Must be exposed when source proof provides it; otherwise set `null` and emit a missing-evidence warning. |
| Fixture/scaffold lineage | `signal_id` | Must be exposed as `null` until a concrete signal domain producer exists; emit warning. |
| Fixture/scaffold lineage | `execution_intent_id` | May show source fixture value, but authority must be `fixture_only`; emit warning. |
| Fixture/scaffold lineage | `shadow_decision_id` | May show source fixture value, but authority must be `fixture_only`; emit warning. |
| Explanation | `confidence` | Required when present. |
| Explanation | `direction` | Required when present. |
| Explanation | `risk_decision` | Required. |
| Explanation | `block_or_allow_reason` | Required. |
| Explanation | `explanation_payload.summary` | Required when present. |
| Explanation | `explanation_payload.causes` | Required when present. |
| Evidence flags | `feature_flags.missing` | Required, default empty array. |
| Evidence flags | `feature_flags.stale` | Required, default empty array. |
| Evidence flags | `feature_flags.unused` | Required, default empty array. |
| Safety | `live_gate_status` | Must equal `blocked_human_only`. |
| Safety | `no_live_side_effects` | Must be true when present in source explanation payload. |
| Safety | `non_live_only` | Must be true for paper ledger rows. |
| Warnings | `lineage_warnings` | Required array, empty only if every authoritative stage is present and no scaffold/fixture-only stage is displayed. |

## 4. Authority Model

The dashboard must carry a per-field authority map so operators can distinguish proven domain lineage from demonstration fixture IDs.

Required authority values:

| Authority | Meaning |
|---|---|
| `domain_record` | ID is produced or forwarded by a concrete V2 domain/service record identified in 069A/069B. |
| `proof_payload` | ID is present in proof artifacts and corresponds to an existing concrete stage, but the proof payload may use fixture naming. |
| `fixture_only` | ID is present in non-live proof fixtures but 069A/069B found no concrete V2 domain producer. |
| `missing` | Expected field is absent from current proof payload. |
| `scaffold_only` | Stage exists only as route metadata or placeholder namespace. |

Minimum row authority map:

```json
{
  "lineage_authority": {
    "feature_snapshot_id": "domain_record",
    "prediction_id": "domain_record",
    "signal_id": "scaffold_only",
    "decision_id": "domain_record",
    "risk_decision_id": "domain_record",
    "execution_intent_id": "fixture_only",
    "paper_trade_id": "proof_payload",
    "shadow_decision_id": "fixture_only",
    "replay_step_id": "missing"
  }
}
```

## 5. Missing-Evidence Warnings

The dashboard must expose missing-evidence warnings in two places:

1. `payload_warnings`: aggregate warnings that affect the whole dashboard payload.
2. `lineage_warnings`: row-specific warnings attached to each decision or action row.

Warning object shape:

```json
{
  "code": "SIGNAL_ID_DOMAIN_RECORD_MISSING",
  "severity": "warning",
  "field": "signal_id",
  "message": "Signal stage is scaffold-only; no concrete V2 signal domain record currently proves prediction-to-signal lineage.",
  "operator_action": "Treat signal lineage as unavailable until a signal domain producer and validation test exist.",
  "evidence_pointer": "claude_worklog/phase2_core_rebuild/decision_explainability/069B_LINEAGE_EVIDENCE_PACKET.md"
}
```

Required warning codes:

| Code | Severity | Trigger |
|---|---|---|
| `SIGNAL_ID_DOMAIN_RECORD_MISSING` | `warning` | `signal_id` is absent or only scaffold metadata exists. |
| `EXECUTION_INTENT_FIXTURE_ONLY` | `warning` | `execution_intent_id` is present only in proof fixture rows. |
| `SHADOW_DECISION_FIXTURE_ONLY` | `warning` | `shadow_decision_id` is present only in shadow comparison fixture rows. |
| `REPLAY_STEP_ID_NOT_EXPOSED` | `warning` | Replay view claims replay-step lineage but source proof row has no `replay_step_id`. |
| `PAPER_TRADE_ID_FIXTURE_DERIVATION_MISMATCH` | `warning` | Fixture `paper_trade_id` does not match the current service derivation formula described by 069B. |
| `RISK_REASON_MAPPING_NOT_DOMAIN_COMPLETE` | `warning` | Operator-facing proof reason is richer than the current typed risk-domain reason mapping. |
| `LIVE_GATE_NOT_BLOCKED_HUMAN_ONLY` | `blocker` | Any source row or envelope has a live gate value other than `blocked_human_only`. |
| `CONCRETE_LINEAGE_ID_MISSING` | `blocker` | Any row lacks `feature_snapshot_id`, `prediction_id`, `decision_id`, or `risk_decision_id`. |

Warnings must be visible in the UI, filterable by severity, and included in any exported operator evidence packet. The UI must not hide warnings behind a collapsed debug-only panel.

## 6. Row Example

For the current `safe_long_paper_intent` proof row, the dashboard payload should render the complete visible chain while marking non-authoritative stages:

```json
{
  "scenario_id": "safe_long_paper_intent",
  "symbol": "BTCUSDT",
  "side": "long",
  "requested_action": "open_long",
  "v2_action": "allow_paper_open_long",
  "feature_snapshot_id": "fs_safe_long_paper_intent",
  "prediction_id": "pred_safe_long_paper_intent",
  "signal_id": null,
  "decision_id": "dec_safe_long_paper_intent",
  "risk_decision_id": "rd_safe_long_paper_intent",
  "execution_intent_id": "intent_safe_long_paper_intent",
  "paper_trade_id": "paper_safe_long_paper_intent",
  "shadow_decision_id": "shadow_safe_long_paper_intent",
  "replay_run_id": "non_live_replay_backtest_fixture_run",
  "replay_step_id": null,
  "confidence": 0.82,
  "direction": "long",
  "risk_decision": "allow",
  "block_or_allow_reason": "not_blocked",
  "live_gate_status": "blocked_human_only",
  "non_live_only": true,
  "lineage_authority": {
    "feature_snapshot_id": "domain_record",
    "prediction_id": "domain_record",
    "signal_id": "scaffold_only",
    "decision_id": "domain_record",
    "risk_decision_id": "domain_record",
    "execution_intent_id": "fixture_only",
    "paper_trade_id": "proof_payload",
    "shadow_decision_id": "fixture_only",
    "replay_step_id": "missing"
  },
  "lineage_warnings": [
    {
      "code": "SIGNAL_ID_DOMAIN_RECORD_MISSING",
      "severity": "warning",
      "field": "signal_id"
    },
    {
      "code": "EXECUTION_INTENT_FIXTURE_ONLY",
      "severity": "warning",
      "field": "execution_intent_id"
    },
    {
      "code": "SHADOW_DECISION_FIXTURE_ONLY",
      "severity": "warning",
      "field": "shadow_decision_id"
    },
    {
      "code": "REPLAY_STEP_ID_NOT_EXPOSED",
      "severity": "warning",
      "field": "replay_step_id"
    }
  ]
}
```

## 7. Operator UI Requirements

The operator dashboard must provide:

1. A lineage chain column or panel ordered as `feature_snapshot_id -> prediction_id -> signal_id -> decision_id -> risk_decision_id -> execution_intent_id -> paper_trade_id -> shadow_decision_id -> replay_step_id`.
2. A visible authority badge for every chain field: `domain_record`, `proof_payload`, `fixture_only`, `missing`, or `scaffold_only`.
3. A warning badge on each row when `lineage_warnings` is non-empty.
4. An aggregate warning summary showing counts by code and severity.
5. A hard blocked state when any blocker warning exists.
6. A persistent `live_gate_status = blocked_human_only` indicator before any decision/action details.
7. No UI affordance that treats fixture-only execution or shadow IDs as live-trading authorization.
8. No hidden fallback that fills missing IDs from strings, scenario names, or inferred prefixes.

## 8. Readiness Rules

The payload is dashboard-ready when:

1. All concrete lineage IDs are present on every row: `feature_snapshot_id`, `prediction_id`, `decision_id`, `risk_decision_id`.
2. The payload explicitly marks `signal_id`, `execution_intent_id`, `shadow_decision_id`, and missing `replay_step_id` evidence according to the authority model.
3. Every row preserves `block_or_allow_reason`, `risk_decision`, `confidence` when present, feature flag arrays, and explanation causes when present.
4. Every source row and envelope preserves `live_gate_status = blocked_human_only`.
5. The dashboard exposes warnings as operator-visible payload data, not as implementation comments.

The payload is blocked when:

1. Any concrete lineage ID is missing.
2. Any live gate value is not `blocked_human_only`.
3. The dashboard presents fixture-only or scaffold-only IDs as authoritative domain lineage.
4. Missing-evidence warnings are omitted from the payload.

## 9. Recommendation

`069C` is READY as a dashboard integration specification because it defines how the operator payload must expose currently verified lineage fields while making missing or fixture-only evidence visible. This does not close the implementation gaps identified by 069B; it prevents the dashboard contract from hiding them.

PHASE2HA0_069C_DASHBOARD_INTEGRATION_READY
