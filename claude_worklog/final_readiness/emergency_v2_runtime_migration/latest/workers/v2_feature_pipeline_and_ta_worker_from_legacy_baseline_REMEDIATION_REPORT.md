# V2 Feature Pipeline + TA Worker Remediation

Result: targeted remediation applied after the Claude remediation child produced
no stdout/stderr for more than five minutes and was stopped.

## Fixes Applied

- Added `SYMBOL_UNIVERSE_CONTRACT_REQUIRED` to the worker public payload.
- Added distinct symbol roles:
  `legacy_active_symbols`, `discovered_symbols`, `observed_symbols`,
  `training_symbols`, `paper_symbols`, `live_blocked_symbols`, and
  `binance_usdm_confirmed_symbols`.
- Classified missing public symbol-universe payload as
  `MISSING_SYMBOL_UNIVERSE_PUBLIC_PAYLOAD` and used
  `v2/backend/app/services/symbol_universe/service.py` as the service contract.
- Fixed paralysis detection test evidence by deriving worker `now_ms` from the
  input snapshot timestamps when present.
- Removed legacy-Redis-looking `market:{tf}` validation issue labels from code;
  they are now `market_input:{tf}` labels, not Redis key names.
- Repaired `v2_feature_pipeline_and_ta_worker_from_legacy_baseline_legacy_behavior_mapping.json`
  so it is valid JSON.
- Documented non-parity/evidence gaps for deferred CoinAnk, CoinAPI depth,
  Binance tape, cross-timeframe, BTC-correlation, and extended TA-family work.
- Added machine-checked legacy-surface registries:
  `LEGACY_TA_INDICATOR_FAMILIES_DEFERRED_WITH_REASON` and
  `LEGACY_FEATURE_FAMILIES_DEFERRED_WITH_REASON`, with tests proving every
  listed legacy family is either implemented or explicitly deferred with a
  reason.

## Validation

- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider v2/backend/tests/integration/cli/test_v2_feature_pipeline_and_ta_worker.py`
  passed after the surface-registry remediation: `16 passed`.
- `.venv/bin/python3 -m py_compile v2/backend/app/cli/v2_feature_pipeline_and_ta_worker.py v2/backend/app/services/feature_pipeline_and_ta/service.py`
  passed.
- JSON validation passed for the repaired legacy behavior mapping.
- Public worker payload regenerated with `live_gate=blocked_human_only`.

## Safety

- Legacy path `/home/wali/Desktop/AI BOT` was not touched.
- Old Redis was not written.
- No exchange action was introduced.
- No leverage or margin path was introduced.
- No final live approval token was created.
- Live remains `blocked_human_only`.
