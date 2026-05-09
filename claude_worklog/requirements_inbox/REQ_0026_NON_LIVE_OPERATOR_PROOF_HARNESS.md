# Requirement 0026 - Non-Live Operator Proof Harness

## Objective

Create an executable non-live proof harness that produces operator-inspectable
evidence for the V2 backtest, paper, and shadow MVP.

The system already has MVP markers and unit tests. The missing piece is a
deterministic command that produces concrete proof artifacts.

## Required Command

```bash
PYTHONPATH=. python3 -m v2.backend.app.cli.non_live_operational_proof --output-dir claude_worklog/final_readiness/non_live_operational_proof/latest
```

## Required Behavior

The harness must run entirely offline and non-live using local deterministic
fixtures.

It must not:

- write Redis
- read or write live Redis keys
- touch `/home/wali/Desktop/AI BOT`
- restart live services
- call live trading endpoints
- place or cancel orders
- change leverage or margin
- enable live trading
- deploy

## Required Proof Artifacts

The harness must emit:

- `replay_backtest_result.json`
- `replay_backtest_result.md`
- `paper_ledger_result.json`
- `paper_ledger_result.md`
- `shadow_comparison_result.json`
- `shadow_comparison_result.md`
- `risk_gateway_result.json`
- `risk_gateway_result.md`
- `decision_explainability_result.json`
- `decision_explainability_result.md`
- `aggregate_non_live_proof_rollup.md`
- `GO_NO_GO.md`

The `GO_NO_GO.md` file must contain exactly:

`NON_LIVE_OPERATOR_PROOF_HARNESS_READY`

## Required Proof Scenarios

At minimum, include deterministic fixture scenarios for:

1. safe long paper intent
2. stale data blocked by risk gateway
3. duplicate signal blocked
4. hedge-close residual exposure blocked
5. LAB-like short squeeze / hedge unwind failure case
6. paper ledger open, close, reduce, and block events
7. shadow comparison: legacy action vs V2 decision

## Required Fields

Proof artifacts must include:

- `feature_snapshot_id`
- `prediction_id`
- `decision_id`
- `risk_decision_id`
- `execution_intent_id`
- `paper_trade_id` where applicable
- `shadow_decision_id` where applicable
- symbol
- side or direction
- confidence
- risk decision
- block or allow reason
- paper PnL placeholder or result
- explanation payload
- stale, missing, and unused feature flags
- live gate status

## Required Tests

Add tests verifying:

- CLI runs successfully
- all required artifacts are emitted
- GO/NO-GO marker is correct
- no live, Redis, legacy, or exchange action occurs
- risk gateway blocks stale data
- LAB-like hedge unwind case is blocked or reduced
- paper ledger records non-live events
- shadow comparison emits legacy-vs-V2 difference

REQ_NON_LIVE_OPERATOR_PROOF_HARNESS_READY
