# Codex Review: V2 Legacy Startup Manifest Parity and Bridge Exit

GO/NO-GO: `V2_LEGACY_STARTUP_MANIFEST_PARITY_AND_BRIDGE_EXIT_CODEX_PASS`

This review covers startup-manifest parity and bridge-exit planning only.
It does not approve edge, canary, live trading, legacy shutdown, Redis trim,
dynamic paper-symbol adoption, or trainer/checkpoint parity.

## Findings

No blocking findings remain after scoped V2-side remediation during this
review.

## Fixes Applied During Review

- The planner now parses the current legacy startup script read-only:
  `/home/wali/Desktop/AI BOT/scripts/start_all_services_production.sh`.
  The repo snapshot is kept only as drift evidence.
- The dynamic symbol coverage matrix no longer labels trainer-bridge
  predictions or CoinAnk bridge data as V2-native. Active BTC/ETH/SOL
  prediction and CoinAnk families are now `V2_BRIDGE_FROM_LEGACY_REDIS`;
  OHLCV/orderbook remain `PLACEHOLDER_NOT_READY`.
- First-batch tasks now carry explicit `codex_review_required=true`,
  `broad_audit=false`, `status=QUEUED_NOT_RUNNING`, and per-task
  `file_lock_group`.
- The startup parity lane is registered in the V2 report center and was
  re-indexed into the frontend report-center payload.

## Verified

- Canonical manifest source is the local legacy startup script:
  `parsing_source_used=local`, `local_runtime_script_used_for_parsing=true`.
  Local SHA is `2b5a9a63fc76487b3a6f46cdbb8060044aeab69c5f8117bbf30e7efdb8a10ca9`.
- All required phases are represented: preflight, monitoring, ingestors,
  feature/resampler, technical analysis, universe validation, trainer,
  orchestrator, traders, portfolio monitors, and health validation.
- All required major services are represented in the 38-row manifest/parity
  matrix, including Binance/KuCoin/CoinAnk/CoinAPI ingestors, liquidation
  lanes, realtime price provider, resampler, feature pipeline, TA, trainer,
  orchestrator, traders, portfolio monitors, and health probe.
- Service classifications are explicit: `V2_NATIVE`, `V2_BRIDGE_FROM_LEGACY_REDIS`,
  `LEGACY_REFERENCE_ONLY`, `V2_MISSING`, `OPERATOR_DECISION_REQUIRED`, or
  `NOT_REQUIRED_FOR_V2_PAPER_SHADOW`.
- Redis contract map has 24 rows, `v2_writes_only_v2_namespace=true`, and
  legacy bridge/reference rows require bridge labeling.
- Dynamic symbol coverage covers the 25-symbol legacy universe and keeps
  current V2 active coverage at only BTCUSDT, ETHUSDT, and SOLUSDT.
- Trainer native readiness is not claimed: `rl_hybrid_trainer` remains
  `V2_BRIDGE_FROM_LEGACY_REDIS` with native trainer/prediction publisher work
  queued as first-batch tasks.
- First-batch tasks are narrow, queue-only, and paired with Codex review
  descriptors using the supported `codex exec review --uncommitted` form.
- Report center exposes `v2_legacy_startup_manifest_parity_and_bridge_exit`
  with `blocks_live=true`, `blocks_shutdown=true`, and
  `blocks_production_equivalence=true`.

## Safety

- `live_gate=blocked_human_only`
- `live_symbols=[]`
- `approves_live=false`
- `approves_canary=false`
- `approves_legacy_shutdown=false`
- `approves_redis_trim=false`
- No executable old-Redis write path was found in the reviewed V2 planner,
  CLI, worklog artifacts, or public payload.
- No exchange mutation path was found; approval/leverage hits were safety
  scoreboard text only.
- No raw secret material was found in the reviewed startup-parity artifacts.

## Non-Blocking Note

The static parity table still retains a few legacy/snapshot-era services that
are not launched by the current local startup script. Those rows now carry
`parser_evidence.target_seen_in_manifest=false`, so they are visible as parity
references and are not evidence of current local startup execution.

## Verification

```text
python -m py_compile \
  v2/backend/app/services/legacy_startup_parity/native_runtime_legacy_parity.py \
  v2/backend/app/cli/v2_legacy_startup_manifest_parity_and_bridge_exit.py \
  v2/backend/app/services/report_center/report_registry.py \
  v2/backend/app/cli/v2_report_center_indexer.py

PYTHONPATH=$PWD .venv/bin/pytest \
  v2/backend/tests/integration/cli/test_v2_legacy_startup_manifest_parity_and_bridge_exit.py -q

PYTHONPATH=$PWD .venv/bin/pytest \
  v2/backend/tests/unit/services/report_center/test_report_center.py -q

PYTHONPATH=$PWD .venv/bin/python \
  -m v2.backend.app.cli.v2_legacy_startup_manifest_parity_and_bridge_exit

PYTHONPATH=$PWD .venv/bin/python \
  -m v2.backend.app.cli.v2_report_center_indexer --once --json

jq empty startup-parity and report-center JSON artifacts
```

Results: py_compile passed, startup parity tests passed `9/9`, report-center
tests passed `13/13`, packet regeneration passed, report-center re-index passed,
and JSON validation passed.

