# V2 Runtime Soak 1h Report - BLOCKED (in progress)

Generated: 2026-05-17T02:15:00Z
Git HEAD: 31a7fd70319f0d586c454b5ea2ea530ba9cb1541
GO/NO-GO: V2_RUNTIME_SOAK_BLOCKED

## Honest soak progress

- first_observed_utc: 2026-05-17T02:00:21Z
- last_observed_utc: 2026-05-17T02:12:30Z
- minutes_observed: 13.45
- observation_count: 6
- soak_15m_ready: false
- soak_1h_ready: false
- soak_6h_ready: false

1h target requires minutes_observed >= 60. Current value is 13.45.
The packet emits BLOCKED honestly rather than fabricating the
milestone.

## Runtime health (all green)

- 10/10 required V2 processes running
- v2:* total = 30 across 8 required namespaces (no namespace empty)
- all_v2_processes_uninterrupted across all 6 observations
- runtime guard classification: V2_PRODUCTION_REPLACEMENT_RUNTIME_READY_STABLE
- payload freshness refresher cycling at 60s; all live payloads
  fresh under 180s
- soak observer cycling at 300s; comparator cycling at 300s

## V2 vs legacy comparison snapshot

Per-symbol comparison from production_equivalence_comparison.json:

| Symbol | Match | Notes |
| --- | --- | --- |
| BTCUSDT | false | action_mismatch: legacy=close_short_open_long, v2=hold |
| ETHUSDT | true | match |
| SOLUSDT | false | action_mismatch: legacy=open_short, v2=hold |

Both mismatches are action_mismatch with v2=hold. Root cause: V2
native CPU policy runs from DETERMINISTIC_INIT weights (operator-
approved checkpoint not loaded). The strict P0.2F gate is paper-
only, so V2 "hold" is the safe default when the trained signal is
not loaded.

Remediation task already known: CHECKPOINT_WEIGHT_BLOB_OPERATOR_REQUIRED.
No new remediation task created. The mismatch is not a runtime
failure; it is a known model-state limitation.

## Legacy still owns production

- 10 legacy processes still running (live_binance, live_binance_liquidations,
  live_coinank, live_kucoin, live_coinapi_v1, live_coinapi_wsds,
  feature_pipeline, rl.hybrid_trainer, rl.orchestrator_worker,
  monitor_portfolio_primary).
- Legacy production Redis namespaces remain populated.
- Legacy was NOT stopped by this packet.

## Safety scans

- old Redis writes attempted by V2 loops: 0
- exchange mutation attempts: 0
- live approval token created: 0
- Redis trim approval created: 0
- live_gate: blocked_human_only
- live_symbols: []

## Hard constraints upheld

- AI BOT (legacy directory) NOT modified.
- Legacy processes NOT stopped.
- Every V2 write guarded with `key.startswith("v2:")` in writers.
- 0 exchange orders placed, cancelled, or modified.
- Leverage and margin unchanged.
- No live, canary, Redis-trim, or paper-only-acceptance approvals.

## Next required action

Wait for the soak observer to accumulate >= 60 minutes of
uninterrupted observations. ETA: ~2026-05-17T03:00:21Z (60 minutes
after first_observed_utc) under the assumption no V2 loop dies.
When `soak_1h_ready` flips to true AND `v2_namespaces_never_empty`
stays true AND `all_v2_processes_uninterrupted` stays true, the
next packet may emit V2_RUNTIME_SOAK_1H_READY.

The runtime guard, comparator, soak observer, freshness refresher,
and 5 chain loops continue to run autonomously on their cycles. No
silent waiting; every observation updates the public payload.

## Decision

V2_RUNTIME_SOAK_BLOCKED. Soak window in progress; 1h target not
yet met. Live and shutdown remain blocked.
