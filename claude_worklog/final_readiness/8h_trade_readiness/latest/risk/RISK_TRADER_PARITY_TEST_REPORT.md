# 8h Risk/Trader Parity Test Report

Generated: `2026-05-15T21:39:00Z`

Status: `RISK_TRADER_PARITY_TESTS_BLOCKED_EXPLICIT_GAPS`

## Result

Claude child `1662211` produced no stdout, stderr, or required artifacts for nearly five minutes. Codex terminated only that V2 Claude child and ran the focused risk/trader parity test set directly.

Command:

```bash
PYTHONPATH="$PWD" .venv/bin/pytest v2/backend/tests/integration/cli/test_v2_risk_trader_action_parity_deny_paths.py v2/backend/tests/integration/cli/test_v2_risk_gateway_runtime_worker.py v2/backend/tests/unit/services/risk_legacy_gates
```

Result:

- `101 passed`
- `3 skipped`

The skipped tests are explicit parity gaps, not hidden passes:

- `fee_ratio_gate`: legacy executor-layer guard is not exposed as a V2 risk gateway service entry point.
- `churn_veto`: legacy lifecycle-layer veto is not exposed as a V2 risk gateway service entry point.
- `minimum_hold_time`: no V2 risk gateway service entry point; only paper-runtime minimum-hold field exists on paper-shadow paths.

## Decision

Risk gateway deny-path coverage is strong, but risk/trader parity is not complete while these three legacy protective behaviors remain explicit gaps.

This does not approve live, canary, or legacy shutdown.

Safety:

- live gate: `blocked_human_only`
- live symbols: `[]`
- exchange mutation reachable: `false`
- leverage/margin mutation reachable: `false`
- old Redis write: `false`
