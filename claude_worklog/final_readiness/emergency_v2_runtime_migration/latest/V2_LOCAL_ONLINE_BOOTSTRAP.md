# V2_LOCAL_ONLINE_BOOTSTRAP

How to bring V2 online **locally** as a paper/shadow runtime. **Never live.** No public exposure.

## Pre-conditions

- Operator declares old legacy system is shut down ([EMERGENCY_MIGRATION_CONTEXT.md](EMERGENCY_MIGRATION_CONTEXT.md)).
- No `APPROVED_FINAL_LIVE_TINY_CANARY_ONLY.md` in `claude_worklog/approvals/`.
- No Redis trim approval token.
- At least the existing standalone `paper_online_runtime` is available; the six P0 library-only workers will be lifted into CLIs by Lane 1.
- `v2/scripts/deployment/preflight_check.py` (built by P2 task `claude_port_v2_p2_deployment_helpers`) returns OK.

## Allowed local targets

| target | purpose | binding |
|---|---|---|
| 127.0.0.1 | dev frontend, dev backend API | loopback only |
| localhost | same | loopback only |
| V2-namespaced filesystem under `v2/runtime/` | append-only ledgers, status payloads | local disk only |
| V2 frontend public payload at `v2/frontend/public/operator_runtime/` | GUI source-of-truth | served by vite dev server |

**Forbidden:** public hosting, internet-routable bind, real exchange credentials, anything not loopback.

## Bootstrap sequence (run only after the gating tasks above)

### Step 0 — preflight

```text
v2/scripts/deployment/preflight_check.py
```

Must print `PREFLIGHT_OK` and exit 0. If it prints `BLOCKED_APPROVAL_TOKEN_PRESENT`, stop immediately and remove the token via operator-only workflow before proceeding.

### Step 1 — restart the paper online runtime

```text
python3 -m v2.backend.app.cli.paper_online_runtime --loop --interval 30 --symbol BTCUSDT
```

Verify within 60s that `v2/frontend/public/operator_runtime/paper_online/latest/paper_runtime_status.json` has a fresh `last_run_ts`.

### Step 2 — restart the paper shadow observer

```text
python3 -m v2.backend.app.cli.paper_shadow_observation --write
```

Verify within 60s that `v2/frontend/public/operator_runtime/paper_shadow_observation/latest/paper_shadow_observation_status.json` updates.

### Step 3 — start P0 workers as they ship

Each P0 worker, once implemented, has its own runnable invocation in its task descriptor. Suggested startup order:

1. `v2_feature_snapshot_builder`
2. `v2_risk_gateway_runtime_worker`
3. `v2_paper_execution_worker`
4. `v2_execution_ledger_worker`
5. `v2_signal_lineage_worker`
6. `v2_account_position_monitor` (read-only, with `MISSING_CREDENTIALS` if no read-only keys)

For each, verify the corresponding public payload under `v2/frontend/public/operator_runtime/<worker>/latest/` updates within 60s.

### Step 4 — restart automation supervisors

The four supervisor bash-loops (`agent_supervisor`, `parallel_capacity_scheduler`, `codex_non_live_watchdog`, `always_on_objective_runner`) currently down per Phase A. Restart procedure depends on how the operator originally launched them; re-run the bash-loop wrappers under the same parent process or under nohup.

### Step 5 — Admin AI + monitor center (P1)

Once `claude_port_v2_script_monitor` and an Admin AI backend task land, expose them in the GUI Mission Control / Monitor Center / Admin AI surface.

## Safety checklist (must be true before declaring V2 online locally)

- [ ] preflight returned OK
- [ ] paper online runtime payload fresh < 60s
- [ ] paper shadow observation payload fresh < 60s
- [ ] every started worker has a fresh public payload
- [ ] live gate `blocked_human_only` in every worker payload
- [ ] no approval token present
- [ ] no Redis trim approval present
- [ ] no legacy paths modified
- [ ] no exchange order/cancel/leverage/margin-mode call attempted
- [ ] no secrets in any payload
