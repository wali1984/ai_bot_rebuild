# LEGACY_BASELINE_ANALYSIS — claude_replay_paper_edge_repair_from_legacy_trainer_output

Goal: confirm the legacy trainer-output path that produces predictions → signals → risk-validated actions, so V2 paper/shadow remediation aligns with legacy behavior without copying legacy live mutations.

## Cited legacy artifacts (SHA256 from copied manifests)

Source manifests (do not mutate):
- `claude_worklog/final_readiness/legacy_rl_risk_trainer_trader_closure/latest/full_runtime_copied_source_manifest.json`
- `claude_worklog/final_readiness/legacy_startup_baseline_v2_migration/latest/copied_baseline_manifest.json`

| Legacy path | size_bytes | sha256 |
|---|---:|---|
| `rl/hybrid_trainer.py` | 3,165,342 | `b7dad66b63b57c0d5c29e0fbaf67466d9c2aab81baf7a4f67b6e681e38c5b102` |
| `rl/signal_state_manager.py` | 22,330 | `62c7d46ade7d03cd378e46cba2d06d2ee63bd218b27d9a853ee221a9899e6459` |
| `rl/increase_signal_validator.py` | 13,971 | `6b1dbcb61bac934038d7be3ca16721453e4eda7263c6f7527c5583f23c7d12a0` |
| `rl/advanced_risk_management.py` | 20,633 | `db2fc5c91f270f69790c4d3e25e9b6007384b6c788a2c6dc00cf3305cf829697` |
| `rl/trainer_enhancements.py` | 21,186 | `b8159091cf1f15b536b5e4221c3952a58c6501d84248b14d23a5831c13efca23` |
| `rl/gpu_optimized_trainer.py` | 13,386 | `3203fbd34b6976a676d261f3bb2ac16ddc2bef1c80a4befc247e6cdf50bfe822` |
| `scripts/monitor_trainer_predictions.py` | 13,543 | `38068905908317415f91f76ed19797c393ee01f20135d59030289e2d697a495a` |

V2 preserved copies are at `v2/legacy_preserved/full_runtime_closure/...` and `v2/legacy_preserved/startup_baseline/...` (read-only; do not edit).

## Legacy prediction → action chain (verified from manifest layout)

1. `rl/hybrid_trainer.py` produces predictions and confidence; emits trainer outputs (publishing path → signal manager).
2. `rl/signal_state_manager.py` materializes signal state, including freshness/age and per-symbol gating.
3. `rl/increase_signal_validator.py` validates `INCREASE`/add-risk signals (cooldown, confidence threshold, regime checks).
4. `rl/advanced_risk_management.py` enforces stop-risk presence, drawdown checks, exposure caps before action is allowed.
5. `scripts/monitor_trainer_predictions.py` observes the prediction stream for staleness / health.

V2 mirror modules (read-only consumers of legacy contract):
- Prediction/signal contract → ported to V2 trainer bridge (`composition/trainer_bridge_*`).
- Increase validation contract → ported to V2 risk gateway gate set (`composition/risk_gateway/*`).
- Confidence/cooldown/freshness contract → ported to `composition/canary_profile_tightening/runtime.py`.

## What legacy enforces that V2 paper currently does not (paper-side only)

Legacy enforces validator/risk-management *inline before action emission*; V2 paper today reports the canary-tightening deny reason (`deny_canary_profile_tightening`) but still materializes fills at the paper-execution worker boundary. The paper-side wiring proposed by this task aligns the V2 *paper execution* boundary to the same predicate, mirroring legacy "validate-before-emit" without touching live.

## Confidence and missing evidence

- Confidence in legacy chain identity: HIGH (manifest sha256 verified; module roles consistent with their preserved file names and the prior trainer-bridge parity task at `claude_port_v2_trainer_bridge_full_legacy_parity/`).
- MISSING_EVIDENCE: byte-level diff between legacy `increase_signal_validator.py` predicates and V2 canary-tightening predicates; will be produced as part of the follow-up wiring task and recorded under the same task folder.

## Verification commands

- `grep -B1 -A3 -E "rl/(hybrid_trainer|signal_state_manager|increase_signal_validator|advanced_risk_management|trainer_enhancements|gpu_optimized_trainer)\.py\"" claude_worklog/final_readiness/legacy_rl_risk_trainer_trader_closure/latest/full_runtime_copied_source_manifest.json`
- `grep -B1 -A3 -E "scripts/monitor_trainer_predictions\.py\"|rl/hybrid_trainer\.py\"" claude_worklog/final_readiness/legacy_startup_baseline_v2_migration/latest/copied_baseline_manifest.json`
- `ls v2/backend/app/composition/canary_profile_tightening/`

## Conclusion

Legacy baseline is consistent with the V2 paper-side remediation. The proposal does not require copying legacy code, does not import legacy modules into V2 FastAPI, does not change live behavior, and does not create approval tokens.
