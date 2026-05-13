# V2_LOCAL_RUNTIME_AFTER_BASELINE_COPY — Phase K

## Classification

```text
V2_LOCAL_ONLINE_BLOCKED_BASELINE_COPY_COMPLETE_BUT_WORKERS_NOT_PORTED_YET
```

Translated: the baseline copy is **complete enough** (33 of 39 files copied, 6 explicit blockers, zero secret flags) that the next-step worker ports have everything they need on disk. But **no V2 baseline-anchored worker has shipped yet**, so the V2 local runtime is not yet meaningfully "online".

## What is alive locally

| component | status |
|---|---|
| V2 frontend (`npm run dev` / vite) | running pid 14711 |
| legacy ingestors / TA / feature pipeline / trainer / trader | running (operator-owned; not a V2 deliverable) |
| `paper_online_runtime` | NOT running |
| `paper_shadow_observation` | NOT running |
| four supervisor daemons (`agent_supervisor`, `parallel_capacity_scheduler`, `codex_non_live_watchdog`, `v2_worker_porting_orchestrator`) | NOT running |

## What blocks "V2_LOCAL_ONLINE_DEGRADED_BASELINE_COPY_COMPLETE"

- The four supervisor daemons are not running, so dispatch of `claude_port_v2_market_ingestor_from_legacy_baseline` cannot happen autonomously yet. The operator must run [start_v2_worker_porting_control_plane.sh](../../../tools/start_v2_worker_porting_control_plane.sh) from a normal terminal.
- Paper online runtime is not running. The operator can restart it via [V2_LOCAL_RUNBOOK.md](../../v2_worker_porting_orchestrator/latest/V2_LOCAL_RUNBOOK.md) → step 2.

## What is intentionally NOT done in V2 this turn

- No V2 live trader started. ✓
- No V2 live keys activated. ✓
- No V2 write to legacy Redis namespace. ✓
- No V2 process placed an exchange order. ✓
- No V2 process changed leverage or margin mode. ✓

## What to look at after the operator runs the start script

```text
.venv/bin/python3 claude_worklog/tools/v2_worker_porting_orchestrator.py --status | head -30
bash claude_worklog/tools/status_v2_worker_porting_control_plane.sh
ls v2/frontend/public/operator_runtime/v2_market_ingestor/latest/  # appears once worker ships
ls claude_worklog/final_readiness/emergency_v2_runtime_migration/latest/workers/  # baseline analysis files appear here first
```
