# Codex Review: V2 Liquidation WSS Client Paper/Shadow

Generated: `2026-05-17T23:47:02Z`

GO/NO-GO: `V2_LIQUIDATION_WSS_CLIENT_CODEX_PASS_PAPER_SHADOW`

## Decision

Codex passes the V2 liquidation WSS client at paper/shadow scope. The client is V2-only, public-data-only, opt-in gated, bounded, and writes only V2 liquidation namespace keys. It does not approve live trading, canary trading, exchange mutation, leverage/margin changes, Redis trim, approval creation, checkpoint compatibility, policy architecture parity, production equivalence, or legacy shutdown.

## WSS Source And Opt-In Gate

Reviewed source:

- `v2/backend/app/services/native_ingestors/liquidations_wss.py`
- `v2/backend/app/cli/v2_liquidation_wss_loop.py`
- `v2/backend/tests/integration/cli/test_v2_liquidation_wss_loop.py`

The only real network endpoint in the reviewed implementation is:

- `wss://fstream.binance.com/ws/!forceOrder@arr`

This is the public Binance Futures force-order stream. No API key or credential is used.

The client is gated by `V2_LIQUIDATION_WSS_OPT_IN=true`:

- Without opt-in, Codex verified the CLI returns `V2_LIQUIDATION_WSS_CLIENT_PAPER_SHADOW_BLOCKED` and does not connect.
- With opt-in, Codex ran a bounded paper/shadow session: `--total-seconds 3 --max-seconds-per-session 2 --max-events-per-session 1`.
- Result: `V2_LIQUIDATION_WSS_CLIENT_PAPER_SHADOW_READY`, `sessions=1`, `reconnect_count=0`, `events_received=0`, `events_written=0`, `last_event_utc=null`.

The empty event window is reported honestly. No liquidation events were synthesized.

## Bounds And Retention

Codex verified:

- session runtime is bounded by `total_seconds` and `max_seconds_per_session`;
- event intake is bounded by `max_events_per_session`;
- reconnect backoff is exponential with a `30s` cap;
- `RetentionRing` is bounded, default capacity `200` events per symbol;
- aggregate windows are rolling 1h and 24h windows;
- parser maps Binance `forceOrder` events only and rejects malformed/non-forceOrder payloads.

## Redis Contract

Reviewed writes are guarded by `_safe_redis_set`, which refuses non-`v2:` keys.

Allowed WSS writes are:

- `v2:market:liquidations:latest:{symbol}`
- `v2:market:liquidations:aggregate:{symbol}`
- `v2:market:liquidations:{symbol}`
- `v2:market:liquidations:heartbeat`

Current Redis state after the bounded session:

- `v2:market:liquidations:heartbeat`: populated
- `v2:market:liquidations:latest:*`: empty
- `v2:market:liquidations:aggregate:*`: empty
- per-symbol event keys: empty

Because the bounded window received no events, no per-symbol keys were written. This is correct and avoids fake data.

## Aggregator And Observation State

The full-observation liquidation aggregator remains honest:

- current liquidation subfamily remains `24/36`;
- `v2_liquidation_aggregator_per_symbol_source_available=false`;
- per-symbol slots fill only from real `v2:market:liquidations:latest:{symbol}` and `v2:market:liquidations:aggregate:{symbol}` keys;
- source-availability probe flags are not treated as market data.

Full observation state remains:

- `FULL_OBSERVATION_BUILDER_PARTIAL_MISSING_FIELDS`
- `checkpoint_compatibility_claimed=false`
- `policy_architecture_parity_claimed=false`

## Runtime And Safety

- Continuous remediation governor remains `CODEX_CONTINUOUS_REMEDIATION_REVIEW_GOVERNOR_READY`.
- 6h soak remains passed.
- V2/remediation processes remain running.
- No WSS process remained running after the bounded session.
- Legacy was not stopped or modified.

Safety state:

- `live_gate`: `blocked_human_only`
- `live_symbols`: `[]`
- `approves_live`: `false`
- `approves_canary`: `false`
- `approves_legacy_shutdown`: `false`
- `approves_redis_trim`: `false`

## Validation

- Focused tests: `36 passed`
  - `test_v2_liquidation_wss_loop.py`
  - `test_v2_liquidation_ingestor_loop.py`
  - `test_v2_liquidation_observation_aggregator.py`
- `py_compile`: PASS for WSS client, WSS CLI, source classifier, and liquidation observation aggregator.
- No-opt-in CLI path: PASS, returns BLOCKED with no socket.
- Short opt-in bounded session: PASS, one session, zero events, zero writes beyond heartbeat.
- Redis namespace scan: PASS, no per-symbol keys faked.
- Old Redis write scan: PASS; reviewed writes are guarded to `v2:` keys.
- Exchange mutation scan: PASS.
- Approval/live/shutdown drift scan: PASS.
- Raw secret scan: PASS.
- Torch/pickle load scan: PASS.
- `git diff --check`: PASS for reviewed files/artifacts.

## Non-Approval Items

- This does not start a persistent always-on WSS daemon.
- This does not approve live or canary trading.
- This does not approve legacy shutdown.
- This does not claim checkpoint compatibility or policy architecture parity.
- Full observation remains partial until real liquidation events and the remaining non-liquidation families are complete.

## Final Decision

`V2_LIQUIDATION_WSS_CLIENT_CODEX_PASS_PAPER_SHADOW`
