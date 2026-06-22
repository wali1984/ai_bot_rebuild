# Codex Review: V2 Post-Hoc Replay Outcome Miner Timer

GO/NO-GO: `V2_POST_HOC_REPLAY_OUTCOME_MINER_TIMER_CODEX_PASS`

READY was reviewed as an installed, active timer only. This review does not approve edge, canary, live trading, legacy shutdown, Redis trimming, or symbol adoption.

## Findings

No blocking findings.

The timer is active, enabled, firing on the intended 60-second cadence, and the one-shot service exits successfully. The miner payloads are refreshing, replay bundles are not duplicate-corrupt, cost-model metadata remains clean, and the verdict remains conservative.

## Reviewed Scope

- user systemd timer: `ai-bot-v2-post-hoc-replay-outcome-miner.timer`
- user systemd service: `ai-bot-v2-post-hoc-replay-outcome-miner.service`
- `claude_worklog/systemd/user/ai-bot-v2-post-hoc-replay-outcome-miner.service`
- `claude_worklog/systemd/user/ai-bot-v2-post-hoc-replay-outcome-miner.timer`
- `v2/backend/app/cli/v2_post_hoc_replay_outcome_miner.py`
- `v2/backend/app/services/edge_proof/replay_miner.py`
- post-hoc miner latest worklog and public payloads
- refreshed native edge-proof metric mirrors
- three replay-bundle JSONL stores

## Timer And Service

Systemd state:

```text
timer_unit=ai-bot-v2-post-hoc-replay-outcome-miner.timer
timer_enabled=enabled
timer_active=active
service_unit=ai-bot-v2-post-hoc-replay-outcome-miner.service
service_active_state_after_oneshot=inactive
service_result=success
service_exec_main_status=0
```

Cadence and command:

```text
OnBootSec=30s
OnUnitActiveSec=60s
AccuracySec=10s
Persistent=true
ExecStart=/usr/bin/env bash -lc 'exec "/home/wali/Desktop/AI BOT REBUILD/.venv/bin/python3" -m v2.backend.app.cli.v2_post_hoc_replay_outcome_miner --symbols BTCUSDT,ETHUSDT,SOLUSDT --json'
```

The service runs `v2.backend.app.cli.v2_post_hoc_replay_outcome_miner` and sets `LIVE_GATE=blocked_human_only`.

Timer refresh proof:

```text
before payload: generated_at=2026-05-23T06:38:16Z bundles_total=41
after payload:  generated_at=2026-05-23T06:39:18Z bundles_total=41
later payload:  generated_at=2026-05-23T06:40:19Z bundles_total=44
```

## Payload Freshness

Current observed post-hoc miner payload:

```text
generated_at=2026-05-23T06:40:19Z
status_age_seconds=10.0
bundles_total=44
label_counts={'correct_no_trade': 1, 'insufficient_evidence': 43}
windows_filled={'1m': 2, '5m': 1, '15m': 0, '1h': 0}
verdict=EDGE_NOT_CLAIMED_OPERATOR_THRESHOLDS_REQUIRED
```

Payloads checked:

- `post_hoc_replay_outcome_status.json`
- `replay_outcome_bundles.jsonl`
- `edge_metrics_summary.json`
- post-hoc miner public mirrors
- native edge-proof worklog/public `edge_metrics_summary.json`

Mirror checks:

```text
latest_public_cmp=0
latest_state_cmp=0
metrics_public_cmp=0
native_metrics_public_cmp=0
```

## Replay Bundle Integrity

All three replay-bundle stores were checked:

```text
claude_worklog/final_readiness/v2_post_hoc_replay_outcome_miner/latest/replay_outcome_bundles.jsonl
rows=44
bad_cost_model_marker_count=0
missing_visible_override_field_count=0
duplicate_prediction_id_count=0
duplicate_intent_id_count=0
filled_window_count=3
fabricated_insufficient_window_count=0
safety_violations=0

v2/frontend/public/v2_post_hoc_replay_outcome_miner/latest/replay_outcome_bundles.jsonl
rows=44
bad_cost_model_marker_count=0
missing_visible_override_field_count=0
duplicate_prediction_id_count=0
duplicate_intent_id_count=0
filled_window_count=3
fabricated_insufficient_window_count=0
safety_violations=0

claude_worklog/final_readiness/v2_post_hoc_replay_outcome_miner/state/replay_bundles.jsonl
rows=44
bad_cost_model_marker_count=0
missing_visible_override_field_count=0
duplicate_prediction_id_count=0
duplicate_intent_id_count=0
filled_window_count=3
fabricated_insufficient_window_count=0
safety_violations=0
```

Filled windows use real miner timeline evidence:

```text
source=V2_MINER_PRICE_TIMELINE
filled windows observed: 1m=2, 5m=1, 15m=0, 1h=0
```

Insufficient windows remain explicit and unfilled; no insufficient window contains fabricated `after_cost_return_bps` or nonzero samples.

## Cost Model

Every replay bundle row has:

- `market_snapshot.cost_model_source` containing `OPERATOR_DECISION_REQUIRED`
- `market_snapshot.operator_decision_required=true`
- `market_snapshot.operator_override_required=true`
- `market_snapshot.default_fee_bps_visible=5.0`
- `market_snapshot.default_slippage_estimate_bps_visible=2.0`

## Conservative Verdict

The current evaluator verdict remains:

```text
EDGE_NOT_CLAIMED_OPERATOR_THRESHOLDS_REQUIRED
```

Thresholds remain operator-required:

```text
min_sample_count=OPERATOR_DECISION_REQUIRED
min_after_cost_expectancy_bps=OPERATOR_DECISION_REQUIRED
min_after_cost_lower_ci_bps=OPERATOR_DECISION_REQUIRED
max_drawdown_bps_rolling=OPERATOR_DECISION_REQUIRED
min_downside_pre_cascade_recall=OPERATOR_DECISION_REQUIRED
max_false_positive_rate=OPERATOR_DECISION_REQUIRED
max_false_negative_rate=OPERATOR_DECISION_REQUIRED
```

## Safety Verification

- No live approval was found.
- No canary approval was found.
- No legacy shutdown approval was found.
- No Redis trim approval was found.
- No old Redis write path was found in reviewed timer/miner code.
- No exchange mutation path was found in reviewed timer/miner code.
- No raw secrets were found; scan hits were comments/status text only.
- `live_gate=blocked_human_only`.
- `live_symbols=[]`.

## Test Evidence

```text
PYTHONPATH=$PWD .venv/bin/pytest \
  v2/backend/tests/integration/cli/test_v2_post_hoc_replay_outcome_miner.py \
  v2/backend/tests/integration/cli/test_v2_native_edge_proof_evaluator.py -q
```

Result:

```text
43 passed in 0.29s
```

Compile check:

```text
python -m py_compile \
  v2/backend/app/services/edge_proof/evaluator.py \
  v2/backend/app/services/edge_proof/replay_schema.py \
  v2/backend/app/services/edge_proof/replay_miner.py \
  v2/backend/app/cli/v2_post_hoc_replay_outcome_miner.py
```

Result: pass.

## Safety Scoreboard

- did_not_modify_legacy_bot
- did_not_stop_v2_runtime
- did_not_write_old_redis
- did_not_call_exchange
- did_not_enable_live
- did_not_create_approval_marker
- did_not_fabricate_future_outcome_windows
- live_gate = blocked_human_only
- live_symbols = []
- approves_live = false
- approves_canary = false
- approves_legacy_shutdown = false
- approves_redis_trim = false
