# LEGACY_SHUTDOWN_RECOMMENDATION_AFTER_RL_RISK_AUDIT — Phase I

## Recommendation

```text
BLOCK_LEGACY_SHUTDOWN_PARITY_INCOMPLETE
```

## Why

| blocker | evidence |
|---|---|
| Trainer parity not achieved | Phase D classifies `WRAPPER_NOT_LEGACY_HYBRID_PARITY` active; V2 paper mode runs a momentum stub, not the legacy trainer; 120+ rl/ helpers preserved but not yet enumerated in any V2 LEGACY_BASELINE_ANALYSIS.md |
| Risk/action paths not yet test-covered | Phase E identifies 9+ legacy risk gates with no V2-side parity tests; risk gateway library exists but lacks tests for kill_switch, halt_manager, reduce_only_latch, intelligent_close_guard, auto_deleverager, shared_risk_gate, margin_governor, phase_controller, adaptive_gate |
| Account/position monitor MISSING_IN_V2 | Phase G classifies it; legacy `services/portfolio_state.py` + `services/portfolio_publisher.py` + `monitor_portfolio_*.py` not yet ported to a V2 read-only monitor |
| Signal publisher MISSING_IN_V2 | Phase F shows legacy `utils/signal_publish.py` + `utils/signal_schema.py` field schema not yet adopted by V2; placeholder service file only |
| Baseline-anchored ingestor / coinank / feature-pipeline ports not yet implemented | Phase G classifies three workers as `NEEDS_CODE_PORT`; task descriptors queued from prior turn |
| Trade permission read-only/unknown | Operator state shows trade-permission evidence pending; V2 cannot confirm whether exchange keys are read-only |
| Paper-shadow PnL ≈ -49.12 with flat fills at 2271 and rising blocked-intents | Reported in the prior turn's paper-edge-tightening summary; not improved this turn |

Any one of these alone is sufficient to block shutdown. All seven are active.

## What would lift the recommendation

To reach `KEEP_LEGACY_RUNTIME_FOR_TRAINER_PARITY_REFERENCE` (intermediate):

- Trainer-bridge port lands with `V2_TRAINER_BRIDGE_CODEX_PASS` AND the LEGACY_BASELINE_ANALYSIS.md cites SHA256 from `full_runtime_copied_source_manifest.json` for every consumed rl/ helper.

To reach `SAFE_TO_SHUTDOWN_LEGACY_RUNTIME_FOR_V2_PAPER_ONLY`:

- All P0 remediation tasks (Phase H) closed AND Codex aggregate passes
- The 9+ legacy-equivalent risk-gate tests pass on the V2 risk gateway library
- Account/position monitor port shipped with explicit `MISSING_CREDENTIALS` classification accepted by the operator
- Signal publisher port shipped with the legacy field schema preserved
- Three baseline-anchored ingestor/coinank/feature ports shipped
- V2 paper-shadow runtime fresh and the paper-edge-tightening blockers either resolved or accepted with explicit operator decision
- live gate still `blocked_human_only`; no approval token

## What this recommendation does NOT do

- Does not stop the legacy runtime. The operator retains full authority.
- Does not modify the legacy bot tree.
- Does not propose enabling live trading at any stage. Live remains `blocked_human_only`.

## Tracking

Per-blocker progress is tracked via the per-worker Codex GO/NO-GO files under `claude_worklog/final_readiness/emergency_v2_runtime_migration/latest/workers/`. The orchestrator's `--once` tick will flip `blocked_workers` to `[]` and `legacy_baseline_required_workers` to `[]` only when the conditions above are satisfied.
