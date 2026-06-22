# Codex Review: V2 Full-Observation TA Position-History Burndown

Generated: `2026-05-21T04:38:21Z`

GO/NO-GO: `V2_FULL_OBSERVATION_TA_POSITION_HISTORY_BURNDOWN_CODEX_PASS_PARTIAL_PROGRESS`

## Decision

Codex passes the TA final-slot and V2 position-history burndown as honest partial progress. The packet increases V2-owned observation coverage, keeps missing values explicit, and does not claim checkpoint compatibility, policy architecture parity, live trading, production equivalence, or legacy shutdown.

This is not a complete full-observation approval. The builder still reports `FULL_OBSERVATION_BUILDER_PARTIAL_MISSING_FIELDS` against the `1911` target dimension.

## Evidence Reviewed

Reviewed:

- `v2/backend/app/services/rl_core/full_observation_builder.py`
- `v2/backend/app/services/rl_core/position_history_aggregator.py`
- `v2/backend/tests/integration/cli/test_v2_full_observation_ta_position_history_burndown.py`
- `claude_worklog/final_readiness/v2_full_observation_ta_position_history_burndown/latest/V2_FULL_OBSERVATION_TA_POSITION_HISTORY_BURNDOWN_REPORT.md`
- `claude_worklog/final_readiness/v2_full_observation_ta_position_history_burndown/latest/ta_position_history_burndown_status.json`
- `claude_worklog/final_readiness/v2_full_observation_builder/latest/full_observation_builder_status.json`
- public frontend/operator mirrors under `v2/frontend/public/operator_runtime/...`

## Soak And Governors

Codex verified the standing runtime evidence remains healthy:

- 6h soak: `V2_RUNTIME_SOAK_6H_READY`
- observed soak minutes: `895.22`
- all V2 processes uninterrupted: `true`
- V2 namespaces never empty: `true`
- 8h war-room governor: `CODEX_8H_WAR_ROOM_REVIEW_GOVERNOR_READY`
- continuous remediation governor: `CODEX_CONTINUOUS_REMEDIATION_REVIEW_GOVERNOR_READY`
- governor fail blockers: none

The runtime safety pins remain `live_gate=blocked_human_only` and `live_symbols=[]`.

## TA Slot Review

`htf_lf_trend_agreement` now computes only when `htf_ret_pct` and `rsi_14` are present and the feature snapshot freshness state is `CURRENT`. Missing and stale cases are explicit:

- `MISSING_HTF_RET_PCT_AND_RSI_14_FROM_V2_FEATURES`
- `MISSING_HTF_RET_PCT_FROM_V2_FEATURES`
- `MISSING_RSI_14_FROM_V2_FEATURES`
- `BLOCKED_BY_FEATURE_FRESHNESS_NOT_CURRENT:<state>`
- `V2_DERIVED_FROM_FEATURES`

The neutral RSI boundary is handled deterministically, so a present `rsi_14 == 50.0` does not fall through into a missing value.

`macd_signal_strength` does not fabricate a ratio when `macd == 0.0`; it emits `MACD_ZERO_RATIO_UNDEFINED`.

## Position History Review

The position-history aggregator reads V2-owned paper data only:

- `v2:paper:positions`
- `v2:paper:ledger`
- `v2:paper:intents`
- `v2:paper:intents_held_by_paper_fill_gate`
- optional V2-owned `v2:paper:position_price_track:{symbol}`
- optional V2-owned `v2:paper:position_history:{symbol}`
- V2 paper heartbeat metadata only in the helper snapshot path

No legacy Redis key, legacy feature key, legacy log, or legacy filesystem current-truth source is consumed by the reviewed active path. The aggregator is read-only with respect to Redis.

Codex verified generic shadow intents are not counted as accepted positions. Accepted counts require ledger `accepted` rows or paper intents explicitly marked `counted_as_accepted_position=true` or `paper_fill_allowed=true`.

MFE, MAE, and ROE are not fabricated. They remain `null` with explicit V2-owned missing-source strings unless V2-owned price tracking or realized-exit evidence exists. Current proof payloads show `MISSING_V2_OWNED_POSITION_RECORD` where no paper position exists.

## Current Status

Current full-observation status:

- state: `FULL_OBSERVATION_BUILDER_PARTIAL_MISSING_FIELDS`
- target full-observation dimension: `1911`
- generated dimensions: `BTCUSDT=157`, `ETHUSDT=157`, `SOLUSDT=151`
- missing dimensions: `BTCUSDT=1754`, `ETHUSDT=1754`, `SOLUSDT=1760`
- zero-filled field count: `0`
- `checkpoint_compatibility_claimed=false`
- `policy_architecture_parity_claimed=false`
- `live_gate=blocked_human_only`
- `live_symbols=[]`

Frontend/public payloads show the same partial status, zero-fill count, and false compatibility/parity flags.

## Safety

Codex verified:

- no old Redis write path in the reviewed builder or aggregator;
- no exchange order, cancel, modify, leverage, margin, `/fapi/`, or test-order endpoint in the reviewed source;
- no torch import, pickle load, checkpoint load, or policy architecture startup;
- no legacy current-truth Redis namespace read in the reviewed source;
- no live/canary/shutdown/Redis-trim approval;
- no checkpoint compatibility or policy architecture parity claim;
- `approves_live=false`;
- `approves_canary=false`;
- `approves_legacy_shutdown=false`;
- `approves_redis_trim=false`.

Source-scan hits for `prediction:` were V2 namespaced (`v2:prediction:{symbol}:{timeframe}`), not legacy prediction keys. Exchange/leverage hits were safety-test strings and report/review text, not callable mutation paths.

## Validation

- Burndown tests: `24 passed`.
- Existing full-observation builder status tests: `9 passed`.
- `py_compile`: PASS.
- JSON/status inspection: PASS.
- Public mirror inspection: PASS.
- Old Redis namespace scan: PASS.
- Redis write scan: PASS.
- Exchange mutation scan: PASS.
- Torch/pickle/checkpoint-load scan: PASS.
- Generic shadow-intent accepted-count proof: PASS.
- MFE/MAE/ROE missing-source proof: PASS.
- Governor/soak inspection: PASS.

## Final Decision

`V2_FULL_OBSERVATION_TA_POSITION_HISTORY_BURNDOWN_CODEX_PASS_PARTIAL_PROGRESS`
