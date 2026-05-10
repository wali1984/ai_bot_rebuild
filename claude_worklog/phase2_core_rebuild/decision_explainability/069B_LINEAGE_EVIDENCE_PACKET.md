# 069B — Decision Lineage Evidence Packet

Task: `069B_decision_lineage_evidence_packet_builder`
Mode: documentation only, non-live, source/evidence packet.
Allowed output prefix: `claude_worklog/phase2_core_rebuild/decision_explainability/`

No legacy bot directory was modified. No V2 source was modified. No Redis data store was read or written. No service was restarted. No exchange order, leverage, margin, or live-trading setting was changed.

## 1. Packet Authority

Primary predecessor: `069A_LINEAGE_SOURCE_SCAN.md` with marker `PHASE2HA0_069A_SOURCE_SCAN_READY`.

Source authority consulted:

| Evidence class | Path | Use in this packet |
|---|---|---|
| 069A scan | `claude_worklog/phase2_core_rebuild/decision_explainability/069A_LINEAGE_SOURCE_SCAN.md` | Inventory of current lineage-bearing records and known gaps. |
| Non-live operator proof | `claude_worklog/final_readiness/non_live_operational_proof/latest/decision_explainability_result.json` | Five scenario rows carrying `feature_snapshot_id`, `prediction_id`, `decision_id`, `risk_decision_id`, `execution_intent_id`, `paper_trade_id`, and `shadow_decision_id`. |
| Replay proof | `claude_worklog/final_readiness/non_live_operational_proof/latest/replay_backtest_result.json` | Five scenario rows, 1 allowed and 4 blocked, with `live_gate_status = blocked_human_only`. |
| Paper ledger proof | `claude_worklog/final_readiness/non_live_operational_proof/latest/paper_ledger_result.json` | Paper/shadow action surface, non-live-only ledger event rows. |
| Risk proof | `claude_worklog/final_readiness/non_live_operational_proof/latest/risk_gateway_result.json` | Risk allow/deny rows and risk reasons. |
| Shadow proof | `claude_worklog/final_readiness/non_live_operational_proof/latest/shadow_comparison_result.json` | Shadow comparison rows and divergence indicators. |
| Proof gate | `claude_worklog/final_readiness/non_live_operational_proof/latest/GO_NO_GO.md` | `NON_LIVE_OPERATOR_PROOF_HARNESS_READY`. |

## 2. Canonical Chain Observed

Current concrete V2 domain records support this chain:

`raw source refs -> feature_snapshot_id -> prediction_id -> decision_id -> risk_decision_id -> paper_trade_id -> replay_step_id`

Current API/schema scaffolds also name `signal_id` and `execution_intent_id`, but there is not yet a concrete V2 domain record producer for either stage.

Current non-live proof fixtures carry `execution_intent_id` and `shadow_decision_id` fields in the proof JSON, but 069A found that `v2/backend/app/domain/execution/intent.py`, `v2/backend/app/domain/execution/paper.py`, and `v2/backend/app/domain/signals/__init__.py` are scaffold-only. This packet therefore treats signal and execution intent as documented gaps, not as verified domain-produced records.

## 3. Stage-By-Stage Evidence Map

| Stage | Current owner | ID minted or forwarded | Evidence pointer | Packet finding |
|---|---|---|---|---|
| Raw source data | `v2/backend/app/domain/features/models.py` | `source_snapshot_ids`, `source_key_refs`, `source_ingestor_refs` | `FeatureSnapshot` fields at lines 44-62; `trainer_payload` forwards source refs at lines 64-81. | Raw source attribution is represented as refs inside feature snapshots, not as a separate raw-source event record. |
| Feature snapshot | `v2/backend/app/services/feature_snapshots/service.py` and `v2/backend/app/domain/features/models.py` | `feature_snapshot_id` | Service mints or accepts `feature_snapshot_id` at service lines 61-79; model defines snapshot fields at model lines 44-62. | Concrete. Snapshot carries feature values, source refs, freshness, stale/missing/unused feature lists, and trainer readiness. |
| Trainer prediction | `v2/backend/app/services/trainer_prediction_output/service.py` and `v2/backend/app/domain/trainer_prediction_output/record.py` | `prediction_id`, forwards `feature_snapshot_id` | Service assembles prediction at service lines 10-54; record fields at record lines 90-107; validators at record lines 108-168. | Concrete. Prediction carries direction, raw/calibrated confidence, model/checkpoint, worker health, freshness, and top positive/negative feature codes. |
| Signal | API scaffold only: `v2/backend/app/api/v1/signals.py`; domain namespace empty | Intended `signal_id`, forwards `feature_snapshot_id` and `prediction_id` | Route metadata requires `signal_id` at lines 14-22; `v2/backend/app/domain/signals/__init__.py` has no exports. | GAP. There is no current signal-domain record to bind prediction-to-signal. |
| Orchestrator decision | `v2/backend/app/services/orchestrator_decision/service.py` and `v2/backend/app/domain/orchestrator_decision/record.py` | `decision_id`, forwards `prediction_id` and `feature_snapshot_id` | Service derives `decision_id` and action/reason at lines 34-117; record fields at lines 73-87 and validators at lines 88-204. | Concrete. Orchestrator action is derived from prediction freshness, worker health, calibrated confidence, and direction; `live_blocked` must be true. |
| Risk gateway | `v2/backend/app/services/risk_gateway/service.py` and `v2/backend/app/domain/risk_gateway/record.py` | `risk_decision_id`, forwards `decision_id`, `prediction_id`, `feature_snapshot_id` | Service derives risk action/reason and ID at lines 25-79; record fields at lines 56-69 and validators at lines 70-218. | Concrete. Risk allow/deny mirrors orchestrator action and preserves upstream IDs; `live_blocked` must be true. |
| Execution intent | API scaffold only: `v2/backend/app/api/v1/intents.py`; domain placeholder | Intended `execution_intent_id`, forwards full upstream chain including `signal_id` | Route metadata requires `execution_intent_id` at lines 16-31; `v2/backend/app/domain/execution/intent.py` is a one-line placeholder. | GAP. Proof fixtures carry `execution_intent_id`, but no V2 domain producer currently owns it. |
| Paper action | `v2/backend/app/services/paper_execution_ledger/service.py` and `v2/backend/app/domain/paper_execution_ledger/record.py` | `paper_trade_id`, forwards `risk_decision_id`, `decision_id`, `prediction_id`, `feature_snapshot_id` | Service derives paper ledger entry at lines 26-92; record fields at lines 90-104 and validators at lines 105-223. | Concrete. Paper ledger records allow/deny mirror reasons and require `live_blocked` true. |
| Shadow action | Proof artifact and readiness flag only | Fixture `shadow_decision_id`; no domain-owned per-action ID | `shadow_comparison_result.json` contains five comparison rows with `shadow_decision_id`; `ShadowModeReadinessFlag` only carries `state`, timestamp, and `live_blocked` at `v2/backend/app/domain/shadow_mode_readiness/flag.py` lines 14-55. | GAP for domain record. Shadow comparison evidence exists, but there is no per-decision shadow domain record yet. |
| Replay/backtest action | `v2/backend/app/services/replay_backtest_runner/service.py` and `v2/backend/app/domain/replay_backtest_runner/step.py` | `replay_step_id`, forwards `paper_trade_id`, `risk_decision_id`, `decision_id`, `prediction_id`, `feature_snapshot_id` | Service derives replay step at lines 30-128; step record fields at lines 70-85 and validators at lines 87-200. | Concrete for replay/backtest projection. |

## 4. Proof Scenario Lineage Rows

The latest non-live proof packet has five scenarios:

| Scenario | Symbol | Feature snapshot | Prediction | Decision | Risk decision | Execution intent evidence | Paper/shadow evidence | Outcome |
|---|---|---|---|---|---|---|---|---|
| `safe_long_paper_intent` | `BTCUSDT` | `fs_safe_long_paper_intent` | `pred_safe_long_paper_intent` | `dec_safe_long_paper_intent` | `rd_safe_long_paper_intent` | `intent_safe_long_paper_intent` in proof JSON only | `paper_safe_long_paper_intent`, `shadow_safe_long_paper_intent` | allow, paper PnL `+12.40` in replay result |
| `stale_data_blocked` | `ETHUSDT` | `fs_stale_data_blocked` | `pred_stale_data_blocked` | `dec_stale_data_blocked` | `rd_stale_data_blocked` | `intent_stale_data_blocked` in proof JSON only | `paper_stale_data_blocked`, `shadow_stale_data_blocked` | deny because feature snapshot is stale |
| `duplicate_signal_blocked` | `SOLUSDT` | `fs_duplicate_signal_blocked` | `pred_duplicate_signal_blocked` | `dec_duplicate_signal_blocked` | `rd_duplicate_signal_blocked` | `intent_duplicate_signal_blocked` in proof JSON only | `paper_duplicate_signal_blocked`, `shadow_duplicate_signal_blocked` | deny because duplicate signal is blocked by fixture policy |
| `hedge_close_residual_exposure_blocked` | `BNBUSDT` | `fs_hedge_close_residual_exposure_blocked` | `pred_hedge_close_residual_exposure_blocked` | `dec_hedge_close_residual_exposure_blocked` | `rd_hedge_close_residual_exposure_blocked` | `intent_hedge_close_residual_exposure_blocked` in proof JSON only | `paper_hedge_close_residual_exposure_blocked`, `shadow_hedge_close_residual_exposure_blocked` | deny/block-or-reduce because hedge close would leave naked short exposure |
| `lab_hedge_unwind_short_squeeze` | `LABUSDT` | `fs_lab_hedge_unwind_short_squeeze` | `pred_lab_hedge_unwind_short_squeeze` | `dec_lab_hedge_unwind_short_squeeze` | `rd_lab_hedge_unwind_short_squeeze` | `intent_lab_hedge_unwind_short_squeeze` in proof JSON only | `paper_lab_hedge_unwind_short_squeeze`, `shadow_lab_hedge_unwind_short_squeeze` | deny/block-or-reduce; proof records `legacy_loss_avoided` |

## 5. Field-Level Forwarding Contract

| ID | Minting/owning source today | Forwarded by | Persisted or evidenced by | Status |
|---|---|---|---|---|
| `feature_snapshot_id` | `FeatureSnapshotService.build_snapshot` or explicit payload; `FeatureSnapshot` domain model | Trainer prediction, orchestrator decision, risk decision, paper ledger, replay step | Non-live proof JSON, paper ledger proof, replay proof | Concrete |
| `prediction_id` | `assemble_prediction_record` input and `TrainerPredictionRecord` | Orchestrator decision, risk decision, paper ledger, replay step | Non-live proof JSON, paper ledger proof, replay proof | Concrete |
| `signal_id` | No current domain owner; API route metadata only | Intended in `LineageBlock` and `/signals/` metadata | Not present in current proof JSON | GAP |
| `decision_id` | `assemble_orchestrator_decision_record` derives `"dec_" + prediction_id` | Risk decision, paper ledger, replay step | Non-live proof JSON, paper ledger proof, replay proof | Concrete |
| `risk_decision_id` | `assemble_risk_decision_record` derives `"rd_" + decision_id` | Paper ledger, replay step | Non-live proof JSON, paper ledger proof, replay proof | Concrete |
| `execution_intent_id` | No current domain owner; API route metadata only | Intended in `/execution-intents/` metadata | Present in non-live proof JSON as fixture field | GAP as source-domain lineage |
| `paper_trade_id` | `assemble_paper_execution_ledger_entry` derives `"pt_" + risk_decision_id`; proof fixtures use scenario-specific IDs | Replay step | Paper ledger proof and replay proof | Concrete in paper ledger domain, fixture naming differs from service derivation |
| `shadow_decision_id` | No current domain owner; proof fixture only | Shadow comparison proof rows | `shadow_comparison_result.json` | GAP as domain lineage |
| `replay_step_id` | `assemble_replay_backtest_step` derives `"rstep_" + paper_trade_id` | Replay summary aggregation | Replay step domain, not exposed in current latest proof JSON scenario rows | Concrete in domain; absent from latest proof scenario JSON |

## 6. Evidence Integrity Findings

1. Feature snapshot lineage is source-ref grounded: `FeatureSnapshot` stores `source_snapshot_ids`, `source_key_refs`, `source_ingestor_refs`, freshness maps, and stale/missing/unused feature arrays. The service constructs those values and computes trainer readiness.
2. Trainer prediction lineage is explainable enough for current packet use: it carries model version, checkpoint, confidence raw/calibrated, worker health, freshness, and top positive/negative feature codes.
3. Orchestrator and risk gateway preserve upstream IDs and explain action reasons through typed reason codes.
4. Paper ledger and replay step preserve upstream IDs and mirror reason codes, while enforcing `live_blocked = True`.
5. The latest non-live operator proof has a ready marker and consistently uses `live_gate_status = blocked_human_only`.
6. Current signal, execution-intent, and shadow per-decision domains are not source-complete. Their proof fixture IDs are useful for UI demonstration and operator proof, but they must not be treated as fully domain-produced lineage until follow-up implementation closes the gaps.

## 7. Blocks And Gaps

No safety block was encountered for writing this documentation packet.

Required follow-up gaps:

| Gap | Impact | Suggested owner |
|---|---|---|
| No concrete `signal_id` domain record or signal service | Cannot prove a source-domain prediction-to-signal stage. | 069C/069D or next Phase 2H signal-lineage subtask |
| No concrete `execution_intent_id` domain record or service | Cannot prove a source-domain risk-to-intent handoff. | Execution intent domain implementation subtask |
| No concrete `shadow_decision_id` domain record | Cannot prove shadow action as a domain event, only as proof-fixture comparison evidence. | Shadow-mode domain implementation subtask |
| Fixture `paper_trade_id` naming differs from current service derivation | Operator proof rows are coherent, but ID derivation is not byte-for-byte the current service formula. | 069D validation packet |
| Latest replay proof scenario rows omit `replay_step_id` | Replay step source can mint the ID, but latest proof JSON scenario summary does not surface it. | Replay proof payload extension |

## 8. Read-Only Verification Commands Used

The packet was assembled from read-only shell commands only:

| Command class | Purpose |
|---|---|
| `sed -n` | Read supervisor task JSON, 069A output, proof JSON, and source snippets. |
| `nl -ba ... | sed -n` | Capture line-numbered evidence pointers for V2 source files. |
| `rg --files` and `rg -n` | Inventory relevant files and locate lineage fields. |
| `find ... -type f` | Enumerate source namespaces. |

No command wrote Redis, restarted services, contacted an exchange, changed live trading state, committed, pushed, or modified V2 source.

## 9. Recommendation

`069B` is READY as an evidence packet because it maps every currently evidenced stage and explicitly marks non-owned signal, execution-intent, and shadow per-decision stages as gaps rather than silently claiming complete coverage.

PHASE2HA0_069B_EVIDENCE_PACKET_READY
