# 128 Risk Gateway Recovery Classification

## Classification

Non-live MVP blocker in `RISK_GATEWAY_DEFAULT_DENY_MVP`.

Blocked task:
`128_risk_gateway_2gb_assembler_service_implementation`

The prior watchdog recovery was shallow: it observed that some outputs existed, but did not verify task required outputs, did not validate the implementation, and did not normalize 128 state.

## Required recovery

Codex must perform closed-loop recovery:

1. Inspect task definition required outputs.
2. Compare each required output against the filesystem.
3. Inspect stdout/stderr for recoverable BEGIN_FILE content.
4. Materialize or patch missing non-live V2 files only.
5. Run compile/tests.
6. Run secret and safety scans.
7. Produce PASS/FAIL evidence.
8. Normalize/supersede stale runtime state only after validation.
9. Commit/push.
10. Continue to Codex review.

## Safety

No legacy bot mutation.
No Redis writes/deletes.
No live service restart.
No exchange action.
No deployment/live trading.

128_RISK_GATEWAY_RECOVERY_CLASSIFIED
