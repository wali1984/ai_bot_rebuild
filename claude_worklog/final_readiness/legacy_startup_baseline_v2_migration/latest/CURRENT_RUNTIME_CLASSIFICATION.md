# CURRENT_RUNTIME_CLASSIFICATION — Phase A

As of 2026-05-13 (inspection run this turn).

## Operator declaration vs observed reality

**Operator said:** legacy started **without** the trader; treat as `LEGACY_RUNTIME_REFERENCE_ACTIVE_NO_TRADER`.

**Observed:** `python3 -u trading/trader.py` is **alive** (pid 14912, ~7559s = ~2 hours uptime). The trader was already running at the start of this session and is still running.

**Classification applied (per task contingency):** `LEGACY_TRADER_PROCESS_OBSERVED_READONLY` — I am NOT killing it, NOT restarting it. V2 migration can continue, but **live risk requires the operator's decision**. The operator should be aware that the legacy trader is presently capable of placing live orders against the running ingestors/feature pipeline/trainer/orchestrator chain.

## Active legacy processes (observed read-only)

| pid | etimes | command |
|---|---|---|
| 14711 | 7574 | `npm run dev` (V2 frontend vite — owned by V2, not legacy) |
| 14912 | 7559 | `python3 -u trading/trader.py` — **TRADER ACTIVE, contrary to operator declaration** |
| 46218 | 989 | `python3 -u ingest/live_binance.py` |
| 46365 | 978 | `python3 -u ingest/live_binance_liquidations.py` |
| 46559 | 963 | `python3 -u ingest/live_coinank.py` |
| 47157 | 934 | `python3 -u ingest/live_kucoin.py` |
| 47348 | 920 | `python3 -u ingest/live_technical_analysis.py` |
| 48066 | 893 | `python3 -u feature_pipeline.py` |
| 48623 | 860 | `python3 -u -m rl.hybrid_trainer --mode hybrid --epochs 1000 --batch-size 64` |

The trainer is running in `--mode hybrid --epochs 1000 --batch-size 64` (note: different flags than the startup script's `--training-mode live --enhanced-features` — operator-customized).

## Not observed (expected per startup script PHASE 0.5 + 4C — operator may have skipped or they died)

- `vpn_monitor.py`
- `system_telegram_monitor.py`
- `monitor_system_memory.py`
- `scripts/memory_monitor.py`
- `scripts/monitor_trainer_predictions.py`
- `ingest/live_coinank_global_aggregator.py`
- `ingest/liquidation_bridge.py`
- `ingest/liquidation_levels_engine.py`
- `ingest/realtime_price_provider.py`
- `ingest/live_coinapi_wsds.py`
- `ingest/live_coinapi_v1.py`
- `ohlcv_resampler_hotfix.py`
- `rl.orchestrator_worker`
- `trading/trader-asjad.py`
- `monitor_portfolio_primary.py`
- `monitor_portfolio_asjad.py`

These are **mapped in the baseline matrix** (Phase B) and **will be copied to v2/legacy_preserved/** (Phase C) regardless of whether they are currently running, because they are required source-of-truth for V2 ports.

## V2 automation state

| process | status |
|---|---|
| `v2_worker_porting_orchestrator` daemon | **NOT RUNNING** (operator hasn't run start script from real terminal) |
| `agent_supervisor.py` | NOT RUNNING |
| `parallel_capacity_scheduler.py` | NOT RUNNING |
| `codex_non_live_watchdog.py` | NOT RUNNING |
| `v2.backend.app.cli.paper_online_runtime` | NOT RUNNING |
| `v2.backend.app.cli.paper_shadow_observation` | NOT RUNNING |

## Safety gates (verified absent)

- `claude_worklog/approvals/APPROVED_FINAL_LIVE_TINY_CANARY_ONLY.md` — **absent**
- `claude_worklog/approvals/APPROVED_REDIS_LIQUIDATIONS_EVENTS_XTRIM_MINID_1777222885206_0_ONLY.md` — **absent**

## Classification tokens applied

```text
LEGACY_RUNTIME_REFERENCE_ACTIVE_WITH_TRADER_OBSERVED
LEGACY_TRADER_PROCESS_OBSERVED_READONLY
V2_MIGRATION_ACTIVE
LIVE_GATE_BLOCKED_HUMAN_ONLY (V2 side)
FINAL_APPROVAL_TOKEN_ABSENT
REDIS_TRIM_APPROVAL_ABSENT
OPERATOR_DECLARATION_MISMATCH_TRADER_ACTIVE
```

## What this means for V2 migration

- **The migration can proceed.** Legacy is a read-only reference for porting, regardless of whether the trader is running.
- **V2 will not write old Redis.** V2 ports must produce V2-namespaced data plane outputs only.
- **V2 will not place orders.** V2 paper/shadow only. Live remains `blocked_human_only`.
- **Operator must decide separately** whether to stop the legacy trader. This task does not stop it.

## Operator action items

1. Confirm whether the legacy trader (pid 14912) should remain running. If not, the operator should stop it manually (`kill 14912` or via the legacy stop script).
2. Confirm whether the trainer flags `--mode hybrid --epochs 1000 --batch-size 64` are the intended runtime, or if it should be `--mode hybrid --training-mode live --enhanced-features` per the startup script.
3. Run `bash claude_worklog/tools/start_v2_worker_porting_control_plane.sh` from a normal terminal to bring up the V2 control-plane daemons.
