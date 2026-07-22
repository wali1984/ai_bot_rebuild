# Operator Runbook

Last verified timestamp: 2026-07-22T12:23Z for the profiled trainer publisher/observer and trainer mark-price transport; other sections retain their dated evidence

## Purpose
Provide the daily operator path for checking runtime health, paper halt state, live gate, service drift, website/iOS truth, and incident response entry points.

## Source Files
- `v2/backend/app/main.py`
- `v2/backend/app/api/v1/paper.py`
- `v2/backend/app/api/v1/derivatives.py`
- `v2/backend/app/api/v2/market_contracts.py`
- `v2/backend/app/api/v2/live_readiness.py`
- `v2/backend/app/api/v2/mobile.py`
- `v2/backend/app/cli/v2_trade_management_paper_loop.py`
- `v2/backend/app/cli/v2_runtime_drift_monitor.py`
- `v2/frontend/src/components/layout/RuntimeTruthStrip.tsx`
- `v2/mobile/Sources/AIBotV2/Views/Components/RuntimeTruthCard.swift`

## Runtime Redis Keys/API Routes
- Redis: v2:paper:performance_governor_status
- Redis: v2:paper:new_entry_emergency_halt_status
- Redis: v2:trainer:hybrid_cuda:status
- Redis: v2:monitor:runtime_drift
- Redis: v2:altdata:santiment:symbol:*
- API: /api/v2/paper/runtime-status
- API: /api/v2/live-readiness
- API: /api/v2/mobile/paper-summary
- Artifact: v2/frontend/public/operator_runtime/v2_runtime_drift/latest/status.json

## Operator/Trader/Developer Meaning
- Operator: use this document to decide whether the current runtime is safe, current, and fail-closed.
- Trader: use this document to interpret paper performance, A+ readiness, REDUCE_SIZE bootstrap rows, live gate state, and why trades are blocked.
- Developer: use this document to find the source files, route contracts, Redis keys, tests, and evidence artifacts that must stay in sync.
- Primary audience for this page: operator, trader, and developer.

## Failure Modes
- Stale runtime payload labelled as current.
- `new_entries_allowed=true` while PF is below 1 or expectancy is non-positive.
- A+ shown when final A+ rows are zero, or REDUCE_SIZE rows shown as final A+.
- Live readiness shown without signed-read and pre-submit dry-run proof.
- Santiment or another paid data source expected for symbol selection but unused.
- Feature freshness or lineage missing around `available_at`, `feature_cutoff`, `decision_time`, or `execution_time`.

## Debug Commands
- `systemctl --user list-units --type=service --all | rg "ai-bot-v2|paper|trainer"`
- `redis-cli GET v2:paper:performance_governor_status | python3 -m json.tool`
- `redis-cli GET v2:paper:new_entry_emergency_halt_status | python3 -m json.tool`
- `redis-cli GET v2:monitor:runtime_drift | python3 -m json.tool`
- `redis-cli --scan --pattern "v2:altdata:santiment:symbol:*" | wc -l`

## Validation Commands
- `python -m py_compile v2/backend/app/cli/v2_runtime_drift_monitor.py`
- `.venv/bin/pytest -q v2/backend/tests/unit/cli/test_v2_runtime_drift_monitor.py`
- `npm --prefix v2/frontend run typecheck`
- `npm --prefix v2/frontend run build`
- `swift test --package-path v2/mobile`

## Evidence Artifacts
- `goal_state/V2_CODEX_A_TO_Z_FABLE_PHASE_VALIDATION_FIX_RESOLUTION_AND_GO_LIVE_READINESS_COMPLETION/PHASE_H_BACKEND_API_CONTRACT_STATUS.json`
- `goal_state/V2_CODEX_A_TO_Z_FABLE_PHASE_VALIDATION_FIX_RESOLUTION_AND_GO_LIVE_READINESS_COMPLETION/PHASE_I_FRONTEND_ROUTE_TRUTH_STATUS.json`
- `goal_state/V2_CODEX_A_TO_Z_FABLE_PHASE_VALIDATION_FIX_RESOLUTION_AND_GO_LIVE_READINESS_COMPLETION/PHASE_J_IOS_RUNTIME_TRUTH_STATUS.json`
- `goal_state/V2_CODEX_A_TO_Z_FABLE_PHASE_VALIDATION_FIX_RESOLUTION_AND_GO_LIVE_READINESS_COMPLETION/PHASE_K_RUNTIME_ALERT_MATRIX.json`
- `goal_state/V2_CODEX_A_TO_Z_FABLE_PHASE_VALIDATION_FIX_RESOLUTION_AND_GO_LIVE_READINESS_COMPLETION/RUNTIME_SNAPSHOTS/PHASE_K_RUNTIME_DRIFT_STATUS.json`

## Current Runtime Truth
- Paper state: `HALTED_PERFORMANCE`, PF about `0.4613`, expectancy about `-5.2575 bps`, and `new_entries_allowed=false`.
- Trainer state: `WEIGHTS_UPDATING` with feedback rows present.
- Live state: `blocked_human_only`; dry-run packets must not submit or mutate exchange state.
- Runtime drift: Phase K monitor reports `services_stale=0` after V2 restarts and the legacy comparator stop.
- Santiment: `v2:altdata:santiment:symbol:*` has runtime symbol-selection evidence and the paid-ingestor-unused alert is passing.

## Profiled trainer-publisher check (2026-07-22)

The publisher is online when all five planes agree:

1. `systemctl` reports `active/running`, a nonzero PID and no new restarts;
2. the process CWD, executable, `PYTHONPATH` and `AI_BOT_CODE_SHA` resolve to
   immutable release `e34af1e6a6bb9b54818e18f9279fcc9904de0922`;
3. the publisher holds the ledger writer lock and open main/WAL/SHM file
   descriptors throughout both compute and idle intervals;
4. the actual observer unit, `ai-bot-v2-native-cuda-trainer-persistent.service`,
   stays active and publishes `probe_succeeded=true`, `scan_complete=true`,
   `ledger_integrity_verified=true`, and zero exclusions; and
5. a completed cycle and the independent observer/loader agree on the appended
   strict row count.

Run:

```bash
systemctl --user show ai-bot-v2-profiled-base-feature-publisher.service \
  -p ActiveState -p SubState -p MainPID -p NRestarts -p ExecMainStartTimestamp

pid=$(systemctl --user show ai-bot-v2-profiled-base-feature-publisher.service \
  -p MainPID --value)
readlink -f "/proc/$pid/cwd"
tr '\0' '\n' < "/proc/$pid/environ" | \
  rg '^(AI_BOT_CODE_SHA|PYTHONPATH|PYTHONPYCACHEPREFIX|LIVE_GATE)='

jq '{cycle_started_at,cycle_completed_at,classification,selected_symbols,
     published_symbols,failures,masked_cost_observation_symbol_count}' \
  /home/wali/ai_bot_local_data/v2_native_trainer/profiled_base_publisher_v1/profiled_base_publisher_status_v1.json

lsof -p "$pid" | rg \
  'durable_feature_snapshot_ledger|profiled_base_feature_publisher_v1.writer.lock'
stat -c '%n size=%s inode=%i' \
  /home/wali/ai_bot_local_data/v2_native_trainer/durable_feature_snapshot_ledger.sqlite3{,-wal,-shm}

systemctl --user show ai-bot-v2-native-cuda-trainer-persistent.service \
  -p ActiveState -p SubState -p MainPID -p NRestarts
jq '{generated_at,state,inventory:.authenticated_sample_inventory,
     training_loop_active,trainer_admission_authorized,checkpoint_authorized,
     model_authorized,prediction_authorized,paper_trading_authorized,
     live_execution_authorized,runtime_wired}' \
  v2/runtime/native_cuda_trainer_waiting_for_authenticated_samples_status.json
```

Current acceptance burn-in sampled the services and sidecars 39 times, observed
13 distinct successful observer artifacts, and crossed two publisher cycles.
TAOUSDT sequences 39/40 and TREEUSDT sequences 41/42 were appended; each cycle
published one strict pair with zero failures and zero masked observations. WAL
inode `59941802` and SHM inode `59942438` remained stable while the WAL grew to
1,030,032 bytes. The final scan reported 42 verified records, 27 append
receipts, 15 strict candidates and zero exclusions. Publisher PID `3727644`
and observer PID `3670540` were both active with zero restarts at the recorded
observation.

Do not query a guessed `profiled-training-waiting-observer` unit; no such unit
is installed. A later publisher cycle may safely report a stale or unavailable
closed window; that is not the same as a dead service. Never force candidate
supply around finality, provenance, availability or CAS verification.

The publisher being online does not mean the optimizer is online. The strict
loader currently reports `runtime_wired=false`; prediction, paper and live
authority are false. See
`claude_worklog/codex/CODEX_AUTHENTICATED_TRAINER_PUBLISHER_RECOVERY_2026_07_22.md`
for the exact loader command, acceptance counts and remaining adapter gate.

### Trainer mark-price ownership check

The trainer-facing key `v2:market:mark_price:{symbol}` has exactly one intended
writer: `ai-bot-v2-binance-mark-price-wss-seeder.service`. The public metadata
service may read that key, but its output belongs at
`v2:market:premium_index:{symbol}`. Never restore the old metadata write to the
canonical key and never implement a read-then-skip compromise; two writers can
still race between the read and write.

Both services must resolve to immutable source release
`2f05742c48d09b6018381a99535703321c4be06e`:

```bash
systemctl --user show \
  ai-bot-v2-binance-mark-price-wss-seeder.service \
  ai-bot-v2-binance-public-metadata-ingestor.service \
  -p Id -p ActiveState -p SubState -p MainPID -p NRestarts \
  -p WorkingDirectory -p Environment

redis-cli GET v2:market:mark_price:TRUMPUSDT | jq \
  '{schema_version,symbol,event_time,received_at,available_at,generated_at,
    expected_update_interval_seconds,source,transport,places_real_order,
    leverage_mutation,margin_mode_mutation}'

redis-cli GET v2:market:premium_index:TRUMPUSDT | jq \
  '{symbol,event_time,available_at,source,transport,source_key}'
```

Required canonical mark invariants:

- schema `binance_usdm_mark_price_wss_v1`;
- source `binance_usdm_wss_mark_price_all_symbols` and transport
  `websocket_primary`;
- finite, canonical JSON with both snake-case and exchange-style mark/index
  aliases;
- `event_time <= received_at == available_at == generated_at`;
- `expected_update_interval_seconds=1.0`; and
- every order, leverage, margin-mode, transfer and credential-exposure flag is
  false.

The post-deployment acceptance probe ran for 70.047 seconds at 50 ms cadence.
It observed 1,373/1,373 valid canonical TRUMPUSDT mark documents, zero missing,
invalid or unparsable marks, and no wrong-owner payload. The independent
premium-index key was present for 1,363 samples after initial materialization
and carried two distinct event times. At cutover, metadata PID `3764071` and
WebSocket PID `3764065` were active with zero restarts. The WebSocket unit
intentionally exits after 600 messages so systemd can re-resolve the adaptive
symbol universe; later bounded restart-count growth is expected. Judge it by
successful exit/reconnect, current payload freshness and schema, not by a
permanent `NRestarts=0` requirement.

The publisher cycle ending at `2026-07-22T12:24:01.572529Z` published its one
selected strict pair with zero failures. The next cycle correctly isolated
ONEUSDT because canonical OHLCV REST provenance was unavailable. That later
retryable hold is not a mark transport regression: the failure reasons must
not contain `CAUSAL_COST_MARK_PRICE_SOURCE_JSON_INVALID`, and no orphan ledger
row may be appended.
