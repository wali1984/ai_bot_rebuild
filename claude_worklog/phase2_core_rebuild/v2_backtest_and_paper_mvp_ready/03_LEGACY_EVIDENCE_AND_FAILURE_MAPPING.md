# Legacy Evidence Consulted and Legacy Failure Mapping

REQ_0019, REQ_0020, REQ_0022, REQ_0023, and REQ_0024 require every V2 build milestone to state the legacy evidence consulted, the legacy behavior preserved, the legacy failure addressed, and the V2 proof gate that validates the fix. The seven REQ_0017 milestones each carried that mapping in their per-milestone planning artifacts (`00_*_SUB_PHASE_BREAKDOWN.md`, `01_*_LEGACY_EVIDENCE_REVIEW.md`, and the per-sub-phase implementation reports). This file consolidates the per-milestone mapping for the consolidation gate.

## Legacy evidence consulted (read-only audit roots)

- `claude_worklog/legacy_runtime_audit/00_AUDIT_INDEX.md`
- `claude_worklog/legacy_runtime_audit/06_TRAINER_RUNTIME_EVIDENCE.md`
- `claude_worklog/legacy_runtime_audit/07_ORCHESTRATOR_TRADER_RUNTIME_EVIDENCE.md`
- `claude_worklog/legacy_runtime_audit/09_SIGNAL_TO_EXECUTION_RUNTIME_AUDIT.md`
- `claude_worklog/legacy_runtime_audit/10_RISK_AND_SAFETY_RUNTIME_AUDIT.md`
- `claude_worklog/legacy_runtime_audit/11_FAILURE_MODE_AND_GAP_REGISTER.md`
- `claude_worklog/legacy_runtime_audit/12_LEGACY_MONITOR_INVENTORY.md`
- `claude_worklog/legacy_readonly_audit/00_AUDIT_INDEX.md` (per REQ_0023, where authored)
- `claude_worklog/legacy_readonly_audit/08_FAILURE_CASE_REGISTER.md` (per REQ_0023, where authored; includes LAB hedge-unwind / squeeze case per REQ_0022)
- `claude_worklog/phase2_core_rebuild/legacy_evidence/00_EVIDENCE_INDEX.md` (per REQ_0019, where authored)
- `claude_worklog/phase2_core_rebuild/legacy_service_map/01_STARTUP_SCRIPT_SERVICE_MAP.md`
- `claude_worklog/phase2_core_rebuild/legacy_service_map/02_RUNTIME_PROCESS_PARITY_MAP.md`
- `claude_worklog/phase2_core_rebuild/legacy_service_map/05_INGESTOR_TO_FEATURE_PIPELINE_MAP.md`
- `claude_worklog/phase2_core_rebuild/legacy_service_map/06_TRAINER_ORCHESTRATOR_TRADER_MAP.md`
- `claude_worklog/phase2_core_rebuild/feature_snapshots/01_LEGACY_FEATURE_PIPELINE_PARITY.md`
- `claude_worklog/phase2_core_rebuild/symbol_universe/01_LEGACY_CONFIG_SYMBOL_BEHAVIOR.md`
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity/01_LEGACY_HYBRID_TRAINER_BEHAVIOR_INVENTORY.md`

## Legacy behavior preserved

- `live_coinank.py` is preserved as-is (REQ_0020 § "live_coinank.py"). The seven REQ_0017 typed surfaces do NOT modify, refactor, rename, or import legacy ingestor source files. They consume read-only adjudicated typed inputs, not raw legacy module instances.
- The legacy hybrid trainer GPU / batching / checkpoint / model-loading assumptions are preserved by the REQ_0017 milestone 1 subprocess-boundary adapter (REQ_0006 protected-runtime policy). The V2 trainer prediction output composition root does NOT import the legacy trainer module into the FastAPI process; it is invoked through the subprocess adapter authored under 2E1.
- The legacy 25-symbol active subset behavior (REQ_0020 § "config.py symbols") is preserved by the symbol-universe artifacts; no REQ_0017 milestone collapses USD-M, COIN-M, USDC, dated contracts, or spot-like symbols.
- No mutation of `/home/wali/Desktop/AI BOT`. Verified via `git diff --stat` checks in each per-milestone Codex review.

## Legacy failures addressed (per REQ_0017 milestone)

### Milestone 1 — Trainer prediction output

- Legacy failure: process-alive-but-prediction-worker-dead state silently held the legacy bot in a no-prediction posture without typed boundary; missing `prediction_id`, missing `feature_snapshot_id`, missing confidence attribution surface (REQ_0020 § "GPU trainer" "V2 must fix").
- V2 fix: typed `TrainerPredictionRecord` carries `prediction_id`, `feature_snapshot_id`, `confidence_attribution_summary`, `prediction_freshness` enum (`fresh` / `stale` / `missing`), and the typed worker-health surface (`HEALTHY` / `DEGRADED` / `CRITICAL` / `UNKNOWN`). Downstream consumers (orchestrator decision, risk gateway, paper-execution ledger, replay/backtest runner) pattern-match on the typed surface; they cannot silently consume an undefined-confidence or worker-dead prediction.
- V2 proof gate: `PHASE2E3C_TRAINER_PREDICTION_OUTPUT_COMPOSITION_ROOT_CODEX_PASS` plus the per-sub-phase Codex PASS markers across 2E1 / 2E2 / 2E3.

### Milestone 2 — Orchestrator decision

- Legacy failure: orchestrator decision routing in `rl.orchestrator_worker` carried implicit string-typed proposal / signal routing, with the live-blocked posture enforced through environment variables and per-call argument passing rather than a typed value. Missing typed abstain-low-confidence / abstain-freshness-stale / abstain-freshness-missing / abstain-worker-degraded / abstain-worker-critical / abstain-worker-unknown branches meant decisions could be routed on degraded inputs without a typed abstain surface.
- V2 fix: typed `OrchestratorDecisionRecord` exhausts the four typed actions (`OPEN_LONG`, `OPEN_SHORT`, `HOLD`, `ABSTAIN`) and the typed reason constants enumerated in §02; abstain branches are mandatory for low-confidence / stale-freshness / missing-freshness / degraded-worker / critical-worker / unknown-worker inputs.
- V2 proof gate: `PHASE2F_C_ORCHESTRATOR_DECISION_COMPOSITION_ROOT_CODEX_PASS`.

### Milestone 3 — Risk-gateway default-deny

- Legacy failure: `trading/trader.py` and `rl.orchestrator_worker` had no default-deny risk boundary; missing typed allow/deny exhaustion meant the LAB hedge-unwind / squeeze failure case (REQ_0022) could route a hedge-close in a code path that did not type-check residual exposure.
- V2 fix: typed `RiskDecisionRecord` with two-action exhaustion (`ALLOW` / `DENY`) and a default-DENY branch (`RISK_DECISION_REASON_DENY_DEFAULT`); ALLOW paths are exhaustive (`ALLOW_PROCEED_LONG`, `ALLOW_PROCEED_SHORT`); orchestrator-abstained / orchestrator-held inputs DENY by typed reason.
- V2 proof gate: `PHASE2G_C_RISK_GATEWAY_COMPOSITION_ROOT_CODEX_PASS`.

### Milestone 4 — Paper-execution ledger

- Legacy failure: legacy bot had no typed paper-execution ledger entry contract; ledger / log writes for hypothetical paper paths were inconsistent and lacked typed mirror semantics relative to the upstream risk decision.
- V2 fix: typed `PaperExecutionLedgerEntry` mirrors the upstream `RiskDecisionRecord` typed surface with two-action exhaustion (`RECORD_ALLOW` / `RECORD_DENY`) and the typed mirror-reason constants. The recorder does not introduce PnL, position sizing, fees, slippage, or persistence at this milestone (those belong to downstream evidence-collection lanes per REQ_0020).
- V2 proof gate: `PHASE2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_CODEX_PASS`.

### Milestone 5 — Replay/backtest runner

- Legacy failure: legacy bot had no replayable / backtestable run typed surface; ad hoc replay scripts conflated mode (replay-vs-backtest), step records, and run summaries.
- V2 fix: typed `ReplayBacktestRun` (with two typed mode constants), typed `ReplayBacktestStep` (with mirror action / reason constants), and typed `ReplayBacktestSummary`; the composition root `ReplayBacktestRunner` exposes a single typed entrypoint that downstream evidence-collection lanes invoke without introducing a strategy library, a scheduler, or a background loop at this milestone.
- V2 proof gate: `PHASE2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_CODEX_PASS`.

### Milestone 6 — Paper-mode runtime flag

- Legacy failure: legacy `trader.py` and `rl.orchestrator_worker` carried implicit live-mode posture through environment variables and per-call argument passing, which made it impossible to assert the live-blocked posture by typed value and was a contributing factor in the LAB hedge-unwind / squeeze failure (REQ_0022).
- V2 fix: typed `PaperModeFlag` with two-state exhaustion (`PAPER_MODE_PAPER` default / `PAPER_MODE_LIVE_BLOCKED`), `live_blocked: bool == True` invariant on every instance; constructing with `live_blocked == False` raises `PaperModeDomainError`. There is NO `live_enabled` constant.
- V2 proof gate: `PHASE2J_C_PAPER_MODE_RUNTIME_FLAG_COMPOSITION_ROOT_CODEX_PASS`.

### Milestone 7 — Shadow-mode-readiness flag

- Legacy failure: legacy `monitor_trainer_predictions.py`, `monitor_trainer_prices.py`, `monitor_portfolio_primary.py`, and `monitor_portfolio_asjad.py` inspect runtime state without a typed precondition flag, which made it impossible to assert shadow-mode readiness by typed value and was a contributing factor in the LAB hedge-unwind / squeeze failure (REQ_0022) and in the broader failure-class register where decisions were made on stale or partially-initialized runtime state (REQ_0023, REQ_0024).
- V2 fix: typed `ShadowModeReadinessFlag` with two-state exhaustion (`SHADOW_MODE_NOT_READY` default / `SHADOW_MODE_READY`), `live_blocked: bool == True` invariant on every instance. There is NO `SHADOW_MODE_LIVE`, `SHADOW_MODE_LIVE_ENABLED`, or `live_enabled` constant.
- V2 proof gate: `PHASE2K_C_SHADOW_MODE_READINESS_FLAG_COMPOSITION_ROOT_CODEX_PASS`.

## REQ_0022 LAB hedge-unwind / squeeze case — consolidated mapping

REQ_0022 demands V2 learn from the LAB hedge-unwind failure where the legacy bot closed the protective long around breakeven and left a short exposed before an approximately 80% pump. The seven REQ_0017 typed surfaces address the contributing factors as follows:

- Typed prediction surface (milestone 1) prevents downstream consumers from acting on undefined-confidence or worker-dead inputs.
- Typed orchestrator decision exhaustion with abstain branches (milestone 2) prevents proceed routing on degraded confidence / stale freshness / missing freshness / degraded worker / critical worker / unknown worker.
- Default-deny risk gateway (milestone 3) prevents allow routing on orchestrator-abstained / orchestrator-held / default branches.
- Typed paper-execution ledger entry (milestone 4) records every typed risk-decision mirror action so downstream replay can compare hypothetical paper-mode behavior against legacy actions.
- Typed replay/backtest runner (milestone 5) provides the typed entrypoint a downstream evidence-collection lane will use to instantiate the LAB hedge-unwind replay case (REQ_0022 § "Required replay/backtest case").
- Typed paper-mode flag (milestone 6) ensures the runtime mode is asserted by typed value (`live_blocked == True` invariant) at every consumer site, replacing the implicit env-var / per-call argument-passing posture that contributed to the LAB failure.
- Typed shadow-mode-readiness flag (milestone 7) ensures the readiness posture is asserted by typed value before any future shadow-mode comparison consumer attempts to compare V2 behavior to legacy behavior.

The downstream LAB hedge-unwind replay case authoring itself (REQ_0022 § "Required replay/backtest case") is NOT in scope of this consolidation gate; it is authored under the post-consolidation evidence-collection lane enumerated in `07_NEXT_STEP_AFTER_CONSOLIDATION.md`. The consolidation gate certifies only that the typed surfaces required to author the case exist.

V2_BACKTEST_AND_PAPER_MVP_READY_LEGACY_EVIDENCE_AND_FAILURE_MAPPING_READY
