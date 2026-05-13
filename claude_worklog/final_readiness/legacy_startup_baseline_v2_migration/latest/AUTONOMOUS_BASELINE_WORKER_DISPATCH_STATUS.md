# AUTONOMOUS_BASELINE_WORKER_DISPATCH_STATUS — Phase H

## Selected primary worker (computed from orchestrator)

```text
next_worker      = v2_market_ingestor_from_legacy_baseline
next_action.kind = dispatch_legacy_baseline_analysis
task_descriptor  = claude_worklog/agent_supervisor/tasks/claude_port_v2_market_ingestor_from_legacy_baseline.json
codex_pair       = claude_worklog/agent_supervisor/tasks/codex_review_v2_market_ingestor_from_legacy_baseline.json
```

The orchestrator surfaced this selection on its last `--once` tick (verified this turn). The selector pointer file at `claude_worklog/final_readiness/v2_worker_porting_orchestrator/latest/next_selected_task.json` was refreshed.

## What the supervisor will do when it picks this up

1. Read the task descriptor's `prompt`. The **LEGACY-FIRST MANDATE — BASELINE-ANCHORED** preamble forces the sub-agent to read `v2/legacy_preserved/startup_baseline/ingest/{live_binance,live_kucoin,realtime_price_provider,live_coinapi_wsds,live_coinapi_v1}.py` first.
2. Run the closure scanner to confirm transitive dependencies; copy uncovered helpers OR document them as `MISSING_IN_LEGACY_BASELINE`.
3. Cite SHA256 from `copied_baseline_manifest.json` inside `LEGACY_BASELINE_ANALYSIS.md` and `legacy_behavior_mapping.json` **before** writing any V2 implementation code.
4. Build `v2/backend/app/cli/v2_market_ingestor.py`, integration tests, and the public payload.
5. Trigger `codex_review_v2_market_ingestor_from_legacy_baseline`.

## Why this — not the website task — is the next dispatch

The website parallel task (`parallel_trading_platform_consumer_ui_from_real_v2_payloads`) is **support-only**. Per the non-drift governor lock (still on disk at `claude_worklog/autonomous_governor/latest/NON_DRIFT_GOVERNOR_LOCK.json`), only the selected primary task runs. The orchestrator's `next_action.kind` is `dispatch_legacy_baseline_analysis` for the market ingestor — not a UI dispatch.

## Backfill task for the already-shipped feature snapshot worker

Still queued from prior turn at:

- `claude_worklog/agent_supervisor/tasks/claude_backfill_v2_feature_snapshot_builder_legacy_analysis.json`
- `claude_worklog/agent_supervisor/tasks/codex_review_v2_feature_snapshot_builder_legacy_backfill.json`

This backfill can run **in parallel** with the market ingestor port — it touches no V2 code, only retroactive legacy mapping for the already-shipped CLI.

## What the operator should do

Run the V2 control-plane start script from a normal terminal:

```text
bash claude_worklog/tools/start_v2_worker_porting_control_plane.sh
bash claude_worklog/tools/status_v2_worker_porting_control_plane.sh
```

Once the four tmux sessions are alive (`ai_bot_worker_porting_orchestrator`, `ai_bot_agent_supervisor`, `ai_bot_parallel_scheduler`, `ai_bot_codex_watchdog`), the dispatch happens automatically. No manual worker-by-worker prompting needed.
