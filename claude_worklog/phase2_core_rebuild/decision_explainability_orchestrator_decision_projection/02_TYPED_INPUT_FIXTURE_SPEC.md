# Phase 2U — Typed Input Fixture Spec

## Fixture pack

The Phase 2U fixture pack defines four deterministic typed scenarios with three rows each. All fixture content is test-only, frozen-dataclass typed, and contains no PnL / size / price / fees / slippage / funding / OI / liquidation / orderbook / hedge-state / residual-exposure / squeeze-risk computation.

### Scenario 1 — `orchestrator_decision_explainability_pack_btc_winner_long`

- Symbol: `BTCUSDT`.
- Rows: 3.
- Per-row input `TrainerPredictionRecord`: direction=`long`, confidence_raw=0.85, confidence_calibrated=0.85, freshness_flag=`fresh`, source_freshness_age_ms=1500, worker_health_status=`HEALTHY`.
- Per-row produced `OrchestratorDecisionRecord`: decision_action=`open_long`, decision_reason_code=`proceed_long`, input_prediction_direction=`long`, input_prediction_confidence_calibrated=0.85, input_prediction_freshness_flag=`fresh`, input_worker_health_status=`HEALTHY`, live_blocked=True.
- `legacy_evidence_pointer`: `legacy_evidence__orchestrator_decision_explainability__btc_winner_long__step_<N>` for each row (N ∈ {0, 1, 2}).

### Scenario 2 — `orchestrator_decision_explainability_pack_eth_winner_short`

- Symbol: `ETHUSDT`.
- Rows: 3.
- Per-row input `TrainerPredictionRecord`: direction=`short`, confidence_raw=0.82, confidence_calibrated=0.82, freshness_flag=`fresh`, source_freshness_age_ms=1500, worker_health_status=`HEALTHY`.
- Per-row produced `OrchestratorDecisionRecord`: decision_action=`open_short`, decision_reason_code=`proceed_short`, input_prediction_direction=`short`, input_prediction_confidence_calibrated=0.82, input_prediction_freshness_flag=`fresh`, input_worker_health_status=`HEALTHY`, live_blocked=True.
- `legacy_evidence_pointer`: `legacy_evidence__orchestrator_decision_explainability__eth_winner_short__step_<N>`.

### Scenario 3 — `orchestrator_decision_explainability_pack_lab_loser_short`

- Symbol: `LABUSDT`.
- Rows: 3.
- Per-row input `TrainerPredictionRecord`: direction=`short`, confidence_raw=0.83, confidence_calibrated=0.83, freshness_flag=`fresh`, source_freshness_age_ms=1500, worker_health_status=`HEALTHY`.
- Per-row produced `OrchestratorDecisionRecord`: decision_action=`open_short`, decision_reason_code=`proceed_short`, input_prediction_direction=`short`, input_prediction_confidence_calibrated=0.83, input_prediction_freshness_flag=`fresh`, input_worker_health_status=`HEALTHY`, live_blocked=True.
- `legacy_evidence_pointer`: `legacy_evidence__orchestrator_decision_explainability__lab_hedge_unwind_squeeze__step_<N>` (LAB hedge-unwind / squeeze legacy-failure pointer literal per REQ_0022).

### Scenario 4 — `orchestrator_decision_explainability_pack_sol_orchestrator_abstained_low_confidence`

- Symbol: `SOLUSDT`.
- Rows: 3.
- Per-row input `TrainerPredictionRecord`: direction=`long`, confidence_raw=0.40, confidence_calibrated=0.40, freshness_flag=`fresh`, source_freshness_age_ms=1500, worker_health_status=`HEALTHY`.
- Per-row produced `OrchestratorDecisionRecord`: decision_action=`abstain`, decision_reason_code=`abstain_low_confidence`, input_prediction_direction=`long`, input_prediction_confidence_calibrated=0.40, input_prediction_freshness_flag=`fresh`, input_worker_health_status=`HEALTHY`, live_blocked=True.
- `legacy_evidence_pointer`: `legacy_evidence__orchestrator_decision_explainability__sol_orchestrator_abstained_low_confidence__step_<N>`.

## Typed test-only value classes

The fixtures module declares the following **test-only frozen dataclasses** (no production use; not exported beyond the Phase 2U test directory):

- `OrchestratorDecisionExplainabilityFixtureInput` carrying:
  - `source_scenario_slug: str` (one of the four scenario slugs).
  - `step_index: int` (0-based ordinal within scenario; range 0..2).
  - `symbol: str` (one of `BTCUSDT` / `ETHUSDT` / `LABUSDT` / `SOLUSDT`).
  - `prediction_id: str` (deterministic, slug + step ordinal).
  - `feature_snapshot_id: str`.
  - `model_version: str`.
  - `checkpoint_id: str`.
  - `worker_id: str`.
  - `prediction_ts_ms: int`.
  - `direction: str` (`long` / `short` / `flat`).
  - `confidence_raw: float`.
  - `confidence_calibrated: float`.
  - `freshness_flag: str` (`fresh` / `stale` / `missing`).
  - `source_freshness_age_ms: int | None`.
  - `worker_health_status: str` (`HEALTHY` / `DEGRADED` / `CRITICAL` / `UNKNOWN`).
  - `top_positive_feature_codes: tuple[str, ...]`.
  - `top_negative_feature_codes: tuple[str, ...]`.
  - `expected_decision_action: str` (`open_long` / `open_short` / `hold` / `abstain`).
  - `expected_decision_reason_code: str` (`proceed_long` / `proceed_short` / `hold_flat_direction` / `abstain_low_confidence` / `abstain_freshness_stale` / `abstain_freshness_missing` / `abstain_worker_degraded` / `abstain_worker_critical` / `abstain_worker_unknown`).
  - `legacy_evidence_pointer: str`.

- `OrchestratorDecisionExplainabilityEnvelope` carrying ONLY these 15 fields (no others):
  - 3 lineage IDs: `decision_id`, `prediction_id`, `feature_snapshot_id`.
  - 1 symbol: `symbol`.
  - 1 timestamp: `decision_ts_ms`.
  - 2 decision-side codes: `decision_action`, `decision_reason_code`.
  - 4 input-prediction-side mirror fields: `input_prediction_direction`, `input_prediction_confidence_calibrated`, `input_prediction_freshness_flag`, `input_worker_health_status`.
  - 1 invariant: `live_blocked` (always `True`).
  - 3 test-only metadata fields: `source_scenario_slug`, `step_index`, `legacy_evidence_pointer`.

- `OrchestratorDecisionProjectionHarnessResult` carrying ONLY:
  - `envelopes: tuple[OrchestratorDecisionExplainabilityEnvelope, ...]` (12 entries).
  - `decision_records: tuple[OrchestratorDecisionRecord, ...]` (12 entries; matched positionally to `envelopes`).

## Determinism

- `BASE_PREDICTION_TS_MS = 1_731_400_000_000`. Per-row `prediction_ts_ms` = `BASE_PREDICTION_TS_MS + scenario_index * 60_000 + step_ordinal * 100`.
- `ORCHESTRATOR_CLOCK_START_MS = 1_731_500_000_000`. The `build_orchestrator_clock()` factory returns a closure that increments by 17 ms per call, starting at `ORCHESTRATOR_CLOCK_START_MS`. The evaluator closure invokes the clock once per evaluator call (12 calls total).
- `LOW_CONFIDENCE_THRESHOLD = 0.55` (float). Confidence values 0.85 / 0.82 / 0.83 are above threshold and yield `proceed_<direction>`; 0.40 is below threshold and yields `abstain_low_confidence`.

## Top feature codes

Per-row `top_positive_feature_codes` and `top_negative_feature_codes` are deterministic non-overlapping tuples of two codes each (e.g., `("feat_0001", "feat_0002")` and `("feat_0099", "feat_0100")`). They satisfy the `TrainerPredictionRecord` validation (disjoint, unique within each tuple, non-empty, within length cap) but are NOT mirrored into the `OrchestratorDecisionExplainabilityEnvelope` (the orchestrator decision record does not carry top-feature codes).

## Hard safety

No filesystem path is opened from any `legacy_evidence_pointer` string. No file I/O, network client, environment-variable reader, or heavyweight numerics import is permitted in the fixtures module. No PnL / size / price / fees / slippage / funding / OI / liquidation / orderbook / hedge-state / residual-exposure / squeeze-risk field is permitted. No `shadow_decision_id`, `execution_intent_id`, `risk_decision_id`, `paper_trade_id`, `replay_step_id`, `replay_run_id`, or `replay_summary_id` field is permitted on the Phase 2U envelope.

PHASE2U_TYPED_INPUT_FIXTURE_SPEC_READY
