# EMERGENCY_V2_RUNTIME_MIGRATION_AND_ONLINE_BOOTSTRAP — Phase A Context

Operator-declared state, as of 2026-05-13.

## Operator declaration

- Old legacy system: **shut down by operator**. Treated as `FROZEN_REFERENCE` only.
- Legacy role: **frozen_reference_only**. Any "current legacy runtime evidence" must be classified `MISSING_RUNTIME_EVIDENCE` unless re-confirmed by a fresh read against a still-running legacy process.
- V2 current state: `partial_control_plane_until_worker_audit_proves_otherwise`.
- Live gate: `blocked_human_only`.
- Final approval token: **absent**.
- Old Redis writes: **forbidden**.
- Exchange actions: **forbidden**.
- Migration mode: `emergency_parallel_worker_porting`.

## Primary objective

Bring V2 online locally as an **independent paper/shadow runtime**. Independent means: V2 workers run without requiring the legacy bot's runtime processes. Bridge-only or wrapper-only paths are not independence.

## Secondary objective

Expose every V2 worker (existing, queued, missing, blocked) in the GUI/Admin AI surface, with source/freshness labels and explicit MISSING_EVIDENCE wherever runtime evidence cannot be produced.

## Repo snapshot

- Branch: `master`
- HEAD = origin/master: `36e234a337a01e12acb079c28a28ae156128b2e1`
- Last commit: `Add parallel trading platform consumer UI support task`
- Dirty file count: 230 (daemon-owned churn — runtime status JSONs, automation utilization logs, planner artifacts). Untracked roots: `.claude/`, `claude_worklog/`, `v2/`. None of this churn is owned by this migration task.

## Active runtime processes (only what is alive right now)

| Process | PID | Etimes | Role |
|---|---|---|---|
| `python3 -u trading/trader.py` | 14912 | ~794s | Legacy trader process — restarted recently. Operator declared old system shut down, so this is treated as a stray / awaiting termination by operator, NOT current evidence. |
| `npm run dev` (vite) | 14711 | — | V2 frontend dev server |
| `node v2/node_modules/.bin/vite` | 14739 | — | V2 frontend dev server |

What is **NOT running** (compared to earlier session snapshot, when the broader automation set was active):
- `python3 -m v2.backend.app.cli.paper_online_runtime` — **DOWN** (was earlier in session, no longer)
- `python3 -m v2.backend.app.cli.paper_shadow_observation` — **DOWN**
- `python3 -m rl.hybrid_trainer` — **DOWN** (legacy trainer, expected to be down per operator declaration)
- `python3 -m rl.orchestrator_worker` — **DOWN**
- `python3 ingest/live_coinank.py` — **DOWN** (legacy ingestor)
- `agent_supervisor.py --daemon` — **DOWN**
- `parallel_capacity_scheduler.py --daemon` — **DOWN**
- `codex_non_live_watchdog.py --daemon` — **DOWN**
- `always_on_objective_runner.py` loop — **DOWN**

This means **paper-shadow soak is not currently producing fresh evidence**, and the always-on automation supervisors are not running. This worsens the migration urgency.

## V2 worker inventory snapshot (from PHASE C gap matrix)

Library services migrated (deterministic, fully implemented) but **embedded in `paper_online_runtime.py` rather than independently runnable**:
- orchestrator decision (`v2/backend/app/composition/orchestrator_decision/`)
- risk gateway (`v2/backend/app/composition/risk_gateway/`)
- paper execution ledger (`v2/backend/app/composition/paper_execution_ledger/`)
- feature snapshot builder (`v2/backend/app/services/feature_snapshots/`)
- replay/backtest runner (`v2/backend/app/composition/replay_backtest_runner/`)

Standalone CLI that runs today: `v2/backend/app/cli/paper_online_runtime.py` (1050+ lines, full main + argparse, writes operator runtime payloads).

Standalone CLI also present: `v2/backend/app/cli/paper_shadow_observation` (read-only observer).

**Missing in V2 (0% real implementation):** market ingestor, CoinAnk/liquidation bridge, account/position monitor, PnL/accounting worker, script monitor, config/admin manager, Admin AI backend.

**Wrapper-only / bridge-only:** trainer bridge (monitors legacy Redis only; paper mode uses inline momentum wrapper), signal publisher (placeholder service, logic inline in paper_online_runtime), live execution adapter (correctly fail-closed by middleware, no live executor path).

## Hard constraints (carried into all sub-tasks)

- Do not modify `/home/wali/Desktop/AI BOT`.
- Do not write/delete legacy Redis keys; no `XADD`/`SET`/`HSET`/`DEL`/`XDEL`/`XTRIM`/`FLUSH`/`EXPIRE`/`CONFIG SET`/`BGSAVE` against old Redis.
- No Redis trim approval file.
- No final live approval token.
- No place/cancel/modify exchange orders.
- No leverage change. No margin-mode change.
- No live key activation. No live trading enablement.
- No secrets in commits.
- Work only inside `AI BOT REBUILD`.
- Live remains `blocked_human_only`.
- Legacy is frozen reference only — do not synthesize "current legacy runtime evidence".

## Safety classification

```
PRIMARY_OBJECTIVE = V2_INDEPENDENT_PAPER_SHADOW_RUNTIME
LIVE_GATE = blocked_human_only
FINAL_APPROVAL_TOKEN = absent
REDIS_TRIM_APPROVAL = absent
LEGACY_MUTATION = forbidden
EXCHANGE_ACTION = forbidden
MIGRATION_MODE = emergency_parallel_worker_porting
```

## Related artifacts

- Gap matrix: [V2_RUNTIME_WORKER_GAP_MATRIX.md](V2_RUNTIME_WORKER_GAP_MATRIX.md)
- Lane plan: [PARALLEL_LANE_PLAN.md](PARALLEL_LANE_PLAN.md)
- Missing list: [MISSING_V2_RUNTIME_WORKERS.md](MISSING_V2_RUNTIME_WORKERS.md)
- Bootstrap: [V2_LOCAL_ONLINE_BOOTSTRAP.md](V2_LOCAL_ONLINE_BOOTSTRAP.md)
- Final report: [EMERGENCY_V2_RUNTIME_MIGRATION_AND_ONLINE_BOOTSTRAP_REPORT.md](EMERGENCY_V2_RUNTIME_MIGRATION_AND_ONLINE_BOOTSTRAP_REPORT.md)
- GO/NO-GO: [GO_NO_GO.md](GO_NO_GO.md)
