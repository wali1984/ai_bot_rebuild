# Codex Review: V2 Native Trainer Bridge-Exit Prediction Publisher

GO/NO-GO: `V2_NATIVE_TRAINER_BRIDGE_EXIT_PREDICTION_PUBLISHER_CODEX_PASS`

This review covers the V2 native trainer bridge-exit prediction publisher only.
It does not approve edge, canary, live trading, legacy shutdown, Redis trim,
checkpoint compatibility, model parity, paper-symbol adoption, or trainer-symbol
adoption.

## Verified

- The 25-symbol dynamic universe is represented across 1m and 5m.
- The publisher emitted 50 prediction rows to `v2:prediction:{symbol}:{timeframe}`.
- The Redis write audit reports `writes_attempted=52`, `writes_succeeded=52`,
  `writes_failed=0`, and `old_redis_write_attempts=0`.
- Prediction keys in the packet all start with `v2:prediction:`.
- `v2:trainer:prediction_publisher_status` exists and reports
  `published_count=50`, `contract_only_count=50`, `trainer_native_readiness_claimed=false`,
  and `v2_native_trainer_ready=false`.
- `v2:trainer:heartbeat` exists. The live heartbeat key is shared by V2 trainer
  components and currently reflects the V2 RL core heartbeat; this does not
  create an unsafe approval or old-Redis write.
- The sampled Redis prediction payload includes all required provenance/safety
  fields: `prediction_id`, `symbol`, `timeframe`, `generated_at`,
  `feature_snapshot_id`, `trainer_source`, `model_source`,
  `prediction_source_classification`, expected-move fields, confidence fields,
  feature freshness, missing/stale flags, checkpoint blocker, model blockers,
  paper-fill gate fields, approval fields, `live_gate`, and `live_symbols`.
- Missing/stale feature state remains explicit. The sampled payload reports
  `feature_freshness_state=MISSING_OR_STALE` with stale/missing flags rather than
  fabricated values.
- Trainer readiness is not overstated:
  `trainer_source=V2_NATIVE_CONTRACT_ONLY`,
  `trainer_native_readiness_claimed=false`, and `v2_native_trainer_ready=false`.
- Strict paper-fill safety remains active. Packet rows have
  `paper_fill_allowed=false`, and sampled payloads are blocked with
  `paper_fill_gate_status=BLOCKED_BASELINE_OR_CONTRACT_ONLY`.
- Existing stronger prediction preservation is implemented and tested. This
  runtime packet published 50 contract-only rows and did not report unsafe
  overwrites.
- Report center exposes `v2_native_trainer_prediction_publisher` with
  `blocks_live=true`, `blocks_shutdown=true`, and
  `blocks_production_equivalence=true`.

## Safety

- `live_gate=blocked_human_only`
- `live_symbols=[]`
- `approves_live=false`
- `approves_canary=false`
- `approves_legacy_shutdown=false`
- `approves_redis_trim=false`
- No exchange mutation path was found in the reviewed publisher code or packet
  artifacts.
- No old-Redis write path was found. The publisher rejects non-`v2:*` writes.
- No raw secret material was found in the reviewed publisher code or packet
  artifacts.

## Verification

```text
python -m py_compile \
  v2/backend/app/services/trainer_bridge_exit/native_prediction_publisher.py \
  v2/backend/app/cli/v2_native_trainer_prediction_publisher.py \
  v2/backend/app/services/report_center/report_registry.py
```

Result: pass.

```text
PYTHONPATH=$PWD .venv/bin/pytest \
  v2/backend/tests/integration/cli/test_v2_native_trainer_prediction_publisher.py \
  v2/backend/tests/unit/services/report_center/test_report_center.py -q
```

Result: `30 passed in 0.15s`.

```text
PYTHONPATH=$PWD .venv/bin/python \
  -m v2.backend.app.cli.v2_report_center_indexer --once --json

jq empty trainer-publisher and report-center JSON artifacts
```

Result: report-center re-index passed; JSON validation passed.

