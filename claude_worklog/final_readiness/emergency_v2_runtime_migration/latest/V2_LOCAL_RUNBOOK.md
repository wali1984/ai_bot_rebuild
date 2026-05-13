# V2_LOCAL_RUNBOOK

Day-to-day operator commands for running V2 locally. Loopback-only. Paper-only. Never live.

## 0. Pre-flight (every session)

```text
cd "$HOME/Desktop/AI BOT REBUILD"
v2/scripts/deployment/preflight_check.py
```

Expected: `PREFLIGHT_OK`. If it prints `BLOCKED_APPROVAL_TOKEN_PRESENT`, stop and remove the token via operator workflow.

## 1. Start the V2 frontend dev server (if not running)

```text
cd v2
npm run dev
```

Already running? Check `ps -ef | grep vite`.

## 2. Start the paper online runtime

```text
cd "$HOME/Desktop/AI BOT REBUILD"
python3 -m v2.backend.app.cli.paper_online_runtime --loop --interval 30 --symbol BTCUSDT
```

Verify within 60s:

```text
test -f v2/frontend/public/operator_runtime/paper_online/latest/paper_runtime_status.json && \
  jq '.last_run_ts' v2/frontend/public/operator_runtime/paper_online/latest/paper_runtime_status.json
```

## 3. Start the paper shadow observer

```text
python3 -m v2.backend.app.cli.paper_shadow_observation --write
```

(Wrap in `while true; do ...; sleep 300; done` if desired.)

## 4. Start P0 workers (after Lane 1 ships them)

```text
python3 -m v2.backend.app.cli.v2_feature_snapshot_builder --loop --interval 30
python3 -m v2.backend.app.cli.v2_risk_gateway_runtime_worker --loop --interval 30
python3 -m v2.backend.app.cli.v2_paper_execution_worker --loop --interval 30
python3 -m v2.backend.app.cli.v2_execution_ledger_worker --loop --interval 30
python3 -m v2.backend.app.cli.v2_signal_lineage_worker --loop --interval 30
python3 -m v2.backend.app.cli.v2_account_position_monitor --loop --interval 60 --readonly-only
```

## 5. Restart automation supervisors

These four bash-loops are currently DOWN. Restart with the same wrappers that originally launched them. Verify they tail their respective log files under `claude_worklog/agent_supervisor/logs/control_plane/`.

## 6. Health check

```text
find v2/frontend/public/operator_runtime -name "*_status.json" -mmin -2 | head
```

Lists every worker payload updated in the last 2 minutes. Any expected worker missing from the list is offline.

## 7. Stop everything safely

```text
v2/scripts/deployment/stop_all_workers.sh
```

Stops only V2-owned PIDs. Never touches legacy. Idempotent.

## Forbidden in this runbook

- `python3 -m v2.backend.app.cli.<anything> --real` — no real-mode flag exists; if you see one, do NOT use it.
- Any `redis-cli` write against the old Redis namespace.
- Any `kill` against legacy PIDs.
- Any push to a non-`master` branch labelled "ready-for-live".
- Any creation of `claude_worklog/approvals/APPROVED_FINAL_LIVE_TINY_CANARY_ONLY.md`.
- Editing files under `/home/wali/Desktop/AI BOT`.
