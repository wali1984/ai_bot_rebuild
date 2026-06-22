CLOSED_LOOP_TAKEOVER_CLAUDE_PRIORITY_MISSING_INGESTOR_SERVICE_20260531_CODEX_FAIL

BLOCKER: write_event_to_redis does not include Redis stream write success in its return/emit count, so consume_events/run_wss_session can report successful events_written even when _liquidations_events_stream publish fails; this drops liquidation events needed by the V2 liquidation_levels_engine.
