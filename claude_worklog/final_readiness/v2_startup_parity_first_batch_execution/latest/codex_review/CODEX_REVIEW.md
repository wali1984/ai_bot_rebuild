# Codex Review: V2 Startup Parity First-Batch Execution

GO/NO-GO: `V2_STARTUP_PARITY_FIRST_BATCH_EXECUTION_CODEX_PASS`

This review covers the first-batch startup-parity execution packet only.
It does not approve edge, canary, live trading, legacy shutdown, Redis trim,
dynamic symbol adoption, trainer native readiness, checkpoint parity, or full
migration.

## Findings

No blocking findings remain after scoped V2-side remediation during this
review.

## Fixes Applied During Review

- Added explicit per-task implementation metadata:
  `implementation_artifact`, `implementation_status`, `blocked_reason`,
  `target_v2_keys`, `does_not_fake_data`, `missing_source_policy`,
  `old_redis_write=false`, `exchange_mutation=false`, and
  `live_or_shutdown_approval=false`.
- Propagated those fields into the aggregate status, public per-task payloads,
  and operator dashboard task summaries.
- Registered `v2_startup_parity_first_batch_execution` in the report center and
  re-indexed the frontend report-center payload.

## Verified

- All 10 first-batch tasks have an implementation artifact or an explicit
  block reason. The implementation artifacts are scoped functions in
  `v2/backend/app/services/native_runtime_migration/first_batch_executor.py`.
- Tasks are narrow and not broad audits:
  `codex_review_required=true`, `broad_audit=false`, and scoped file-lock groups
  are present for every task.
- Dynamic 25-symbol coverage is refreshed:
  `base_universe_size=25`, `active_symbol_count=3`, and symbol rosters remain
  unchanged pending governance.
- Missing upstream data is marked explicitly. Examples:
  BTC OHLCV is `PLACEHOLDER_NOT_READY / NO_CLIENT_PRESENT`; BTC orderbook is
  `PLACEHOLDER_NOT_READY / MISSING_SOURCE`; non-active feature symbols remain
  `PLACEHOLDER_NOT_READY / MISSING_SOURCE`.
- Bridge labels are honest. BTC CoinAnk and trainer prediction are
  `V2_BRIDGE_FROM_LEGACY_REDIS / BRIDGE_ONLY`, not V2-native.
- V2 target keys are defined per implemented/scaffolded task, including
  `v2:market:ohlcv:binance:{symbol}:{timeframe}`,
  `v2:market:orderbook:binance:{symbol}`,
  `v2:prediction:{symbol}:{timeframe}`, and
  `v2:trainer:dataset:manifest`.
- Trainer bridge-exit does not claim native readiness:
  `trainer_native_readiness_claimed=false` and
  `trainer_native_claim=false`.
- The dataset builder uses the V2 replay dataset manifest only:
  `uses_only_v2_owned_evidence=true`, `checkpoint_compatibility_claimed=false`,
  and `policy_architecture_parity_claimed=false`.
- Feature pipeline/TA active coverage is limited to BTCUSDT, ETHUSDT, and
  SOLUSDT; dynamic symbols are gated on real upstream ingestors and are not
  filled with fake features.
- Startup-order control plane is read-only observability and does not start,
  stop, install, or enable services.
- Report center exposes the lane with `blocks_live=true`,
  `blocks_shutdown=true`, and `blocks_production_equivalence=true`.
- High-throughput scheduler has 3 active lanes while automatable work remains,
  and file locks are unique.

## Safety

- `live_gate=blocked_human_only`
- `live_symbols=[]`
- `approves_live=false`
- `approves_canary=false`
- `approves_legacy_shutdown=false`
- `approves_redis_trim=false`
- No executable old-Redis write path was found in the reviewed V2 first-batch
  code, CLI, worklog artifacts, or public payloads.
- No exchange mutation path was found.
- No raw secret material was found. CoinAPI is represented only by env-var name
  with `value_read_or_emitted=false`.

## Verification

```text
python -m py_compile \
  v2/backend/app/services/native_runtime_migration/first_batch_executor.py \
  v2/backend/app/services/native_runtime_migration/contracts.py \
  v2/backend/app/services/native_runtime_migration/safety.py \
  v2/backend/app/cli/v2_startup_parity_first_batch_execution.py \
  v2/backend/app/services/report_center/report_registry.py \
  v2/backend/app/cli/v2_report_center_indexer.py

PYTHONPATH=$PWD .venv/bin/pytest \
  v2/backend/tests/integration/cli/test_v2_startup_parity_first_batch_execution.py -q

PYTHONPATH=$PWD .venv/bin/pytest \
  v2/backend/tests/unit/services/report_center/test_report_center.py -q

PYTHONPATH=$PWD .venv/bin/python \
  -m v2.backend.app.cli.v2_startup_parity_first_batch_execution

PYTHONPATH=$PWD .venv/bin/python \
  -m v2.backend.app.cli.v2_report_center_indexer --once --json

jq empty startup-first-batch and report-center JSON artifacts
```

Results: py_compile passed, first-batch integration tests passed `20/20`,
report-center tests passed `13/13`, packet regeneration passed, report-center
re-index passed, and JSON validation passed.

