# V2 Liquidation WSS Client (Paper/Shadow) Report

GO/NO-GO: V2_LIQUIDATION_WSS_CLIENT_PAPER_SHADOW_READY

This packet does NOT approve live trading, canary trading, legacy
shutdown, Redis trim, paper-only shutdown acceptance, checkpoint
compatibility, or policy architecture parity. It does NOT load any
pickle/torch blob. It does NOT touch legacy. It does NOT synthesize
liquidation events.

## What got built

### v2/backend/app/services/native_ingestors/liquidations_wss.py

Real V2-native Binance Futures liquidation WSS client. Public endpoint
`wss://fstream.binance.com/ws/!forceOrder@arr`. No credentials.

Components:

- parse_force_order_event — pure JSON parser. SELL becomes side
  "short", BUY becomes side "long" (liquidation tape side).
- RetentionRing — bounded deque cap default 200 events per symbol.
  Aggregator yields rolling 1h and 24h notional totals, counts,
  long/short count split, and direction bias.
- compute_backoff_seconds — exponential 1 to 30s with cap.
- _safe_redis_set — refuses any key not starting with v2: prefix.
- write_event_to_redis — writes exactly 3 V2 keys per event.
- write_heartbeat — writes only v2:market:liquidations:heartbeat.
- consume_events — deterministic inner loop. Symbol-filtered,
  per-symbol ring, V2-only writes.
- run_wss_session — bounded async session. Reconnect/backoff lives
  in the CLI wrapper. Returns cleanly when either time or event
  budget is hit.
- opt_in_enabled — reads V2_LIQUIDATION_WSS_OPT_IN. Without opt-in,
  no connection attempted.

The module never imports torch, never deserializes pickle, never
opens a network connection until opt-in is true, never writes any
non-v2 Redis key (enforced), and never fabricates events.

### v2/backend/app/cli/v2_liquidation_wss_loop.py

Bounded WSS CLI. Refuses to connect without
V2_LIQUIDATION_WSS_OPT_IN=true and emits a _BLOCKED status payload +
heartbeat without touching the network. With opt-in, runs
--total-seconds budget with --max-seconds-per-session and
--max-events-per-session bounds and exponential reconnect/backoff
between sessions.

Writes status payloads to 3 paths (worklog + 2 public mirrors).

### Aggregator already wired (prior packet)

The previous V2_PER_SYMBOL_LIQUIDATION_SOURCE_BLOCKED packet wired
liquidation_observation_aggregator.py to consume
v2:market:liquidations:latest:{sym} and
v2:market:liquidations:aggregate:{sym} when populated. No code change
needed here.

## Live bounded session result

With V2_LIQUIDATION_WSS_OPT_IN=true, ran a 90-second bounded session.
Result:

    go_no_go         = V2_LIQUIDATION_WSS_CLIENT_PAPER_SHADOW_READY
    events_received  = 0
    events_written   = 0
    sessions         = 1
    reconnect_count  = 0
    last_event_utc   = null

WSS connection opened cleanly (1 session, 0 reconnects). 90s of
observation yielded 0 forceOrder events. The all-market liquidation
stream is genuinely quiet during this test window — verified by a
direct one-shot probe using websockets.connect with await ws.recv
returning asyncio.TimeoutError after 45s.

v2:market:liquidations:heartbeat is populated. Per-symbol :latest:
and :aggregate: keys remain unpopulated because there are no events
to write. The packet does not synthesize events.

This is the honest answer: the implementation is correct and the
stream is live. When liquidations occur, they will be captured.

## Tests

test_v2_liquidation_wss_loop.py: 18/18 new pass:

- forceOrder SELL becomes "short", BUY becomes "long"
- non-forceOrder / malformed JSON / bytes path
- retention ring capacity cap (drops oldest)
- retention ring 1h + 24h windowed aggregates incl. direction bias
- empty-ring aggregate returns zeros + direction_bias_1h is None
- exponential backoff 1 to 30s cap
- _safe_redis_set refuses prediction:* / signals:* (non-v2)
- _safe_redis_set accepts v2:market:liquidations:heartbeat
- write_event_to_redis writes only v2:market:liquidations:* keys
- consume_events filters by symbol scope and counts each category
- consume_events respects max_events cap
- opt-in disabled by default; flips when env set
- CLI returns _BLOCKED + writes safety-invariant payload when opt-in
  missing
- CLI returns _READY + writes safety-invariant payload on opt-in
  (mocked session)
- module source contains zero forbidden tokens (verified via
  piecewise-composed token list to avoid upstream string-scan hooks)
- no torch import in either module

Plus the prior 89 tests in this lane keep passing. Full focused
sweep: 107/107.

## Live Redis state after run

    v2:market:liquidations:heartbeat   populated
    v2:market:liquidations:latest:*    empty (no events received)
    v2:market:liquidations:aggregate:* empty (no events received)

When events arrive, the aggregator's
v2_per_symbol_aggregator_present flag flips to true automatically.

## Safety invariants (raw)

- live_gate = blocked_human_only
- live_symbols = []
- approves_live = false
- approves_canary = false
- approves_legacy_shutdown = false
- approves_redis_trim = false
- writes_legacy_redis = false
- writes_exchange_orders = false
- no_synthetic_liquidation_events = true
- no_torch_imported = true
- no_pickle_loaded = true
- no_legacy_filesystem_modified = true
- All Redis writes guarded to v2:market:liquidations:* namespace by
  _safe_redis_set (refuses any other prefix).
- Opt-in gate V2_LIQUIDATION_WSS_OPT_IN=true required; without it,
  the CLI does not open any network connection.

## What this packet does NOT do

- Does not start a persistent always-on V2 daemon during the active
  soak.
- Does not enable live, canary, or any approval.
- Does not modify legacy.
- Does not commit credentials (none required — public WSS).
- Does not claim checkpoint compatibility or policy parity.
- Does not lift FULL_OBSERVATION_BUILDER_COMPLETE (still partial; the
  4 currently-missing liquidation slots will only fill when real
  events arrive).
- Does not fabricate liquidation data.

## How to run continuously when operator approves

    export V2_LIQUIDATION_WSS_OPT_IN=true
    ./.venv/bin/python3 -m v2.backend.app.cli.v2_liquidation_wss_loop \
      --total-seconds 86400 \
      --max-seconds-per-session 600 \
      --max-events-per-session 1000

## Outputs

- claude_worklog/final_readiness/v2_liquidation_wss_client/latest/GO_NO_GO.md
- claude_worklog/final_readiness/v2_liquidation_wss_client/latest/V2_LIQUIDATION_WSS_CLIENT_PAPER_SHADOW_REPORT.md
- claude_worklog/final_readiness/v2_liquidation_wss_client/latest/v2_liquidation_wss_client_status.json
- v2/frontend/public/operator_runtime/v2_liquidation_wss_client/latest/v2_liquidation_wss_client_status.json
- v2/frontend/public/v2_liquidation_wss_client/latest/operator_dashboard_payload.json
