# V2_CODEX_SPARK_BACKWARD_COMPATIBILITY_AND_CANARY_CUTOVER_REPORT

**Verdict: V2_CODEX_SPARK_BACKWARD_COMPATIBILITY_AND_CANARY_CUTOVER_READY**

---

## Safety envelope (hard constraints — not overridable)

| Constraint | Value |
|---|---|
| live_gate | `blocked_human_only` |
| live_symbols | `[]` |
| approves_live | `false` |
| approves_canary | `false` |
| legacy stopped | NO |
| V2 runtime stopped | NO |
| report-center stopped | NO |
| replay-miner stopped | NO |
| old Redis written | NO |
| exchange mutation | NO |
| approvals created | NO |

---

## Failures found and fixed

### Failure 1 — `v2_closed_loop_worker_pool.py` wrapper: unrecognized legacy CLI args

- **Root cause:** The existing systemd service unit `ai-bot-v2-closed-loop-worker-pool.service` calls
  the wrapper with `run-once --spawn --target-claude 3 --target-codex 3`. The Spark CLI only
  accepts `--db-path`, `--max-iterations`, `--only-workers`, `--lane-group`. Argparse raised
  `error: unrecognized arguments` → service failed.
- **Fix:** Added a backward-compat shim in `v2_closed_loop_worker_pool.py` that strips the
  legacy positional subcommand and flags via `parse_known_args` before delegating to Spark.

### Failure 2 — `v2_autonomous_mission_backlog_autoseed.py` wrapper: two issues

- **Root cause A:** Service file `ai-bot-v2-autonomous-mission-backlog.service` had
  `PYTHONPATH=…/claude_worklog/tools` **without** the repo root. The wrapper does
  `from v2.backend…` which needs the repo root → `ModuleNotFoundError: No module named 'v2'`.
- **Root cause B:** Service passes `--wait-seconds 5 --json` which the Spark autoseed CLI
  doesn't accept → argparse error.
- **Fix A:** Added `/home/wali/Desktop/AI BOT REBUILD` to the service `PYTHONPATH` environment.
  `systemctl --user daemon-reload` applied.
- **Fix B:** Added backward-compat shim in wrapper to strip `--wait-seconds` and `--json`.

### Failure 3 — `v2_autonomous_mission_execution_burndown.py` wrapper: unrecognized `--json`

- **Root cause:** Service passes `--json`; Spark burndown CLI has no such arg.
- **Fix:** Added `--json` shim to wrapper.

---

## Phase 1 — Existing automation inventory

Artifact: `existing_automation_inventory.json`

Key findings:
- 6 wrapper files inventoried, all present.
- 70+ systemd unit files found (services + timers).
- 3 × Claude persistent workers + 3 × Codex persistent workers active/running.
- Report-center timer: every 60 s.
- Autoseed timer: every 120 s (after 90 s boot).
- Burndown timer: every 300 s (after 90 s boot).
- Worker-pool timer: every 2 min.
- Replay-miner timer: every 60 s.
- Spark DB not yet created (canary not yet started).

---

## Phase 2 — Wrapper compatibility matrix

Artifact: `wrapper_compatibility_matrix.json`

| Wrapper | Import | Legacy args | Symbols | GO/NO-GO |
|---|---|---|---|---|
| v2_closed_loop_worker_pool.py | ✅ | ✅ (after fix) | ✅ | READY |
| v2_closed_loop_claude_worker.py | ✅ | ✅ | ✅ | READY |
| v2_closed_loop_codex_worker.py | ✅ | ✅ | ✅ | READY |
| v2_autonomous_mission_backlog_autoseed.py | ✅ | ✅ (after fix) | ✅ | READY |
| v2_autonomous_mission_execution_burndown.py | ✅ | ✅ (after fix) | ✅ | READY |
| v2_burndown_fail_to_remediation_mapper.py | ✅ | ✅ | ✅ | READY |

**Overall: READY**

---

## Phase 3 — Live automation continuity

Artifact: `automation_continuity_status.json`

- Persistent workers (3 × Claude, 3 × Codex): **active/running** ✅
- Report-center, replay-miner: inactive/dead (timer-driven, not persistent) — normal.
- Autoseed: was failing due to PYTHONPATH bug → **fixed**.
- Burndown: was failing due to `--json` unrecognized arg → **fixed**.
- Agent supervisor: active/running ✅

---

## Phase 4 — Spark canary mode proof

Artifact: `spark_canary_cutover_status.json`

- Spark DB not created (canary not started) → existing workers use file-backed path ✅
- Worker-pool assigns lane IDs with `"-canary"` suffix → canary label enforced ✅
- `_safe_to_claim()` blocks: unsafe live_gate, non-empty live_symbols, approves_live=True, approves_canary=True ✅
- Production automation continues running independently ✅
- Rollback flag: `LEASE_BACKEND=file` → bypasses SQLite entirely
- **Verdict: CANARY_GATED_NOT_PRODUCTION_READY**

---

## Phase 5 — Rollback plan

Script: `claude_worklog/tools/v2_codex_spark_rollback.py`
Artifact: `spark_rollback_proof.json`

Two modes:
- `--mode=file-backend` (default): injects `LEASE_BACKEND=file` drop-in into canary unit dirs.
- `--mode=disable-canary-units`: stops + disables Spark-only timer/service units.

Protected units (NEVER touched by rollback):
- `ai-bot-v2-closed-loop-claude-worker@{1,2,3}.service`
- `ai-bot-v2-closed-loop-codex-worker@{1,2,3}.service`
- `ai-bot-v2-report-center-indexer.service`
- `ai-bot-v2-post-hoc-replay-outcome-miner.service`
- `ai-bot-v2-agent-supervisor.service`
- `ai-bot-v2-autonomous-mission-backlog.service`
- `ai-bot-v2-autonomous-mission-execution-burndown.service`

Spark DB preserved (copy to `.audit-preserved-<ts>.db`, never deleted).

---

## Phase 6 — Regression tests

File: `claude_worklog/tools/tests/test_backward_compat.py`

**29/29 tests pass.**

| Test class | Coverage |
|---|---|
| TestLegacyArgsAccepted (6) | Legacy CLI args accepted by all 6 wrappers |
| TestSparkSymbolsPresent (6) | All exported symbols present |
| TestReportCenterPayloadParsing (2) | Old lane payload schema stable |
| TestCanaryCannotMarkProductionReady (2) | Spark canary blocked from production |
| TestRollbackPreservesOldPath (4) | Rollback script correct and proven |
| TestImportFailureBlocksReady (1) | Missing v2.* causes ImportError |
| TestActiveAutomationFreshness (2) | Workers running, continuity file exists |
| TestNoOldRedisWrites (2) | No legacy Redis write calls in Spark |
| TestNoExchangeMutation (2) | No exchange adapter imports in Spark |
| TestNoApprovals (2) | Canary approval blocked, no approval files |

---

## Artifacts emitted

| File | Purpose |
|---|---|
| `existing_automation_inventory.json` | Phase 1 — full unit/wrapper inventory |
| `wrapper_compatibility_matrix.json` | Phase 2 — per-wrapper compatibility check |
| `automation_continuity_status.json` | Phase 3 — live continuity check |
| `spark_canary_cutover_status.json` | Phase 4 — Spark canary gate proof |
| `spark_rollback_proof.json` | Phase 5 — rollback dry-run proof |
| `GO_NO_GO.md` | Final verdict |
| `operator_payload.json` | Machine-readable operator summary |
| `V2_CODEX_SPARK_BACKWARD_COMPATIBILITY_AND_CANARY_CUTOVER_REPORT.md` | This report |
| `claude_worklog/tools/v2_codex_spark_rollback.py` | Executable rollback script |
| `claude_worklog/tools/tests/test_backward_compat.py` | 29-test regression suite |
