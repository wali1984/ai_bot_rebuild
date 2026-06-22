# Codex Review: Zero-Miss Legacy Core To V2

Generated: `2026-05-16T00:07:41Z`

GO/NO-GO: `ZERO_MISS_LEGACY_CORE_TO_V2_CODEX_FAIL`

## Decision

Codex fails the zero-miss migration review. Claude correctly reported BLOCKED, and Codex also found one overstatement in the delivered evidence: the original smoke proof treated unresolved imports as pass as long as nothing resolved under the legacy root. Codex patched the smoke wrappers and tests so unresolved modules, missing externals, and legacy-root imports now fail.

## What Codex Fixed Directly

- Copied seven omitted preserved RL environment/runtime files from `v2/legacy_preserved` into `v2/legacy_owned_runtime` and amended the manifest.
- Repaired indentation syntax errors in the V2-owned copies of `rl/microstructure_features.py` and `rl/microstructure_aggregator.py`.
- Regenerated dependency closure and function/trainer atlases; copied runtime now has `parse_errors=0` and `py_compile` passes.
- Tightened six V2-owned smoke CLIs so `smoke_pass` requires all requested imports to resolve.
- Updated tests to assert failed smoke wrappers expose blockers and return non-zero.
- Rewrote the import proof and operator payload so the frontend truth remains NO-GO.

## Remaining Blocking Findings

1. `LEGACY_ROOT_READ_ACCESS_DENIED_FULL_216K_LOC_TREE_NOT_MIRRORED`
1. `DEPENDENCY_CLOSURE_UNRESOLVED_LOCAL_IMPORT_TOOLS`
1. `V2_OWNED_RUNTIME_SMOKE_FAILURES_IMPORTS_AND_EXTERNALS`
1. `CONFIG_KEYS_UNMAPPED_1917_OPERATOR_DECISION_REQUIRED`
1. `NATIVE_ALGORITHMIC_CORE_NOT_MIGRATED`
1. `INGEST_TECHNICAL_ANALYSIS_SOURCE_MISSING_FROM_PRESERVED_COPY`
1. `MONITORING_SOURCE_MISSING_FROM_PRESERVED_COPY`

## Current Evidence

- Preserved rebuild Python files: `253`
- V2-owned runtime Python files: `253`
- Dependency closure: `unresolved_local=1`, `external=23`, `parse_errors=0`
- Atlas: `483` classes, `939` functions
- Trainer atlas: `121` trainer files
- Strict smoke all pass: `False`

## Strict Smoke Failures

### `v2_owned_ingestors`
- `ingest.live_technical_analysis`: `UNRESOLVED` - No module named 'ingest.technical_analysis'

### `v2_owned_trainer`
- `rl.continuous_learner`: `EXTERNAL_DEPENDENCY_MISSING` - No module named 'schedule'

### `v2_owned_monitoring`
- `monitoring.oom_monitor`: `UNRESOLVED` - No module named 'monitoring'
- `monitoring.deep_troubleshooter`: `UNRESOLVED` - No module named 'monitoring'
- `monitoring.live_system_auditor`: `UNRESOLVED` - No module named 'monitoring'
- `monitoring.regression_alarms`: `UNRESOLVED` - No module named 'monitoring'

## Safety Checks

- `live_gate=blocked_human_only`
- `live_symbols=[]`
- Old Redis write scan remains PASS over `v2/backend/app`.
- Exchange mutation scan remains PASS over `v2/backend/app`.
- No live/canary/shutdown/Redis-trim approval is created.

## Required Next Work

1. Resolve or explicitly classify `tools` local imports without reading or mutating the legacy root.
2. Provide or classify missing `ingest.technical_analysis` and monitoring modules; they are not present in the preserved copy.
3. Decide external dependency policy for `schedule` and the remaining ML/data packages; do not call smoke PASS while externals are missing.
4. Map the 1,917 config keys or keep them as operator decisions.
5. Continue the native-core P0 work: feature pipeline, RL/MASA/PPO/reward, orchestrator arbitration, stop/TP/hedge paper engine, and native ingestor proof.

This review does not approve live trading, canary trading, Redis trim, or legacy shutdown.
