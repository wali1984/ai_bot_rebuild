# Legacy V2 Realtime Decision Observatory Report

Generated: `2026-05-15T10:34:28Z`

This observatory is read-only against legacy evidence. It does not approve live trading, canary trading, or legacy shutdown.

## Runtime Health

- legacy ingestion health: `STALE`
- legacy trainer health: `RUNNING_READONLY_OBSERVED`
- legacy signal health: `STALE`
- V2 decision quality: `EDGE_PENDING_INSUFFICIENT_SAMPLE`
- legacy-vs-V2 agreement: `LEGACY_SIGNAL_MISSING_V2_PRESENT`
- after-cost correctness: `PENDING_OUTCOME`
- no-trade correctness: `PENDING_OUTCOME`
- paper/shadow outcome: `OUTCOME_PENDING_SOURCE_LIMITED`

## Safety

- live_gate: `blocked_human_only`
- live_symbols: `[]`
- old Redis write status: `ABSENT`
- exchange action status: `ABSENT`
- approval token status: `ABSENT`

## Current Decision

- shutdown recommendation: `BLOCK_LEGACY_SHUTDOWN_PARITY_INCOMPLETE`
- GO/NO-GO: `CODEX_LEGACY_V2_REALTIME_DECISION_OBSERVATORY_READY`

## Recommendations

- recommendations generated: `2`
- Claude tasks dispatched: `[]`
- Codex reviews passed/failed: `{'passed': 0, 'failed': 0, 'pending': ['paper_edge_recovery']}`

Primary next task remains cost-aware paper trade selection and shadow outcome learning. Post-filter no-fill is not being called positive edge.
