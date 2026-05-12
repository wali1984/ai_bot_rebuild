# Legacy Trainer Restart Runtime Capture and V2 Parity Sync Report

Generated: 2026-05-12T16:50:13Z

## Result

`LEGACY_TRAINER_RESTART_RUNTIME_CAPTURE_AND_V2_PARITY_SYNC_BLOCKED`

## What Was Verified

- Legacy trainer process observed: `True` PID `3980694`.
- Legacy trainer cwd: `/home/wali/Desktop/AI BOT`.
- Trainer GPU use observed: `True`.
- V2 paper runtime observed/current: `True`.
- Legacy monitor process observed: `False`.
- Legacy trader observed: `True`.
- Legacy output evidence: `LEGACY_TRAINER_OUTPUT_CURRENT`.
- Legacy publish risk: `PUBLISH_PATH_REQUIRES_OPERATOR_DECISION`.
- Exchange order after restart observed: `True`.
- Full parity claimed: `false`.

## Why Blocked

The capture succeeded, but safety review cannot pass because legacy Redis publish activity and `executed_signals` entries with exchange order IDs were observed after the trainer restart. This task did not cause those actions, but the website and readiness state must show the risk plainly.

## Next Required Action

Operator decision required: contain or disable the legacy publish/execution path, or explicitly approve a separate controlled legacy trainer runtime mode that cannot reach live exchange execution. V2 paper runtime remains current and paper-only.
