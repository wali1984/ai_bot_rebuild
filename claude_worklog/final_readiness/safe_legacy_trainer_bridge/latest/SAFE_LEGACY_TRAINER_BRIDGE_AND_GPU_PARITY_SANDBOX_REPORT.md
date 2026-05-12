# Safe Legacy Trainer Bridge and GPU Parity Sandbox Report

Generated at: 2026-05-12 (current AI BOT REBUILD session)
Lane: primary_claude_lane
Risk level: L1
Gate token: `SAFE_LEGACY_TRAINER_BRIDGE_AND_GPU_PARITY_SANDBOX_READY`
Working directory: `/home/wali/Desktop/AI BOT REBUILD`

## 0. Scope and Non-Action Statement

This packet is a read-only specification. It does not edit source code, does not mutate the legacy bot, does not mutate legacy Redis, does not place/cancel orders, does not change margin or leverage, and does not flip the live gate. It defines a V2-only safe bridge contract and a GPU parity sandbox plan to be operator-approved before any future execution.

Inputs reviewed for this packet (read-only):

- `claude_worklog/final_readiness/legacy_trainer_gpu_parity/latest/LEGACY_TRAINER_GPU_PARITY_AND_V2_WRAPPER_VALIDATION_REPORT.md`
- `claude_worklog/final_readiness/legacy_trainer_gpu_parity/latest/TRAINER_GPU_RUNTIME_MAP.md`
- `claude_worklog/final_readiness/legacy_trainer_gpu_parity/latest/gpu_runtime_state.json`
- `claude_worklog/final_readiness/legacy_trainer_gpu_parity/latest/V2_PAPER_TRAINER_WRAPPER_VALIDATION.md`
- `claude_worklog/final_readiness/legacy_trainer_gpu_parity/latest/TRAINER_OUTPUT_CONTRACT.md`
- `claude_worklog/final_readiness/legacy_trainer_gpu_parity/latest/TRAINER_PARITY_COMPARISON.md`
- `claude_worklog/final_readiness/legacy_trainer_gpu_parity/latest/trainer_parity_matrix.json`
- `claude_worklog/final_readiness/legacy_trainer_gpu_parity/latest/TRAINER_FEATURE_INPUT_MAP.md`
- `claude_worklog/final_readiness/legacy_trainer_gpu_parity/latest/TRAINER_CHECKPOINT_MAP.md`
- `claude_worklog/final_readiness/legacy_trainer_gpu_parity/latest/TRAINER_STARTUP_MAP.md`
- `claude_worklog/final_readiness/legacy_trainer_gpu_parity/latest/LEGACY_TRAINER_STARTUP_DECISION_PACKET.md`
- `claude_worklog/final_readiness/legacy_trainer_restart_runtime/latest/LEGACY_TRAINER_RESTART_RUNTIME_CAPTURE_AND_V2_PARITY_SYNC_REPORT.md`
- `claude_worklog/final_readiness/legacy_trainer_restart_runtime/latest/GPU_RUNTIME_AFTER_RESTART.md`
- `claude_worklog/final_readiness/legacy_trainer_restart_runtime/latest/gpu_runtime_after_restart.json`
- `claude_worklog/final_readiness/legacy_trainer_restart_runtime/latest/process_runtime_state.json`
- `claude_worklog/final_readiness/legacy_trainer_restart_runtime/latest/LEGACY_TRAINER_VS_V2_WRAPPER_COMPARISON.md`
- `claude_worklog/final_readiness/legacy_trainer_restart_runtime/latest/LEGACY_TRAINER_PUBLISH_RISK_REVIEW.md`
- `claude_worklog/final_readiness/legacy_execution_containment/latest/LEGACY_EXECUTION_CONTAINMENT_AND_TRAINER_PARITY_SAFE_MODE_REPORT.md`
- `claude_worklog/final_readiness/v2_live_observer_shadow_twin/latest/TRAINER_BRIDGE_PARITY_STATUS.md`
- `claude_worklog/final_readiness/v2_live_observer_shadow_twin/latest/RISK_GATEWAY_FINAL_AUTHORITY_REPORT.md`
- `claude_worklog/final_readiness/v2_live_observer_shadow_twin/latest/LEGACY_LIVE_BRIDGE_IMPORTER_REPORT.md`
- `claude_worklog/final_readiness/continuous_paper_shadow_runtime/latest/paper_runtime_status.json`
- `v2/runtime/paper_online/latest/paper_runtime_status.json`
- `v2/runtime/paper_online/latest/trainer_prediction_current_record.json`

## 1. Containment Posture (Verified, Read-Only)

| Constraint | State | Raw evidence pointer |
|---|---|---|
| Working dir bounded to AI BOT REBUILD | OK | This packet writes only under `claude_worklog/final_readiness/safe_legacy_trainer_bridge/latest/` |
| Legacy bot mutation | NOT PERFORMED | No edits to `../AI BOT/**` or `./legacy_reference/**` in this task |
| Legacy Redis mutation | NOT PERFORMED | `v2_live_observer_shadow_twin/latest/legacy_live_bridge_status.json`: `legacy_redis_writes=false` |
| Exchange/capital action | NOT PERFORMED | No order/cancel/leverage/margin command issued by this packet |
| Live gate | `blocked_human_only` | `continuous_paper_shadow_runtime/latest/paper_runtime_status.json`: `live_gate_status=blocked_human_only` |
| Margin/leverage change | NOT PERFORMED | No risk/leverage config touched |
| Website work | SUPPORT-ONLY | No website edits performed by this packet |

## 2. Current Runtime Truth (Read-Only, Cited)

Source: `legacy_trainer_restart_runtime/latest/process_runtime_state.json` (2026-05-12T16:50:13Z), corroborated by `legacy_execution_containment/latest/LEGACY_EXECUTION_CONTAINMENT_AND_TRAINER_PARITY_SAFE_MODE_REPORT.md`.

| PID | Classification | CWD | Command |
|---:|---|---|---|
| 1042465 | LEGACY_ORCHESTRATOR_OBSERVED_READONLY | `/home/wali/Desktop/AI BOT` | `python3 -m rl.orchestrator_worker` |
| 3324274 | LEGACY_TRADER_OBSERVED_READONLY | `/home/wali/Desktop/AI BOT` | `python3 -u trading/trader.py` |
| 3446733 | V2_PAPER_RUNTIME_OBSERVED | `/home/wali/Desktop/AI BOT REBUILD` | `python3 -m v2.backend.app.cli.paper_online_runtime --loop --interval 30` |
| 3980694 | LEGACY_TRAINER_PROCESS_OBSERVED | `/home/wali/Desktop/AI BOT` | `python3 -m rl.hybrid_trainer --mode hybrid --training-mode live --enhanced-features` |

Additional: `LEGACY_TRAINER_MONITOR_PROCESS_NOT_OBSERVED`.

GPU state at the same window (`gpu_runtime_after_restart.json`):

- GPU: `NVIDIA GeForce RTX 5080`, driver `580.126.09`, CUDA `13.0`, persistence enabled.
- Compute apps: trainer PID `3980694` present at `1398 MiB` GPU memory.
- Torch probe (local interpreter only): `torch 2.8.0+cu128`, `cuda_available=true`, `device_name="NVIDIA GeForce RTX 5080"`.

V2 paper runtime trainer record (current, `v2/runtime/paper_online/latest/trainer_prediction_current_record.json`):

- `model_checkpoint=v2_paper_readonly_momentum_wrapper_v1`
- `source_type=V2_PAPER_TRAINER_WRAPPER`
- `freshness_state=CURRENT`
- top features: `return_5m`, `return_15m`, `volatility_10`
- `trainer_state=V2_PAPER_TRAINER_WRAPPER_CURRENT`

## 3. Legacy Output Classification (Read-Only)

From `TRAINER_OUTPUT_CONTRACT.md`, `LEGACY_TRAINER_PUBLISH_RISK_REVIEW.md`, and `TRAINER_FEATURE_INPUT_MAP.md`:

| Surface | Type | Risk class | Source evidence |
|---|---|---|---|
| `prediction:<symbol>:<timeframe>` hashes | legacy Redis hash | OBSERVE-ONLY for V2 | hybrid_trainer.py / monitor_trainer_predictions.py |
| `wma:trainer:predictions` stream | legacy Redis stream | OBSERVE-ONLY for V2 | `LEGACY_TRAINER_PUBLISH_RISK_REVIEW.md` |
| `wma:proposals` stream | legacy Redis stream (proposals) | NOT-CONSUMED-BY-V2; trader-observed only | XLEN delta 187 over 31 samples |
| `signals:trading:primary` | legacy Redis stream | NOT-CONSUMED-BY-V2 | latest id `1778602212078-0`, age 9s |
| `signals:trading:asjad` | legacy Redis stream (stale) | IGNORE | last id age 8,326,281 s |
| `executed_signals` | legacy Redis stream | EVIDENCE-OF-LIVE-EXECUTION (legacy origin) | delta 2 over window; exchange order id `49654220167` |
| `signals:debug` | legacy Redis stream | OBSERVE-ONLY for V2 | TRAINER_OUTPUT_CONTRACT.md |
| `signals:trading:last:<symbol>:<timeframe>` | legacy Redis hash | OBSERVE-ONLY for V2 | TRAINER_OUTPUT_CONTRACT.md |
| legacy feature Redis keys (`features:*`, `latest:*`, `latest:binance:ohlcv:*`, `features:coinank:liquidations:*`) | legacy Redis | OBSERVE-ONLY for V2 | gpu_optimized_trainer.py / hybrid_trainer.py |
| Legacy checkpoint files (`ppo_checkpoint_latest.zip`, `masa_checkpoint_*.pkl`, `enterprise_modules_*.pt`) | filesystem | READ-ONLY artifact; not loaded by V2 wrapper | TRAINER_CHECKPOINT_MAP.md |

Classification summary: every observed legacy surface is either OBSERVE-ONLY for V2, or evidence that the already-running legacy stack (not V2) is publishing/executing. No legacy surface is written by V2.

## 4. V2 Paper Trainer Wrapper Evidence (Current)

From `V2_PAPER_TRAINER_WRAPPER_VALIDATION.md` and `v2/runtime/paper_online/latest/trainer_prediction_current_record.json`:

- Wrapper is current and paper-online.
- Source: read-only Binance USD-M klines through `v2/backend/app/cli/paper_online_runtime.py`.
- Lineage IDs (prediction/feature_snapshot/signal/orchestrator_decision/risk_decision/execution_intent) are emitted and current.
- Paper ledger result in prior sample: `NO_FILL_RISK_BLOCKED`; latest observed: `APPROVED_FOR_PAPER_ONLY` with `exchange_order_allowed=false`, `paper_only=true`.
- Classification: `V2_PAPER_TRAINER_WRAPPER_INCOMPLETE`.
- Missing fields for full parity contract: `model_id`, `top_positive_features`, `top_negative_features`, `missing_feature_flags`, `stale_feature_flags`.

Implication: the V2 wrapper is sufficient as a current paper trainer surface but is explicitly not legacy-PPO/MASA parity. The bridge spec in §6 treats the V2 wrapper as the only writable trainer surface; the legacy trainer is OBSERVE-ONLY input.

## 5. Legacy Trainer Process and GPU Evidence (Current)

From `legacy_trainer_restart_runtime/latest/` (2026-05-12T16:50:13Z) and `legacy_trainer_gpu_parity/latest/` (2026-05-12T06:11:36Z):

- Legacy trainer process observed (PID 3980694) under `/home/wali/Desktop/AI BOT` running `rl.hybrid_trainer --mode hybrid --training-mode live --enhanced-features`.
- Trainer PID present in `nvidia-smi --query-compute-apps`: `True` (1398 MiB).
- Legacy trainer monitor process not observed.
- Earlier snapshot (06:11:36Z) showed no trainer process and `GPU_VISIBLE_BUT_TRAINER_GPU_RUNTIME_NOT_PROVEN`.
- The legacy trainer was not started by this packet; the observed run was originated outside V2.

GPU parity summary for the sandbox plan:

- Host GPU and CUDA stack are sufficient for legacy CUDA execution (`torch 2.8.0+cu128`, RTX 5080, CUDA 13.0).
- Current GPU runtime evidence is captured per `gpu_runtime_after_restart.json`.
- Full GPU parity proof for V2 requires a V2-process compute-app entry running the legacy graph, which the V2 paper wrapper does not currently produce. The sandbox plan in §7 specifies how this evidence can be safely acquired without legacy mutation.

## 6. V2-Only Safe Bridge Contract (Specification, Not Implemented)

This is a specification block. No code is written by this packet.

### 6.1 Direction

- Legacy ⇒ V2: read-only ingest of legacy Redis observe-only surfaces and on-disk checkpoint metadata.
- V2 ⇒ Legacy: forbidden. The bridge code path must not contain any Redis write, exchange call, or filesystem write under `legacy_reference/**` or `../AI BOT/**`.

### 6.2 Allowed Read Surfaces

- Legacy Redis (read-only commands only): `XLEN`, `XRANGE`, `XREVRANGE`, `XINFO STREAM`, `HGETALL`, `HMGET`, `TYPE`, `EXISTS`, `MEMORY USAGE`, `PING`.
- Legacy filesystem (read-only): `legacy_reference/.models/checkpoints/live_enhanced/checkpoint_metadata_latest.json`, latest sibling checkpoint metadata files, `*.zip.bak` and `*.pkl` for hash/identity only (no load).
- Legacy process metadata: `/proc/<pid>/cmdline`, `/proc/<pid>/cwd`, `/proc/<pid>/status`, `nvidia-smi` query CSVs.

### 6.3 Forbidden Operations (Enforced by Code Pattern)

- Any Redis write command (`XADD`, `SET`, `HSET`, `DEL`, `XDEL`, `XTRIM`, `EXPIRE`, `RENAME`, `FLUSH*`).
- Any exchange or capital action.
- Any margin or leverage change.
- Any write under `legacy_reference/**` or `../AI BOT/**`.
- Importing legacy Python modules into the V2 FastAPI process.
- Modifying or restarting `rl.hybrid_trainer`, `monitor_trainer_predictions`, `rl.orchestrator_worker`, or `trading/trader.py`.

These prohibitions are static: the bridge module must reject these intents at import boundary, not only at call time. Allowed-command allowlist must be the only routing path; default-deny.

### 6.4 Output Surfaces (V2-Only)

All bridge outputs live under V2 paths only:

- `v2/runtime/paper_online/latest/trainer_prediction_current_record.json` (existing; extended fields below)
- `v2/runtime/paper_online/latest/paper_runtime_status.json` (existing)
- `v2/runtime/legacy_bridge_readonly/latest/legacy_stream_observation.json` (proposed; observed streams only)
- `v2/runtime/legacy_bridge_readonly/latest/legacy_checkpoint_inventory.json` (proposed; hash/identity only)
- `v2/runtime/legacy_bridge_readonly/latest/legacy_process_snapshot.json` (proposed; PID/cwd/cmd only)
- `v2/runtime/legacy_bridge_readonly/latest/gpu_runtime_snapshot.json` (proposed; nvidia-smi CSV/torch probe only)

Required V2 wrapper output fields to close `V2_PAPER_TRAINER_WRAPPER_INCOMPLETE`:

- `model_id`: stable identifier of the V2 wrapper or future loaded checkpoint identity. For paper wrapper it is `v2_paper_readonly_momentum_wrapper_v1`. If a legacy checkpoint identity is mirrored, it must be a hash-pinned reference (e.g., `legacy_ppo:<sha256>` derived from a read-only metadata read), not a load.
- `top_positive_features`: ordered list (name, value, weight) of positive contributors. For paper wrapper this is derived from current `top_features` filtered for positive sign per side.
- `top_negative_features`: same as above for negative contributors.
- `missing_feature_flags`: list of input names expected but absent in the current snapshot (e.g., legacy 768-dim slots not currently sourced).
- `stale_feature_flags`: list of input names where last-update age exceeds a configured staleness window per timeframe.

Lineage continuity: every wrapper emission must still attach the existing IDs (`prediction_id`, `feature_snapshot_id`, `signal_id`, `orchestrator_decision_id`, `risk_decision_id`, `execution_intent_id`), and `live_gate_status` must remain `blocked_human_only` until the live gate is explicitly approved by a human in a separate gate.

### 6.5 Risk Gateway Authority (Unchanged)

- Orchestrator proposes; Risk Gateway is final authority.
- Bridge-derived inputs enter Risk Gateway as advisory observations only.
- Default Risk Gateway behavior on bridge-derived signals: `deny_missing_required_lineage_fields` unless the V2 wrapper supplies complete lineage and the missing-fields list is resolved.
- `exchange_order_allowed=false` is invariant of this packet.

### 6.6 Operator Approvals Required Before Any Bridge Code Lands

- Approval for the V2-only bridge module structure (default-deny Redis command allowlist).
- Approval for the new V2 output paths under `v2/runtime/legacy_bridge_readonly/latest/`.
- Approval for the extended wrapper output schema (the five missing fields).
- Explicit acknowledgement that the bridge cannot in any path load `ppo_checkpoint_latest.zip`, `masa_checkpoint_*.pkl`, or `enterprise_modules_*.pt` into the V2 FastAPI process; any future load must be subprocess-isolated and proven elsewhere.

## 7. GPU Parity Sandbox Plan (Specification, Not Executed)

This is a plan. The sandbox is not started by this packet. Starting it requires a separate operator-approved gate.

### 7.1 Objective

Produce evidence that a V2-originated process can run a legacy-equivalent PPO/MASA inference on RTX 5080 using legacy checkpoint artifacts in a manner that:

- writes no legacy Redis,
- consumes no live exchange path,
- runs in a process whose CWD is `/home/wali/Desktop/AI BOT REBUILD`,
- emits all outputs under `v2/runtime/legacy_bridge_readonly/latest/gpu_parity_sandbox/`,
- runs only against replay/fixture inputs, never live feeds.

### 7.2 Sandbox Isolation Rules

- New subprocess only; no legacy module import into V2 FastAPI.
- Dedicated environment variable allowlist; `REDIS_URL` if any must point to a V2-bounded namespace or be set to an unwritable read-only handle.
- Network egress restricted to local Redis read-only and (optional) read-only Binance public market endpoints for fixture comparison.
- No `nohup`, no detached background processes that survive operator session.
- `--training-mode replay` / `--mode inference_only` style flags must be enforced; live mode is rejected at flag parse.

### 7.3 Inputs to Sandbox

- Read-only copies (hash-verified) of the latest legacy checkpoint artifacts: `ppo_checkpoint_latest.zip`, the matching `masa_checkpoint_<ts>.pkl`, the matching `enterprise_modules_<ts>.pt`, and `checkpoint_metadata_latest.json`.
- Synthetic feature snapshots seeded from a fixed seed plus a window of recent V2 paper wrapper snapshots, padded/projected to the expected `obs_dim=768`.
- A small replay window of `ALICEUSDT@15m` and `BTCUSDT@1m` derived from V2's read-only Binance USD-M plane.

### 7.4 Outputs of Sandbox

- `gpu_parity_sandbox/run_metadata.json` (run id, checkpoint hashes, seeds, host CUDA/driver versions, start/stop times).
- `gpu_parity_sandbox/nvidia_smi_during_run.txt` (csv samples).
- `gpu_parity_sandbox/compute_apps_during_run.csv` (proves V2-originated PID is in compute-apps).
- `gpu_parity_sandbox/inference_outputs.jsonl` (per-step raw action, value head, MASA confidence, calibrated confidence; symbol/timeframe; seed).
- `gpu_parity_sandbox/parity_comparison.json` (rows comparing sandbox confidence/action distribution to V2 wrapper outputs for the same window).
- `gpu_parity_sandbox/SAFETY_LOG.md` (assertions on no Redis writes, no exchange paths, no legacy file writes, no process supervision attempts).

### 7.5 Pass Criteria

- A V2-rooted PID appears in `nvidia-smi --query-compute-apps` during the run.
- Loaded `obs_dim`/`act_dim` match `checkpoint_metadata_latest.json` (`obs_dim=768`, `act_dim=7`).
- For at least one matched window, sandbox outputs include a non-null `model_id` (e.g., `legacy_ppo:<sha256-of-checkpoint>`), `top_positive_features`, `top_negative_features`, `missing_feature_flags`, `stale_feature_flags`.
- No legacy Redis write, no exchange order, no legacy file mutation, no margin/leverage change observed during the run.
- Live gate observed `blocked_human_only` continuously.

### 7.6 Fail/Abort Conditions

- Any attempt to call a non-allowlisted Redis command from the sandbox process.
- Any open/write file descriptor under `legacy_reference/**` or `../AI BOT/**`.
- Any network connection to an exchange endpoint that is not the configured read-only public market plane.
- Any change in compute-apps that is not the sandbox PID and not a pre-existing legacy/V2 process.
- Any reduction in V2 paper runtime freshness beyond the loop interval during the sandbox run.

### 7.7 Rollback

- Sandbox is a single-process replay; rollback is `SIGTERM` then cleanup of `gpu_parity_sandbox/` artifacts.
- No persistent state outside `v2/runtime/legacy_bridge_readonly/latest/gpu_parity_sandbox/` is created.

## 8. Parity Matrix (Carried Forward, Not Re-Run)

From `trainer_parity_matrix.json` (2026-05-12T06:11:36Z), updated with restart-window observations:

| Area | Classification | Note for this gate |
|---|---|---|
| legacy trainer file atlas | parity_verified | Used as input to sandbox spec only |
| legacy PPO/MASA runtime process | observed_readonly (PID 3980694 since 2026-05-12 restart window) | Not started by this packet |
| legacy trainer monitor process | missing_runtime_evidence | Out of scope for this gate |
| GPU availability on host | parity_verified | Sufficient for sandbox |
| current trainer GPU use | observed_readonly (legacy PID in compute-apps) | V2-process GPU use not yet proven |
| legacy checkpoint inventory | parity_verified | Used as identity-only input to sandbox |
| checkpoint identity used by V2 wrapper | v2_simplified_wrapper_not_full_parity | Must remain `v2_paper_readonly_momentum_wrapper_v1` until sandbox completes |
| feature input parity | v2_simplified_wrapper_not_full_parity | Sandbox must map 768-dim padding/projection |
| confidence behavior parity | v2_simplified_wrapper_not_full_parity | Sandbox must capture PPO/MASA agreement and calibration |
| V2 current paper lineage | wrapper_equivalent_for_paper | Continues to satisfy paper-only invariants |
| V2 wrapper required output completeness | blocked | Five missing fields tracked in §6.4 |
| legacy-to-V2 full parity | blocked | Sandbox required before claim |

## 9. Verdict for This Gate

This packet defines:

- a read-only legacy output classification table that does not require V2 to write legacy surfaces,
- a V2-only safe bridge contract that is default-deny, observe-only, and lineage-complete,
- a GPU parity sandbox plan that is process-isolated, replay-only, and produces V2-rooted compute-app evidence,
- explicit operator approvals required before any bridge code or sandbox run.

All current invariants hold:

- V2 paper runtime current and paper-only.
- Risk Gateway final authority retained; `exchange_order_allowed=false`.
- `legacy_redis_writes=false`, `writes_only_local_v2_artifacts=true`.
- Live gate `blocked_human_only`.
- No legacy mutation, no exchange action, no margin/leverage change occurred in this task.

Gate result: `SAFE_LEGACY_TRAINER_BRIDGE_AND_GPU_PARITY_SANDBOX_READY`.

This readiness applies to the specification packet only. Executing the bridge or sandbox requires the separate operator approvals listed in §6.6 and §7.

## 10. Outstanding Items (Tracked, Not Blocking This Gate)

- Five missing V2 wrapper output fields (§6.4) to be implemented under a future task.
- V2-rooted GPU compute-app evidence (§7.5) to be produced under a future sandbox-run task.
- Legacy trainer monitor process is not observed; tracked under prior `legacy_trainer_restart_runtime` gate.
- Codex non-live review for prior restart-runtime packet recorded `LEGACY_TRAINER_RESTART_RUNTIME_CAPTURE_CODEX_FAIL`; attaches to full-parity gate, not this read-only spec gate.

## 11. Evidence Pointers Index

- `claude_worklog/final_readiness/legacy_trainer_gpu_parity/latest/LEGACY_TRAINER_GPU_PARITY_AND_V2_WRAPPER_VALIDATION_REPORT.md`
- `claude_worklog/final_readiness/legacy_trainer_gpu_parity/latest/trainer_parity_matrix.json`
- `claude_worklog/final_readiness/legacy_trainer_gpu_parity/latest/TRAINER_OUTPUT_CONTRACT.md`
- `claude_worklog/final_readiness/legacy_trainer_gpu_parity/latest/TRAINER_FEATURE_INPUT_MAP.md`
- `claude_worklog/final_readiness/legacy_trainer_gpu_parity/latest/TRAINER_CHECKPOINT_MAP.md`
- `claude_worklog/final_readiness/legacy_trainer_gpu_parity/latest/TRAINER_GPU_RUNTIME_MAP.md`
- `claude_worklog/final_readiness/legacy_trainer_gpu_parity/latest/gpu_runtime_state.json`
- `claude_worklog/final_readiness/legacy_trainer_gpu_parity/latest/V2_PAPER_TRAINER_WRAPPER_VALIDATION.md`
- `claude_worklog/final_readiness/legacy_trainer_gpu_parity/latest/LEGACY_TRAINER_STARTUP_DECISION_PACKET.md`
- `claude_worklog/final_readiness/legacy_trainer_restart_runtime/latest/LEGACY_TRAINER_RESTART_RUNTIME_CAPTURE_AND_V2_PARITY_SYNC_REPORT.md`
- `claude_worklog/final_readiness/legacy_trainer_restart_runtime/latest/GPU_RUNTIME_AFTER_RESTART.md`
- `claude_worklog/final_readiness/legacy_trainer_restart_runtime/latest/gpu_runtime_after_restart.json`
- `claude_worklog/final_readiness/legacy_trainer_restart_runtime/latest/process_runtime_state.json`
- `claude_worklog/final_readiness/legacy_trainer_restart_runtime/latest/LEGACY_TRAINER_PUBLISH_RISK_REVIEW.md`
- `claude_worklog/final_readiness/legacy_execution_containment/latest/LEGACY_EXECUTION_CONTAINMENT_AND_TRAINER_PARITY_SAFE_MODE_REPORT.md`
- `claude_worklog/final_readiness/v2_live_observer_shadow_twin/latest/TRAINER_BRIDGE_PARITY_STATUS.md`
- `claude_worklog/final_readiness/v2_live_observer_shadow_twin/latest/RISK_GATEWAY_FINAL_AUTHORITY_REPORT.md`
- `claude_worklog/final_readiness/v2_live_observer_shadow_twin/latest/LEGACY_LIVE_BRIDGE_IMPORTER_REPORT.md`
- `claude_worklog/final_readiness/continuous_paper_shadow_runtime/latest/paper_runtime_status.json`
- `v2/runtime/paper_online/latest/paper_runtime_status.json`
- `v2/runtime/paper_online/latest/trainer_prediction_current_record.json`
