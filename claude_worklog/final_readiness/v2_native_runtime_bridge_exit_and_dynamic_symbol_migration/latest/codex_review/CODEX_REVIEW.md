# Codex Review: V2 Native Runtime Bridge-Exit and Dynamic Symbol Migration

GO/NO-GO: `V2_NATIVE_RUNTIME_BRIDGE_EXIT_DYNAMIC_SYMBOL_MIGRATION_CODEX_FAIL`

This review covers the bridge-exit and dynamic-symbol migration plan only. It does not approve edge, canary, live trading, legacy shutdown, Redis trim, symbol adoption, paper-symbol adoption, training-symbol adoption, checkpoint parity, or policy parity.

## Reviewed Scope

- `v2/backend/app/services/bridge_exit/native_runtime_bridge_exit.py`
- `v2/backend/app/cli/v2_native_runtime_bridge_exit_and_dynamic_symbol_migration.py`
- `v2/backend/tests/integration/cli/test_v2_native_runtime_bridge_exit_and_dynamic_symbol_migration.py`
- `v2/backend/app/services/report_center/report_registry.py`
- `claude_worklog/final_readiness/v2_native_runtime_bridge_exit_and_dynamic_symbol_migration/latest/*`
- `v2/frontend/public/v2_native_runtime_bridge_exit_and_dynamic_symbol_migration/latest/operator_dashboard_payload.json`
- current report-center public index and safe summaries

## Blocking Findings

1. **Dynamic symbol coverage overstates V2-native readiness for the three active symbols.**

   `v2_dynamic_symbol_universe_migration_status.json` marks every onboarding dimension as `V2_NATIVE` for `BTCUSDT`, `ETHUSDT`, and `SOLUSDT`. That conflicts with the same packet's bridge dependency inventory:

   ```text
   bridge_dependency_inventory.ohlcv = PLACEHOLDER_NOT_READY
   bridge_dependency_inventory.orderbook = PLACEHOLDER_NOT_READY
   bridge_dependency_inventory.trainer_predictions = V2_BRIDGE_FROM_LEGACY_REDIS

   BTCUSDT ohlcv=V2_NATIVE orderbook=V2_NATIVE prediction=V2_NATIVE
   ETHUSDT ohlcv=V2_NATIVE orderbook=V2_NATIVE prediction=V2_NATIVE
   SOLUSDT ohlcv=V2_NATIVE orderbook=V2_NATIVE prediction=V2_NATIVE
   overstated_count=9
   ```

   This violates the review requirements that V2-native current coverage is not overstated, bridge data is not mislabeled V2-native, and trainer native readiness is not overstated.

2. **Report center does not expose the bridge-exit plan.**

   The frontend public payload exists at `v2/frontend/public/v2_native_runtime_bridge_exit_and_dynamic_symbol_migration/latest/operator_dashboard_payload.json`, but the current report-center registry/index/safe-summary set has no `v2_native_runtime_bridge_exit_and_dynamic_symbol_migration` entry. Probes found no bridge-exit/dynamic-symbol migration match in:

   ```text
   v2/backend/app/services/report_center/report_registry.py
   v2/frontend/public/v2_report_center/latest/report_index.json
   v2/frontend/public/v2_report_center/latest/operator_dashboard_payload.json
   v2/frontend/public/v2_report_center/latest/latest_blockers.json
   v2/frontend/public/v2_report_center/latest/latest_next_actions.json
   v2/frontend/public/v2_report_center/latest/safe_summaries/
   ```

   This violates the requirement that the report center/frontend expose the bridge-exit plan. Frontend exposure is partial; report-center exposure is absent.

## Verified Good

- Bridge dependency inventory exists and covers 20 lanes: market prices, OHLCV, orderbook, liquidation, funding, open interest, Coinank, CoinAPI, KuCoin, TA indicators, unified features, trainer predictions, risk, orchestrator, paper intents, paper ledger, position history, alt-data, symbol universe, and website pages.
- Lane classifications use the expected taxonomy: `V2_NATIVE`, `V2_BRIDGE_FROM_LEGACY_REDIS`, `PLACEHOLDER_NOT_READY`, and `OPERATOR_DECISION_REQUIRED`. `LEGACY_REFERENCE_ONLY` is defined in code but currently has zero lanes.
- Legacy trainer and legacy Redis dependency is described as read-only through approved bridge contracts in the trainer bridge-exit plan and ingestor migration plan.
- V2-native target keys are defined for market, OHLCV, orderbook, liquidation, funding, OI, features, trainer predictions, risk/orchestrator/paper, alt-data, and symbol-universe lanes.
- The 25-symbol legacy universe is enumerated. The plan reports `v2_native_symbol_count=3` and `missing_v2_symbol_count=22`.
- Trainer bridge-exit plan is concrete and correctly says the native trainer is not yet running: `BRIDGE_ACTIVE_NATIVE_TRAINER_NOT_YET_RUNNING`.
- Ingestor migration plan identifies concrete next tasks for Binance OHLCV, Binance orderbook, liquidation expansion, Coinank per-symbol publisher, TA/features, trainer prediction bridge exit, and risk/orchestrator/paper expansion.
- Dynamic paper-trading plan does not enable live or paper symbols and keeps paper/training adoption behind governance.
- Website lane labels bridge/native/placeholder/operator states and bans trading controls, order buttons, shutdown buttons, and adopt buttons.
- First batch task descriptors are narrow enough for Codex review pairing and carry forbidden-action lists plus write allow-lists.
- No broad "migrate everything" task was found in the first batch.
- No live/canary/shutdown/Redis-trim approval, non-empty `live_symbols`, exchange mutation command, old Redis write command, raw secret, checkpoint parity claim, or policy parity claim was found in the reviewed bridge-exit scope.

## Verification

```text
python -m py_compile \
  v2/backend/app/services/bridge_exit/native_runtime_bridge_exit.py \
  v2/backend/app/cli/v2_native_runtime_bridge_exit_and_dynamic_symbol_migration.py \
  v2/backend/app/services/report_center/report_registry.py \
  v2/backend/app/cli/v2_report_center_indexer.py
```

Result: pass.

```text
PYTHONPATH=$PWD .venv/bin/pytest \
  v2/backend/tests/integration/cli/test_v2_native_runtime_bridge_exit_and_dynamic_symbol_migration.py -q
```

Result:

```text
12 passed in 0.08s
```

JSON validation:

```text
jq empty claude_worklog/final_readiness/v2_native_runtime_bridge_exit_and_dynamic_symbol_migration/latest/*.json \
  v2/frontend/public/v2_native_runtime_bridge_exit_and_dynamic_symbol_migration/latest/operator_dashboard_payload.json
```

Result: pass.

Scoped safety scan:

```text
truthy_approval=0
live_symbols_nonempty=0
exchange_mutation=0
old_redis_write=0
raw_secret=0
checkpoint_parity_claim=0
```

## Required Remediation Before Pass

1. Fix `v2_dynamic_symbol_universe_migration_status.json` and its generator so per-symbol onboarding status is per-capability accurate. At minimum, active symbols must not mark `ohlcv`, `orderbook`, or `prediction` as `V2_NATIVE` while the global lane inventory says those capabilities are placeholder or bridge.
2. Add regression coverage that fails if per-symbol capability labels contradict bridge dependency inventory classifications.
3. Register the bridge-exit packet in the report center and emit a safe summary/current blocker or next-action view so operators can see this P0 migration plan without opening the raw worklog path.
4. Re-index the report center and verify the bridge-exit plan appears in `report_index.json`, `operator_dashboard_payload.json`, and `safe_summaries`.

## Safety Scoreboard

- did_not_modify_legacy = true
- did_not_stop_v2_runtime = true
- did_not_write_old_redis = true
- did_not_call_exchange_mutation = true
- did_not_enable_live = true
- did_not_create_approvals = true
- did_not_mutate_live_symbols = true
- did_not_mutate_paper_symbols = true
- did_not_mutate_training_symbols = true
- did_not_claim_checkpoint_parity = true
- did_not_claim_policy_parity = true
- live_gate = blocked_human_only
- live_symbols = []
- approves_live = false
- approves_canary = false
- approves_legacy_shutdown = false
- approves_redis_trim = false
