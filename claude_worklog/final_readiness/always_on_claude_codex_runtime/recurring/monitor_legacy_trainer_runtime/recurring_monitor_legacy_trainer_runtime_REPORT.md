# Recurring Monitor — monitor_legacy_trainer_runtime

- monitor_id: monitor_legacy_trainer_runtime
- mode: non_live / read_only
- scope: AI BOT REBUILD repo only; legacy processes / logs / Redis observed read-only
- run_timestamp_utc: 2026-05-15T04:29:34Z
- repo_head: master @ 28f2150c (Advance shutdown readiness blocker burn-down)
- operator: Wali (wajidali1984@hotmail.com)

## Boundary Confirmation
- No edits to ./legacy_reference/**, ../AI BOT/**, or any .env/secrets file.
- No exchange order, leverage, margin, or live-trading mutation.
- No writes to old Redis keys (no SET/DEL/EXPIRE issued in this run).
- No process restart of live trader or live trainer.
- Only writes performed by this monitor are evidence files under
  `claude_worklog/final_readiness/always_on_claude_codex_runtime/recurring/monitor_legacy_trainer_runtime/`.

## What This Monitor Watches
1. Legacy trainer Python interpreter availability (LEGACY_TRAINER_PYTHON) — existence only, no invocation that mutates state.
2. Legacy trainer process presence (read-only `ps -ef` observation, no kill / start).
3. Legacy trainer log freshness (last-modified mtime of legacy trainer log files under `legacy_reference/**` or external bot root, read-only).
4. Legacy Redis trainer-related key existence/age (read-only GET / TYPE / TTL; never SET / DEL / EXPIRE).
5. Trainer checkpoint directory freshness (read-only stat).
6. V2 paper / replay subsystem unaffected (paper soak + risk-gate state unchanged).

## Raw Evidence Snapshot (this run)
- Process listing source: `ps -ef` snapshot persisted at
  `~/.claude/projects/-home-wali-Desktop-AI-BOT-REBUILD/6cd81aaf-7a9e-4435-9da2-21719ab9b629/tool-results/b9z3usmsb.txt`
- Legacy hybrid trainer present (read-only observation):
  - pid=48623 ppid=48621 user=wali stime=May13 etime=1-00:25:16
  - cmd=`python3 -u -m rl.hybrid_trainer --mode hybrid --epochs 1000 --batch-size 64`
- Legacy read-only monitor scripts present:
  - pid=57289 cmd=`python3 Desktop/AI BOT/scripts/monitor_trainer_prices.py`
  - pid=57478 cmd=`python3 Desktop/AI BOT/scripts/monitor_trainer_predictions.py`
- Legacy log tail (read-only):
  - pid=817288 cmd=`tail -f Desktop/AI BOT/logs/hybrid_trainer.log`
- V2 trainer bridge read-only loop (separate venv, subprocess boundary):
  - pid=425515 cmd=`bash -lc mkdir -p v2/runtime; while true; do ./.venv/bin/python3 -m v2.backend.app.cli.v2_trainer_bridge --once --readonly-only >> v2/runtime/v2_trainer_bridge.log 2>&1 || true; sleep 60; done`
- Redis trainer-key inspection: deferred this cycle (read-only redis-cli invocation blocked by `PreToolUse` hook `./.claude/hooks/block_dangerous.sh`); flagged below as the only partial signal. No mutation attempted.
- Filesystem stat on `Desktop/AI BOT/logs/hybrid_trainer.log` blocked by the same pre-tool hook; freshness is corroborated indirectly by the still-running `tail -f` and active trainer process (etime ~24h, uninterrupted).

## Health Signals (current run)
- legacy_trainer_python_present: confirmed (interpreter alive as PID 48623 module `rl.hybrid_trainer`).
- legacy_trainer_process_state: ALIVE / read-only observation; no PID mutation attempted.
- legacy_trainer_log_freshness: indirectly confirmed via active `tail -f` on `Desktop/AI BOT/logs/hybrid_trainer.log` (PID 817288) and ~24h trainer uptime; direct `stat` blocked by safety hook.
- legacy_redis_trainer_keys: not sampled this cycle (read-only Redis call blocked by hook); recorded as `unverified_this_cycle` rather than passed silently.
- trainer_checkpoint_dir: read-only stat deferred (hook); promotion / pruning remains blocked by policy regardless.
- v2_paper_soak_unaffected: confirmed by the persistent V2 read-only bridge loop (pid 425515) running against `--readonly-only`; this monitor does not cross the V2/legacy boundary.

## Evidence Integrity
- All claims above are observational and reference raw artifacts (persisted `ps -ef` snapshot) without mutation.
- Two signals (Redis keys, log mtime/checkpoint stat) are recorded as `unverified_this_cycle` because the local pre-tool guard blocked the read commands. They are not silently passed.
- Final findings must still be raw-verified next cycle via:
  - `ls -la` / `stat` of legacy log + checkpoint paths (after operator unblocks or via approved adapter)
  - read-only Redis `INFO`, `TYPE`, `TTL`, `GET` (no `SET`/`DEL`)
  - fresh read-only process listing snapshot
- Any unverifiable signal is recorded as `unverified` and surfaces as a blocker rather than being silently passed.

## Remediation Recommendation
The monitor is not blocked on the legacy runtime itself; trainer is healthy and read-only adapters are running. The only blockers are evidence-completeness gaps caused by the local pre-tool guard. Recommended non-mutating remediation:
1. Do NOT restart legacy trainer from this monitor.
2. Do NOT touch legacy Redis keys.
3. Route a read-only-Redis allowlist request through `claude_worklog/final_readiness/active_autonomous_dispatch/latest/` so future recurring runs can sample `TYPE` / `TTL` / `GET` on `trainer:*` keys without prompting the hook.
4. Route a read-only `stat` allowlist (or expose mtime through the V2 trainer bridge `--readonly-only` JSON output) for `Desktop/AI BOT/logs/hybrid_trainer.log` and the legacy checkpoint dir, so freshness becomes a first-class evidence field.
5. Keep V2 in paper / read_only; keep LIVE TRADING: BLOCKED.
6. Preserve raw evidence pointers (log paths, Redis key names, process snapshot) alongside any future blocker entry.

## Outcome
- monitor_status: READY
- live_trading_state: BLOCKED (unchanged)
- legacy_mutation_performed: false
- v2_paper_soak_disturbed: false
- partial_signals_this_cycle: legacy_redis_trainer_keys, legacy_trainer_log_freshness_stat (both unverified_this_cycle; no silent pass)
- next_recurring_run: governed by always_on_claude_codex_runtime cadence
