# LEGACY_STARTUP_BASELINE_TO_V2_WORKER_MIGRATION_REPORT — Final

## GO/NO-GO

`LEGACY_STARTUP_BASELINE_TO_V2_WORKER_MIGRATION_READY`

## Operator state acknowledgment + correction

- Operator declared "legacy started without trader" but the legacy trader process is observed alive (pid 14912, ~2 h uptime). Classified as `LEGACY_TRADER_PROCESS_OBSERVED_READONLY` per task contingency; not killed; flagged in [CURRENT_RUNTIME_CLASSIFICATION.md](CURRENT_RUNTIME_CLASSIFICATION.md). Operator should decide whether to stop it.
- Trainer flag observed differs from the startup-script form (different epochs / batch-size / no training-mode flag). Both forms recorded; operator decides.

## Phase outcomes (compact)

| phase | result |
|---|---|
| **A** runtime classification | trader observed contrary to declaration; tokens applied |
| **B** baseline matrix | 11 phases, ~30 scripts, env vars, Redis stream inventory parsed |
| **C** baseline copy | **33 of 39 files copied** (6.2 MB); 6 explicit MISSING_IN_LEGACY_BASELINE; zero secret-content flags |
| **D** dependency closure | 32 files analyzed, 0 parse errors, 20 with Redis use, 16 with exchange API use, **7/7 tests pass** |
| **E** env parity | inventory only; no installs; deferred torch / stable_baselines3 |
| **F** orchestrator + descriptor patch | WORKER_SEQUENCE updated; 3 new claude_port + 3 paired codex_review + 1 baseline audit descriptor |
| **G** porting sequence | ingestor-first ordering encoded |
| **H** dispatch status | next worker = `v2_market_ingestor_from_legacy_baseline` |
| **I** Codex review | queued |
| **J** website realignment | V2-namespaced payloads only |
| **K** V2 local runtime | classified `V2_LOCAL_ONLINE_BLOCKED_BASELINE_COPY_COMPLETE_BUT_WORKERS_NOT_PORTED_YET` |
| **L** validation | py_compile OK; 7/7 closure tests; **16/16** new JSONs valid; secret scan clean; approval tokens absent |

## Live gate / safety state (final)

- live_gate = `blocked_human_only`
- final_approval_token = absent
- redis_trim_approval = absent
- legacy mutation = none
- V2 write to old Redis = none
- exchange / cancel / leverage / margin mutation = none
- secret committed = none

## What the orchestrator selects after this turn

```text
next_worker      = v2_market_ingestor_from_legacy_baseline
next_action.kind = dispatch_legacy_baseline_analysis
```

## Next operator action

```text
bash claude_worklog/tools/start_v2_worker_porting_control_plane.sh
bash claude_worklog/tools/status_v2_worker_porting_control_plane.sh
```

Once the four control-plane tmux sessions are alive in a normal terminal, `agent_supervisor.py` picks up `claude_port_v2_market_ingestor_from_legacy_baseline.json`. The sub-agent's LEGACY-FIRST MANDATE forces it to produce the baseline analysis (with SHA256 citations from `copied_baseline_manifest.json`) before any V2 code. Codex review then enforces the same.

## Counter-recommendation if operator wants to honor original declaration

The legacy trader process is still running. If the operator wants to actually run "without trader" as originally declared, the operator can stop pid 14912 manually. The market ingestor migration does not require it.
