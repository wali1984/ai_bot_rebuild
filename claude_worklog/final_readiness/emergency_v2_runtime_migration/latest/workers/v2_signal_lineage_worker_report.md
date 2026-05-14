# v2_signal_lineage_worker — worker report

Generated: 2026-05-14T05:43:00Z

## Status

**MIGRATED_AND_RUNNABLE**. The worker is a standalone CLI signal
lineage worker. It subscribes to the V2 paper runtime bundle
(`paper_online_runtime` public payload) and emits a unified
seven-stage signal lineage record. The signal stage is produced by the
real V2 signal publisher service (`v2/backend/app/services/signal_publisher.py`)
which replaces the prior 1-line scaffold. Live remains
`blocked_human_only`.

## Trigger

`codex_review_v2_signal_lineage_worker` on emit.

## Runnable commands

```text
python3 -m v2.backend.app.cli.v2_signal_lineage_worker --once
python3 -m v2.backend.app.cli.v2_signal_lineage_worker --once --source-file ./paper_runtime_status.json
python3 -m v2.backend.app.cli.v2_signal_lineage_worker --loop --interval 30
```

## Lineage chain

The worker captures the seven per-stage records emitted by the V2
paper runtime in a single tick:

1. `market_data` — from `paper_runtime_status.json::market_feed`.
2. `feature_snapshot` — from `paper_runtime_status.json::feature_snapshot`.
3. `model_output` — from `trainer_prediction.raw_output`.
4. `trainer_prediction` — from `paper_runtime_status.json::trainer_prediction`.
5. `orchestrator_decision` — from
   `current_signal_lineage.orchestrator_decision`.
6. `risk_gateway_decision` — from
   `current_signal_lineage.risk_decision`.
7. `paper_execution_result` — from `paper_ledger_tail[0]`.

`paper_online_runtime.build_signal_lineage()` now delegates to
`v2.backend.app.services.signal_publisher.build_paper_runtime_lineage`.
The standalone signal-lineage worker reads the existing per-stage
records and produces the unified view + explainability block.

## Explainability invariant

Every present-stage explanation either:

- cites every required evidence field for the stage (each citation has
  `field_name`, `source`, `value`, `present`), or
- is replaced verbatim with `EVIDENCE_MISSING_LABEL =
  "Evidence missing — cannot explain without guessing"`.

The worker never invents an explanation. The status payload exposes
`explainability_invariant_violated`; under any failure mode this
remains `false` because the worker collapses missing-evidence
explanations to the labelled constant.

## signal_publisher.py replacement

The previous 1-line placeholder body
(`"""Signal publisher service placeholder. No behavior in scaffold."""`)
is replaced with the real implementation. The worker scans
`signal_publisher.py` on every run for scaffold remnant patterns
(`placeholder`, `todo`, `fixme`, `scaffold`, `no behavior`,
`not implemented`, `stub`). If any match is found the worker
fail-closes with
`runtime_evidence_status=PUBLISHER_REMNANT_DETECTED` so future
regressions cannot ship.

The signal publisher's `build_signal_record(...)` is called inside the
worker to produce the canonical `signal_record` stage between trainer
prediction and orchestrator decision.

## Public payload

Payloads are written to:

- `v2/frontend/public/operator_runtime/v2_signal_lineage_worker/latest/v2_signal_lineage_worker_status.json`
- `v2/runtime/v2_signal_lineage_worker/latest/v2_signal_lineage_worker_status.json`
- `claude_worklog/final_readiness/emergency_v2_runtime_migration/latest/workers/v2_signal_lineage_worker_status.json`

Required operator fields are present:

- `worker_id`, `last_run_ts`
- `live_gate`, `current_gate_state`,
  `gate_always_blocked_invariant`, `exchange_call_invariant`,
  `exchange_action_taken`, `live_blocked`
- `fail_closed`, `fail_closed_reason`,
  `missing_runtime_evidence`, `runtime_evidence_status`,
  `freshness_seconds`
- `source_payload_path`, `source_runtime_id`, `legacy_source_paths`
- `stages` (per-stage block dict), `stage_names`, `stage_order`
- `chain_complete`, `chain_consistent`, `chain_inconsistencies`
- `lineage_ids`, `signal_record`, `signal_lineage_record`
- `explainability_invariant_violated`, `evidence_missing_label`
- `placeholder_remnant_check`, `signal_publisher_self_check`
- `stale_threshold_seconds`, `warn_threshold_seconds`
- full Symbol Universe contract block (legacy/dynamic/training/paper/
  live_blocked/binance_usdm_confirmed/symbol_selection_score_factors)

Current seeded status is fail-closed because no paper runtime bundle
was available at generation time:

- `runtime_evidence_status`: `MISSING_RUNTIME_EVIDENCE`
- `current_gate_state`: `blocked_human_only`
- `chain_complete`: `false`
- `signal_lineage_record`: `{}`

## Behavior

- The worker reads the paper runtime bundle once per invocation, then
  splits it into the seven per-stage records.
- Bundle freshness is computed from `generated_at_ms` (preferred) or
  `generated_at` (ISO `YYYY-MM-DDThh:mm:ssZ`).
  `warn_threshold_seconds=120`, `stale_threshold_seconds=600` by
  default (CLI-overridable).
- Fail-closed conditions (CLI exit code `2`):
  - no source file / public bundle missing →
    `MISSING_RUNTIME_EVIDENCE`
  - invalid JSON → `INVALID_PAYLOAD`
  - any per-stage record missing → `MISSING_CHAIN_RECORDS`
  - bundle age beyond `stale_threshold_seconds` →
    `STALE_RUNTIME_EVIDENCE`
  - any lineage id missing across stages → `CHAIN_INCONSISTENT`
  - signal_publisher.py contains a scaffold remnant →
    `PUBLISHER_REMNANT_DETECTED`
- The Symbol Universe contract is read from the V2 service every run;
  the public Symbol Universe payload is consulted when present.
- No exchange call. No Redis write. The worker source contains no
  Binance/ccxt/Redis import and no Redis writer call.

## Tests

`v2/backend/tests/integration/cli/test_v2_signal_lineage_worker.py`
covers:

1. full-chain capture (all seven stages present)
2. explainability invariant (missing field collapses to label)
3. fail-closed on missing chain record (parametrized over six stage
   drop variants + CLI exit code `2`)
4. fail-closed on stale chain bundle
5. no-placeholder remnants in signal_publisher.py
6. Symbol Universe contract present
7. gate-always-blocked invariant
8. worker source contains no exchange-mutation method names
9. worker source has no Binance/ccxt/Redis imports
10. required public payload fields present (status + on-disk)
11. chain id inconsistency detection
12. signal publisher build_signal_record falls back to
    `EVIDENCE_MISSING_LABEL` when inputs are empty
13. signal publisher self-check appears in payload
14. cross-stage `signal_id` mismatch fails closed
15. feature snapshot explanation cites `volume_last`
16. paper_online_runtime delegates lineage construction to
    `signal_publisher`

Validation result:

```text
24 passed
```

## Legacy baseline

See:

- `v2_signal_lineage_worker_LEGACY_BASELINE_ANALYSIS.md`
- `v2_signal_lineage_worker_legacy_behavior_mapping.json`
