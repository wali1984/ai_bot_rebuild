# Phase 2T — Typed Input Fixture Spec

## Fixture pack

The Phase 2T fixture pack defines four deterministic typed scenarios with three step rows each, plus one summary row per scenario. All fixture content is test-only, frozen-dataclass typed, and contains no PnL / size / price / fees / slippage / funding / OI / liquidation / orderbook / hedge-state / residual-exposure / squeeze-risk computation.

### Scenario 1 — `replay_step_explainability_pack_btc_winner_long`

- Symbol: `BTCUSDT`.
- Steps: 3.
- Per-step input `RiskDecisionRecord` action = `ALLOW`, reason = `RISK_OK`.
- Per-step assembled `PaperExecutionLedgerEntry` ledger_action = `ALLOW`, ledger_reason_code = `RISK_OK`.
- Per-step assembled `ReplayBacktestStep` step_action = `ALLOW`, step_reason_code = `PROCEED_LONG`, input_paper_action = `ALLOW`, input_paper_reason_code = `RISK_OK`.
- Per-scenario assembled `ReplayBacktestSummary`:
  - `total_steps_count` = 3.
  - `record_allow_steps_count` = 3.
  - `record_deny_steps_count` = 0.
  - `mirror_allow_proceed_long_steps_count` = 3.
  - `mirror_allow_proceed_short_steps_count` = 0.
  - `mirror_deny_orchestrator_held_steps_count` = 0.
  - `mirror_deny_orchestrator_abstained_steps_count` = 0.
  - `mirror_deny_default_steps_count` = 0.
- `legacy_evidence_pointer`: `legacy_evidence__replay_step_explainability__btc_winner_long__step_<N>` for steps; `legacy_evidence__replay_step_explainability__btc_winner_long__summary` for summary.

### Scenario 2 — `replay_step_explainability_pack_eth_winner_short`

- Symbol: `ETHUSDT`.
- Steps: 3.
- Per-step input `RiskDecisionRecord` action = `ALLOW`, reason = `RISK_OK`.
- Per-step assembled `ReplayBacktestStep` step_action = `ALLOW`, step_reason_code = `PROCEED_SHORT`, input_paper_action = `ALLOW`, input_paper_reason_code = `RISK_OK`.
- Per-scenario assembled `ReplayBacktestSummary` `mirror_allow_proceed_short_steps_count` = 3; all other partition counts = 0; `record_allow_steps_count` = 3.
- `legacy_evidence_pointer`: `legacy_evidence__replay_step_explainability__eth_winner_short__step_<N>` / `..._summary`.

### Scenario 3 — `replay_step_explainability_pack_lab_loser_short`

- Symbol: `LABUSDT`.
- Steps: 3.
- Per-step input `RiskDecisionRecord` action = `ALLOW`, reason = `RISK_OK`.
- Per-step assembled `ReplayBacktestStep` step_action = `ALLOW`, step_reason_code = `PROCEED_SHORT`, input_paper_action = `ALLOW`, input_paper_reason_code = `RISK_OK`.
- Per-scenario assembled `ReplayBacktestSummary` `mirror_allow_proceed_short_steps_count` = 3; all other partition counts = 0; `record_allow_steps_count` = 3.
- `legacy_evidence_pointer`: `legacy_evidence__replay_step_explainability__lab_hedge_unwind_squeeze__step_<N>` / `..._summary` (LAB hedge-unwind / squeeze legacy-failure pointer literal per REQ_0022).

### Scenario 4 — `replay_step_explainability_pack_sol_orchestrator_held`

- Symbol: `SOLUSDT`.
- Steps: 3.
- Per-step input `RiskDecisionRecord` action = `DENY`, reason = `ORCHESTRATOR_HELD`.
- Per-step assembled `ReplayBacktestStep` step_action = `DENY`, step_reason_code = `ORCHESTRATOR_HELD`, input_paper_action = `DENY`, input_paper_reason_code = `ORCHESTRATOR_HELD`.
- Per-scenario assembled `ReplayBacktestSummary` `mirror_deny_orchestrator_held_steps_count` = 3; all other partition counts = 0; `record_deny_steps_count` = 3.
- `legacy_evidence_pointer`: `legacy_evidence__replay_step_explainability__sol_orchestrator_held__step_<N>` / `..._summary`.

## Typed test-only value classes

The fixtures module declares the following **test-only frozen dataclasses** (no production use; not exported beyond the Phase 2T test directory):

- `ReplayBacktestStepExplainabilityFixtureInput` carrying:
  - `source_scenario_slug: str` (one of the four scenario slugs).
  - `step_index: int` (0-based ordinal within scenario; range 0..2).
  - `symbol: str` (one of `BTCUSDT` / `ETHUSDT` / `LABUSDT` / `SOLUSDT`).
  - `risk_decision_id: str` (deterministic, slug + step ordinal).
  - `decision_id: str`.
  - `prediction_id: str`.
  - `feature_snapshot_id: str`.
  - `risk_decision_action: str` (`ALLOW` / `DENY`).
  - `risk_decision_reason_code: str` (`RISK_OK` / `ORCHESTRATOR_HELD`).
  - `expected_step_action: str` (`ALLOW` / `DENY`).
  - `expected_step_reason_code: str` (`PROCEED_LONG` / `PROCEED_SHORT` / `ORCHESTRATOR_HELD`).
  - `legacy_evidence_pointer: str`.
- `ReplayBacktestStepExplainabilityEnvelope` carrying ONLY these 17 fields (no others):
  - 7 lineage IDs: `replay_step_id`, `replay_run_id`, `paper_trade_id`, `risk_decision_id`, `decision_id`, `prediction_id`, `feature_snapshot_id`.
  - 1 symbol: `symbol`.
  - 1 timestamp: `step_ts_ms`.
  - 4 action / reason codes: `step_action`, `step_reason_code`, `input_paper_action`, `input_paper_reason_code`.
  - 1 invariant: `live_blocked` (always `True`).
  - 3 test-only metadata fields: `source_scenario_slug`, `step_index`, `legacy_evidence_pointer`.
- `ReplayBacktestSummaryExplainabilityEnvelope` carrying ONLY these 14 fields (no others):
  - 2 lineage IDs: `replay_summary_id`, `replay_run_id`.
  - 1 timestamp: `summary_emitted_ts_ms`.
  - 8 partition counts: `total_steps_count`, `record_allow_steps_count`, `record_deny_steps_count`, `mirror_allow_proceed_long_steps_count`, `mirror_allow_proceed_short_steps_count`, `mirror_deny_orchestrator_held_steps_count`, `mirror_deny_orchestrator_abstained_steps_count`, `mirror_deny_default_steps_count`.
  - 1 invariant: `live_blocked` (always `True`).
  - 2 test-only metadata fields: `source_scenario_slug`, `legacy_evidence_pointer`.
- `ReplayBacktestProjectionHarnessResult` carrying ONLY:
  - `step_envelopes: tuple[ReplayBacktestStepExplainabilityEnvelope, ...]` (12 entries).
  - `summary_envelopes: tuple[ReplayBacktestSummaryExplainabilityEnvelope, ...]` (4 entries).

## Determinism

- `BASE_RISK_TS_MS = 1_731_000_000_000`. Per-row `risk_decision_ts_ms` = `BASE_RISK_TS_MS + scenario_index * 60_000 + step_ordinal * 100`.
- `PAPER_LEDGER_CLOCK_START_MS = 1_731_100_000_000`. The `build_paper_ledger_clock()` factory returns a closure that increments by 19 ms per call, starting at `PAPER_LEDGER_CLOCK_START_MS`. 12 invocations across the harness (one per row).
- `REPLAY_CLOCK_START_MS = 1_731_200_000_000`. The `build_replay_clock()` factory returns a closure that increments by 23 ms per call, starting at `REPLAY_CLOCK_START_MS`. The `assemble_step` closure invokes the clock once per step (12 calls), and the `assemble_summary` closure invokes it once per scenario (4 calls); total 16 calls.

## Hard safety

No filesystem path is opened from any `legacy_evidence_pointer` string. No file I/O, network client, environment-variable reader, or heavyweight numerics import is permitted in the fixtures module. No PnL / size / price / fees / slippage / funding / OI / liquidation / orderbook / hedge-state / residual-exposure / squeeze-risk field is permitted.

PHASE2T_TYPED_INPUT_FIXTURE_SPEC_READY
