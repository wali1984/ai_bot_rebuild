# V2 Post-Hoc Replay Outcome Miner Timer — Install Report

GO/NO-GO: V2_POST_HOC_REPLAY_OUTCOME_MINER_TIMER_READY

The V2 post-hoc replay outcome miner timer is installed and enabled
as a user-mode systemd timer. This is paper/shadow evidence collection
only. It does not approve edge, canary, live trading, legacy shutdown,
Redis trimming, or symbol adoption.

## Installed Units

| Unit | Path |
|---|---|
| service | `claude_worklog/systemd/user/ai-bot-v2-post-hoc-replay-outcome-miner.service` |
| timer | `claude_worklog/systemd/user/ai-bot-v2-post-hoc-replay-outcome-miner.timer` |
| installed service | `~/.config/systemd/user/ai-bot-v2-post-hoc-replay-outcome-miner.service` |
| installed timer | `~/.config/systemd/user/ai-bot-v2-post-hoc-replay-outcome-miner.timer` |
| enabled timer symlink | `~/.config/systemd/user/timers.target.wants/ai-bot-v2-post-hoc-replay-outcome-miner.timer` |

## Timer Cadence

- `OnBootSec=30s`
- `OnUnitActiveSec=60s`
- `AccuracySec=10s`
- `Persistent=true`
- Service type: `oneshot`

## Command

```text
/home/wali/Desktop/AI BOT REBUILD/.venv/bin/python3 \
  -m v2.backend.app.cli.v2_post_hoc_replay_outcome_miner \
  --symbols BTCUSDT,ETHUSDT,SOLUSDT --json
```

The unit sets:

- `PYTHONPATH=/home/wali/Desktop/AI BOT REBUILD`
- `LIVE_GATE=blocked_human_only`

## Install Evidence

Commands run:

```text
install -m 0644 claude_worklog/systemd/user/ai-bot-v2-post-hoc-replay-outcome-miner.service \
  ~/.config/systemd/user/ai-bot-v2-post-hoc-replay-outcome-miner.service
install -m 0644 claude_worklog/systemd/user/ai-bot-v2-post-hoc-replay-outcome-miner.timer \
  ~/.config/systemd/user/ai-bot-v2-post-hoc-replay-outcome-miner.timer
systemctl --user daemon-reload
systemctl --user enable --now ai-bot-v2-post-hoc-replay-outcome-miner.timer
```

Systemd state observed after install:

```text
timer_active_state=active
timer_unit_file_state=enabled
service_active_state_after_oneshot=inactive
service_last_result=success
service_last_exec_status=0
last_observed_trigger=2026-05-23 02:22:05 EDT
next_observed_trigger=2026-05-23 02:23:05 EDT
```

The timer fired at least twice after install. The service exited
successfully on the observed tick at 02:22:05 EDT.

## Miner Payload After Timer Ticks

Initial install observation from
`claude_worklog/final_readiness/v2_post_hoc_replay_outcome_miner/latest/post_hoc_replay_outcome_status.json`:

```text
generated_at=2026-05-23T06:22:05Z
bundles_total=14
label_counts={'insufficient_evidence': 14}
windows_filled={'1m': 0, '5m': 0, '15m': 0, '1h': 0}
verdict=EDGE_NOT_CLAIMED_OPERATOR_THRESHOLDS_REQUIRED
live_gate=blocked_human_only
live_symbols=[]
approves_live=false
approves_canary=false
approves_legacy_shutdown=false
approves_redis_trim=false
no_fabricated_outcomes=true
```

Later observation while the timer remained active:

```text
generated_at=2026-05-23T06:24:06Z
bundles_total=18
label_counts={'insufficient_evidence': 18}
windows_filled={'1m': 1, '5m': 0, '15m': 0, '1h': 0}
verdict=EDGE_NOT_CLAIMED_OPERATOR_THRESHOLDS_REQUIRED
live_gate=blocked_human_only
live_symbols=[]
approves_live=false
approves_canary=false
approves_legacy_shutdown=false
approves_redis_trim=false
no_fabricated_outcomes=true
```

The three replay-bundle JSONL stores were rechecked after timer
execution:

```text
rows=18
bad_cost_model_marker_count=0
missing_visible_override_field_count=0
filled_or_sampled_windows=1
safety_violations=0
```

## What This Install Does Not Do

- Does not modify `/home/wali/Desktop/AI BOT`.
- Does not stop legacy.
- Does not stop V2 runtime.
- Does not write old Redis.
- Does not call the exchange.
- Does not enable live.
- Does not approve canary.
- Does not approve legacy shutdown.
- Does not create an approval marker.
- Does not fabricate future outcome windows.
- Does not adopt Symbol Universe candidates.

## Safety Scoreboard

- live_gate = blocked_human_only
- live_symbols = []
- approves_live = false
- approves_canary = false
- approves_legacy_shutdown = false
- approves_redis_trim = false
- did_not_modify_legacy_bot = true
- did_not_stop_v2_runtime = true
- did_not_write_old_redis = true
- did_not_call_exchange = true
- did_not_enable_live = true
- did_not_create_approval_marker = true
- did_not_fabricate_future_outcomes = true
