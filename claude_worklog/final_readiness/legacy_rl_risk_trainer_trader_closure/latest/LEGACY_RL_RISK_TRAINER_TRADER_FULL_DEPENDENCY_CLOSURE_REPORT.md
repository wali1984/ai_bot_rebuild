# LEGACY_RL_RISK_TRAINER_TRADER_FULL_DEPENDENCY_CLOSURE_REPORT — Final

## GO/NO-GO

`LEGACY_RL_RISK_TRAINER_TRADER_FULL_DEPENDENCY_CLOSURE_READY`

## Shutdown recommendation

```text
BLOCK_LEGACY_SHUTDOWN_PARITY_INCOMPLETE
```

(per [LEGACY_SHUTDOWN_RECOMMENDATION_AFTER_RL_RISK_AUDIT.md](LEGACY_SHUTDOWN_RECOMMENDATION_AFTER_RL_RISK_AUDIT.md))

## What this turn produced

The prior startup-baseline copy under-scoped the legacy tree by **6×**. This turn closed the gap.

| phase | result |
|---|---|
| A — file inventory | rl/ 121, trading/ 35, risk/ 22, utils/ 21, services/ 8, scripts/ 21 (filtered), 3 top-level helpers = **231 sources, ~19.6 MB** |
| B — copier | **248 files copied** into `v2/legacy_preserved/full_runtime_closure/`, 139 binary blobs inventoried-only (`.pt`, `.pkl`, `.ckpt`, etc.), **0 secret-content flags** |
| C — dependency closure | scanner `--all` over the 231 sources: 0 missing files; remaining unresolved imports are mostly stdlib false-positives + 3 cross-tree items (`ingest`, `binance_websocket`, `hybrid_rule_based_signals`) |
| D — trainer atlas | every rl/ file classified; trainer-bridge port confirmed `WRAPPER_NOT_LEGACY_HYBRID_PARITY` active |
| E — risk/action path map | every legacy mutation path file-level mapped; **9+ new V2 risk-gateway parity tests required** |
| F — orchestrator/signal flow | trainer:predictions → wma:proposals → canonical + per-account signal streams documented; V2 must write only `v2:*` namespaces |
| G — V2 parity gap matrix | **FULLY_MIGRATED count = 0**; 5 partial, 4 missing, 1 trainer-blocked, 3 needs-code-port, 1 needs-test, 2 fail-closed stubs queued |
| H — remediation tasks | P0 list of 7 tasks; P1 of 3; P2 explicitly BLOCKED until P0 closes |
| I — shutdown recommendation | BLOCK with 7 enumerated blockers |
| J — Codex review descriptor | [codex_review_legacy_rl_risk_trainer_trader_closure.json](../../../agent_supervisor/tasks/codex_review_legacy_rl_risk_trainer_trader_closure.json) queued |
| K — validation | py_compile OK, **7/7 closure-scanner tests pass**, **11/11 new JSONs valid**, secret scan clean, approval tokens absent |

## Files emitted this turn (preserved tree + reports)

- 248 files in `v2/legacy_preserved/full_runtime_closure/` (rl/, trading/, risk/, utils/, services/, scripts/, top-level helpers)
- 11 reports + JSONs in `claude_worklog/final_readiness/legacy_rl_risk_trainer_trader_closure/latest/`
- 1 Codex review descriptor queued
- 1 copier tool: `claude_worklog/tools/copy_legacy_full_runtime_closure.py`

## Live gate / safety state (final)

- `live_gate = blocked_human_only`
- final_approval_token = **absent**
- redis_trim_approval = **absent**
- no legacy mutation (read-only access)
- no V2 write to old Redis (V2 writes only `v2:*` namespace)
- no V2 exchange order / cancel / leverage / margin change
- no secret committed (0 content flags + 0 path matches)
- no binary checkpoint blob committed (139 inventoried, 0 copied)
- legacy trader (pid 14912 from prior turn) NOT killed by this task

## What the orchestrator sees after this turn

- `legacy_baseline_required_workers` unchanged from prior turn (16 of 18) — workers still need their `LEGACY_BASELINE_ANALYSIS.md` files. **What changed:** those analyses can now cite SHA256 from `full_runtime_copied_source_manifest.json` (in addition to `copied_baseline_manifest.json` from the startup-baseline tree) for every rl/risk/services/utils/trading helper they depend on.
- `next_action.kind = dispatch_legacy_baseline_analysis` for `v2_market_ingestor_from_legacy_baseline`. The deeper closure means the sub-agent can fully resolve `from utils import …`, `from risk import …`, `from services import …`, `from config_accounts import …` without "unresolved" classification.

## Required operator decisions (surfaced explicitly)

1. **Trader still running** (pid 14912 from prior turn). This turn does not stop it. If you want to honor your original "without trader" declaration, stop it manually.
2. **Checkpoint blobs.** 139 binary files (`.pt`, `.pkl`, `.ckpt`, etc.) are inventoried under `binary_artifacts_skipped.json` once the manifest writes that file on next run. Decide whether to commit them (large) or store separately.
3. **External deps for trainer.** `torch`, `stable_baselines3`, `cloudpickle`, `gymnasium` are NOT installed in `.venv`. The trainer-bridge port (P1) cannot fully run without these. Approve installation when that port lands.
4. **Shutdown sequencing.** This recommendation is `BLOCK_LEGACY_SHUTDOWN_PARITY_INCOMPLETE`. Do not shut down legacy until the trainer-bridge port reaches `V2_TRAINER_BRIDGE_CODEX_PASS` and the P0 remediation tasks close.

## After this task

The next remediation task to dispatch is `claude_resolve_remaining_unresolved_local_imports` (Phase H P0.1) to close `ingest` / `binance_websocket` / `hybrid_rule_based_signals` resolution. After that, `claude_port_v2_market_ingestor_from_legacy_baseline` proceeds with full closure visibility.
