# PARALLEL_LANE_PLAN — Emergency V2 Runtime Migration

Five concurrent lanes, with strict precedence rules.

## Lane 1: Claude Primary Runtime Migration

**Purpose:** implement real V2 workers in priority order (P0 first, P1 next, P2 stubs as fail-closed only).

**Owner:** Claude Code sub-agents picking up `claude_port_*` task descriptors from `claude_worklog/agent_supervisor/tasks/`.

**Inputs:** the gap matrix ([V2_RUNTIME_WORKER_GAP_MATRIX.md](V2_RUNTIME_WORKER_GAP_MATRIX.md)) drives ordering. P0 tasks address: risk gateway runtime CLI, paper execution worker CLI, execution ledger worker CLI, account/position read-only monitor, signal lineage worker, feature snapshot builder CLI.

**Outputs (per worker):**
- `v2/backend/app/cli/<worker>.py` standalone runnable CLI
- `v2/backend/tests/.../<worker>_test.py` tests
- `v2/frontend/public/operator_runtime/<worker>/latest/<worker>_status.json` public payload
- `claude_worklog/final_readiness/emergency_v2_runtime_migration/latest/workers/<worker>_report.md`
- `claude_worklog/final_readiness/emergency_v2_runtime_migration/latest/workers/<worker>_status.json`

**Precedence:** primary. Cannot be paused by any other lane.

## Lane 2: Codex Parallel Audit

**Purpose:** audit every worker port for safety, evidence, fail-closed behavior, and absence of forbidden actions.

**Owner:** Codex sub-agents picking up `codex_review_*` task descriptors.

**Trigger:** runs after each P0/P1/P2 worker task emits artifacts. May run concurrently while next worker is being implemented.

**Failure conditions:** any of — backlog counted as migration, no runnable command, no test, no public payload, writes old Redis, modifies legacy, mutates orders/leverage/margin, hides missing evidence, uses stale/static proof as current, claims runtime while only using frozen legacy, live gate not `blocked_human_only`.

**Aggregate output:**
- `claude_worklog/final_readiness/emergency_v2_runtime_migration/latest/CODEX_EMERGENCY_MIGRATION_REVIEW.md`
- `claude_worklog/final_readiness/emergency_v2_runtime_migration/latest/CODEX_GO_NO_GO.md` (one line: `EMERGENCY_V2_RUNTIME_MIGRATION_CODEX_PASS` or `EMERGENCY_V2_RUNTIME_MIGRATION_CODEX_FAIL`)

**Precedence:** parallel to Lane 1. Codex never blocks Lane 1 from starting the next task — but Codex `FAIL` blocks Lane 3 bootstrap from declaring a worker online.

## Lane 3: V2 Local Online Bootstrap

**Purpose:** start V2 services locally after workers exist. Never before.

**Owner:** operator manual run or supervised CLI launcher (see [V2_LOCAL_RUNBOOK.md](V2_LOCAL_RUNBOOK.md)).

**Targets:** 127.0.0.1 / localhost only. V2 paper/shadow only. V2 read-only account monitor only if safely configured. **Never live trading.**

**Gating:** must wait for at least P0 worker artifacts to exist and Codex review to be available (PASS or explicit BLOCKED with evidence). Cannot enable live.

**Precedence:** support to Lane 1. Lane 3 pauses if Lane 1 is implementing a worker it would start.

## Lane 4: GUI / Admin AI Visibility

**Purpose:** surface — in Mission Control, Monitor Center, Script Registry, Admin AI — which V2 workers exist, which run, which are missing, latest payload age, latest error, next blocker, Codex status, live gate state.

**Owner:** Claude Code sub-agents picking up GUI-visibility sub-tasks.

**Rule:** no major UI redesign. Add only the visibility needed for the migration. The previously staged `parallel_trading_platform_consumer_ui_from_real_v2_payloads` task is the dedicated UI lane and remains lower priority than worker migration.

**Hard rule:** UI lane **pauses** if it conflicts with a Lane 1 worker migration.

## Lane 5: Continuous Evidence

**Purpose:** keep paper/shadow/runtime payloads fresh so the migration can be evaluated on real data, and report gaps when payloads go stale.

**Owner:** the relaunched supervisor daemons (currently DOWN per Phase A snapshot) plus the new account/position monitor and signal lineage worker once implemented.

**Note:** this lane is **currently failing** — paper_online_runtime, paper_shadow_observation, and all four automation supervisors are not running. Restoring this lane is part of the bootstrap work in [V2_LOCAL_RUNBOOK.md](V2_LOCAL_RUNBOOK.md).

## Cross-lane rules

- Claude runtime migration (Lane 1) is **primary**. No other lane preempts it.
- Codex (Lane 2) runs in parallel after each worker emits artifacts. Codex never blocks Lane 1 from starting the next worker.
- Bootstrap (Lane 3) starts services only after workers exist. Cannot enable live.
- UI/Admin AI (Lane 4) is support-only. Pauses on conflict with Lane 1.
- Continuous evidence (Lane 5) must be restored as part of bootstrap.
- **No final live approval task may run.**
- **No legacy mutation task may run.**
- All lanes share the same hard constraints from [EMERGENCY_MIGRATION_CONTEXT.md](EMERGENCY_MIGRATION_CONTEXT.md).

## Sequencing (rough)

```
T+0       T+1 P0 worker          T+2 Codex review          T+3 bootstrap step
─────────────────────────────────────────────────────────────────────────────
gap matrix
parallel_lane_plan
P0 task descriptors
  ↓
                    risk_gateway_runtime_worker
                    paper_execution_worker         codex_review_risk_gateway_runtime
                    execution_ledger_worker        codex_review_paper_execution
                    account_position_monitor       codex_review_execution_ledger      bootstrap step 1:
                    signal_lineage_worker          codex_review_account_position      restart paper_online_runtime
                    feature_snapshot_builder       codex_review_signal_lineage
                                                   codex_review_feature_snapshot      bootstrap step 2:
                                                                                      stand up monitor/admin AI
P1 task descriptors                                                                   bootstrap step 3:
                                                                                      restart supervisor daemons
                    P1 workers (queued in parallel, run when P0 capacity frees)
```
