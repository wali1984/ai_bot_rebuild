# Legacy Execution Containment and Trainer Parity Safe-Mode Report

Generated at: 2026-05-12T (current session, AI BOT REBUILD)
Lane: primary_claude_lane
Risk level: L1
Gate token: `LEGACY_EXECUTION_CONTAINMENT_AND_TRAINER_PARITY_SAFE_MODE_READY`

## 1. Containment Posture

| Constraint | State | Raw evidence pointer |
|---|---|---|
| Working directory bounded to AI BOT REBUILD | OK | This packet is materialized under `claude_worklog/final_readiness/legacy_execution_containment/latest/` (V2 root only). |
| Legacy bot mutation | NOT PERFORMED | This task performed no edits under `../AI BOT/**`; only reads under V2 paths. |
| Legacy Redis mutation | NOT PERFORMED | `v2_live_observer_shadow_twin/latest/legacy_live_bridge_status.json:"legacy_redis_writes": false`. |
| Exchange/capital action | NOT PERFORMED | This task issued no order/cancel/leverage/margin command. |
| Live gate | `blocked_human_only` | `continuous_paper_shadow_runtime/latest/paper_runtime_status.json:"live_gate_status":"blocked_human_only"`. |
| Website work | SUPPORT-ONLY | No website edit performed by this packet. |

This task is read-only and produces only the two artifacts required by its dispatch.

## 2. Runtime Truth (Observed, Read-Only)

Source: `claude_worklog/final_readiness/legacy_trainer_restart_runtime/latest/PROCESS_RUNTIME_VERIFICATION.md` and `process_runtime_state.json` (generated 2026-05-12T16:50:13Z).

| PID | Classification | CWD | Command |
|---:|---|---|---|
| 1042465 | LEGACY_ORCHESTRATOR_OBSERVED_READONLY | `/home/wali/Desktop/AI BOT` | `python3 -m rl.orchestrator_worker` |
| 3324274 | LEGACY_TRADER_OBSERVED_READONLY | `/home/wali/Desktop/AI BOT` | `python3 -u trading/trader.py` |
| 3446733 | V2_PAPER_RUNTIME_OBSERVED | `/home/wali/Desktop/AI BOT REBUILD` | `python3 -m v2.backend.app.cli.paper_online_runtime --loop --interval 30` |
| 3980694 | LEGACY_TRAINER_PROCESS_OBSERVED | `/home/wali/Desktop/AI BOT` | `python3 -m rl.hybrid_trainer --mode hybrid --training-mode live --enhanced-features` |

Additional classification: `LEGACY_TRAINER_MONITOR_PROCESS_NOT_OBSERVED`.

V2 paper runtime maximum sample age during the restart observation window was 33 seconds — within the loop interval and observed continuously alive.

## 3. Legacy Execution Containment Findings

### 3.1 Legacy executes outside V2 control plane
The legacy trader (`trading/trader.py`, PID 3324274) and legacy hybrid trainer (PID 3980694) both run under CWD `/home/wali/Desktop/AI BOT`, parented outside the V2 paper runtime tree. V2 has no supervisor handle to start, stop, or modify these processes, and this task does not attempt to.

Raw stream evidence (`legacy_trainer_restart_runtime/latest/LEGACY_TRAINER_PUBLISH_RISK_REVIEW.md`):
- `executed_signals` delta over the 31-sample window = `2`
- Exchange order id observed in legacy stream: `49654220167`
- Status: `PUBLISH_PATH_REQUIRES_OPERATOR_DECISION`

These executions were emitted by the already-running legacy stack; V2 did not originate, mediate, or approve them. The containment principle is that V2 never sits in the legacy execution path.

### 3.2 V2 cannot reach the exchange
- `continuous_paper_shadow_runtime/latest/paper_runtime_status.json:"exchange_orders": false`.
- `v2_live_observer_shadow_twin/latest/RISK_GATEWAY_FINAL_AUTHORITY_REPORT.md` for the most recent shadow signal:
  - `current risk result: BLOCKED`
  - `reason: deny_missing_required_lineage_fields`
  - `exchange_order_allowed: False`
- `paper_runtime_status.json:"legacy_redis_writes": false` and `"writes_only_local_v2_artifacts": true`.

V2 Risk Gateway holds final authority and the latest evaluated signal was BLOCKED. There is no observed V2 path that produces an exchange action.

### 3.3 Legacy Redis writes from V2 are not occurring
- `v2_live_observer_shadow_twin/latest/legacy_live_bridge_status.json:"legacy_redis_writes": false`, `"redis_ping":"PONG"`, `streams inspected: 6`.
- The legacy live bridge importer uses read-only inspection and denies Redis write commands by code before execution (per `LEGACY_LIVE_BRIDGE_IMPORTER_REPORT.md`).

## 4. Trainer Parity Safe-Mode Findings

Source: `legacy_trainer_restart_runtime/latest/TRAINER_BRIDGE_PARITY_STATUS.md` (via mirrored `v2_live_observer_shadow_twin/latest/TRAINER_BRIDGE_PARITY_STATUS.md`).

| Item | State |
|---|---|
| Legacy trainer process | `PROCESS_OBSERVED_READONLY` |
| Legacy trainer monitor | `PROCESS_NOT_OBSERVED` |
| GPU runtime | `GPU_RUNTIME_EVIDENCE_MISSING` |
| V2 wrapper | `CURRENT` |
| Parity | `PARTIAL_RUNTIME_BRIDGE_PARITY_NOT_FULL_MODEL_PARITY` |

Safe-mode interpretation:
- The V2 wrapper observes the legacy trainer through artifact/Redis read paths only; it does not import the legacy PPO/MASS model nor claim equivalent inference.
- Trainer monitor is not observed, so trainer-stale/restart events are inferred from stream deltas rather than monitor truth — V2 must therefore continue to treat trainer signals as advisory until full model parity is independently re-attested.
- GPU runtime evidence is missing for this measurement, so no GPU parity claim is made.
- Codex non-live review for the prior restart-runtime packet recorded `LEGACY_TRAINER_RESTART_RUNTIME_CAPTURE_CODEX_FAIL` (`CODEX_GO_NO_GO.md`). That fail attaches to the full-parity gate, not to this read-only containment gate.

Conclusion: trainer parity remains in **partial bridge / not full model parity** mode. The safe-mode contract is therefore: V2 ingests trainer signals as observed inputs, runs them through V2 Risk Gateway which holds final authority, and exchange/capital outputs remain blocked.

## 5. Risk Gateway Paper-Only Status

- Boundary doctrine: orchestrator proposes; Risk Gateway is final authority; trader executes only on approved intents; orchestrator cannot bypass risk gateway (`orchestrator_risk_boundary/latest/ORCHESTRATOR_RISK_GATEWAY_BOUNDARY.md`, gate `ORCHESTRATOR_RISK_GATEWAY_BOUNDARY_READY`).
- Current observed evaluation: `BLOCKED` with `deny_missing_required_lineage_fields`, `exchange_order_allowed: False`.
- Continuous paper shadow runtime gate: `CONTINUOUS_PAPER_SHADOW_RUNTIME_READY` with `exchange_orders=false`, `legacy_redis_writes=false`, `writes_only_local_v2_artifacts=true`, `live_gate_status=blocked_human_only`.

## 6. Containment & Safe-Mode Verdict

All read-only conditions for legacy execution containment and trainer parity safe-mode are met for this gate:

- V2 paper runtime is operational and observed continuously (`V2_PAPER_RUNTIME_OBSERVED`, max age 33s).
- V2 does not mutate legacy code, legacy Redis, or exchange state — verified by zero-write evidence and read-only importer status.
- Legacy execution observed in `executed_signals` originates from the legacy stack; V2 has no causal link in that path.
- V2 Risk Gateway is final authority and currently blocks; exchange orders disabled.
- Trainer bridge runs in partial-parity safe-mode; full model parity remains an explicit non-claim.
- Live gate remains `blocked_human_only`.

Gate result: `LEGACY_EXECUTION_CONTAINMENT_AND_TRAINER_PARITY_SAFE_MODE_READY`.

## 7. Outstanding Items (Tracked, Not Blocking This Gate)

- Trainer monitor process is not observed; full restart-runtime parity remains under `LEGACY_TRAINER_RESTART_RUNTIME_CAPTURE_CODEX_FAIL` and is the scope of a separate gate.
- GPU runtime evidence missing; full GPU parity requires its own re-capture.
- Codex audits for `no_live_side_effects`, `current_runtime_truth`, `public_dashboard_truth`, and `legacy_bridge_readonly` are queued as `pending` under `claude_worklog/agent_supervisor/tasks/`.

## 8. Evidence Pointers Index

- `claude_worklog/final_readiness/legacy_trainer_restart_runtime/latest/PROCESS_RUNTIME_VERIFICATION.md`
- `claude_worklog/final_readiness/legacy_trainer_restart_runtime/latest/process_runtime_state.json`
- `claude_worklog/final_readiness/legacy_trainer_restart_runtime/latest/RESTART_OBSERVATION_SUMMARY.md`
- `claude_worklog/final_readiness/legacy_trainer_restart_runtime/latest/LEGACY_TRAINER_PUBLISH_RISK_REVIEW.md`
- `claude_worklog/final_readiness/legacy_trainer_restart_runtime/latest/CODEX_GO_NO_GO.md`
- `claude_worklog/final_readiness/v2_live_observer_shadow_twin/latest/LEGACY_LIVE_BRIDGE_IMPORTER_REPORT.md`
- `claude_worklog/final_readiness/v2_live_observer_shadow_twin/latest/legacy_live_bridge_status.json`
- `claude_worklog/final_readiness/v2_live_observer_shadow_twin/latest/RISK_GATEWAY_FINAL_AUTHORITY_REPORT.md`
- `claude_worklog/final_readiness/v2_live_observer_shadow_twin/latest/TRAINER_BRIDGE_PARITY_STATUS.md`
- `claude_worklog/final_readiness/orchestrator_risk_boundary/latest/ORCHESTRATOR_RISK_GATEWAY_BOUNDARY.md`
- `claude_worklog/final_readiness/continuous_paper_shadow_runtime/latest/paper_runtime_status.json`
- `claude_worklog/final_readiness/continuous_paper_shadow_runtime/latest/GO_NO_GO.md`
