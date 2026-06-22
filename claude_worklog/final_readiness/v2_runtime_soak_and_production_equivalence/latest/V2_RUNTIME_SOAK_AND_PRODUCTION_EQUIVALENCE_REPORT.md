# V2 Runtime Soak + Production Equivalence - Soaking

Generated: 2026-05-17T02:10:00Z
Git HEAD: 31a7fd70319f0d586c454b5ea2ea530ba9cb1541
GO/NO-GO: V2_RUNTIME_SOAK_AND_PRODUCTION_EQUIVALENCE_READY_SOAKING

## What changed (not an audit; runtime work)

Three concrete things shipped:

1. v2/backend/app/cli/v2_production_equivalence_comparator.py
   - Reads V2 + legacy Redis side by side (tolerant of legacy hash,
     list, and stream key types).
   - Emits per-symbol comparison: legacy_latest_prediction,
     v2_latest_prediction, legacy/v2 confidence, legacy/v2 action,
     legacy/v2 feature_freshness_state, v2 paper_fill_allowed,
     v2 paper_fill_gate_block_reasons, and per-symbol notes.
   - Emits soak_observation.jsonl + soak_status.json with
     soak_15m_ready / soak_1h_ready / soak_6h_ready flags.
   - Outputs at both worklog and public paths.
2. v2/backend/scripts/run_v2_replacement_readiness_scoreboard.py
   - Reads soak + comparator + Redis + ps and produces the
     v2_replacement_readiness_scoreboard.json with the explicit
     fields requested in Phase 5.
3. v2/backend/app/cli/v2_production_payload_freshness_refresher.py
   - Extended to surface v2_soak_progress, v2_vs_legacy_compared_symbols,
     and v2_replacement_readiness_scoreboard_summary in the
     frontend_truth_payload.json.

Plus runtime stabilization items: systemd user unit for the new
comparator, hardened runtime guard that now requires the comparator
process, start/status/stop scripts updated.

## Three gates restated

Shutdown safety has three independent gates. All three must be open
before legacy shutdown can be considered:

| Gate | State |
| --- | --- |
| PAPER_ONLY_ACCEPTANCE_GATE | OPERATOR_ACCEPTANCE_FILE_ABSENT |
| PRODUCTION_EQUIVALENCE_GATE | SOAK_IN_PROGRESS (no closure yet) |
| LIVE_TRADING_GATE | BLOCKED_HUMAN_ONLY (intentional) |

This packet does NOT open any of them.

## Phase 1 - Runtime alive verification

`status_v2_production_replacement_runtime.sh` confirms 10 V2
processes running. `v2_production_replacement_runtime_guard.py
--once` reports `V2_PRODUCTION_REPLACEMENT_RUNTIME_READY_STABLE`.
The start script is idempotent ("already running" is logged for
re-invocations) and refuses to double-launch.

## Phase 2 - Soak evidence at the new path

soak_observation.jsonl appends one observation per cycle (5-min
default). soak_status.json carries:

- minutes_observed
- soak_15m_ready / soak_1h_ready / soak_6h_ready
- all_v2_processes_uninterrupted
- v2_namespaces_never_empty
- legacy_still_owns_production_observed
- safety invariants

Frontend payload updated every observation; no silent waiting.

## Phase 3 - V2 vs legacy production-equivalence comparator

Per-symbol comparison for BTCUSDT/ETHUSDT/SOLUSDT (default).
For each symbol the comparator records:

- legacy_latest_prediction (key + payload summary, type-tolerant)
- v2_latest_prediction (key + payload summary)
- legacy_confidence vs v2_confidence_calibrated
- legacy_action vs v2_selected_action
- legacy_feature_freshness vs v2_feature_freshness
- v2_paper_fill_allowed + block reasons
- match flag and per-symbol notes (action_mismatch, missing key,
  freshness_state_mismatch, v2_paper_fill_blocked)

No invented outcomes.

## Phase 4 - Production-equivalence blocker burndown

See production_equivalence_blocker_burndown.json. 8 blockers
classified across the explicit state categories
IMPLEMENTED_AND_TESTED / RUNTIME_STABLE_SOAKING /
OPERATOR_DECISION_REQUIRED / STILL_PRODUCTION_BLOCKER /
LIVE_ONLY_BLOCKER. None hidden, none auto-resolved.

## Phase 5 - V2 replacement readiness scoreboard

v2_replacement_readiness_scoreboard.json with the required fields:

- v2_runtime_running
- v2_soak_15m_ready / v2_soak_1h_ready / v2_soak_6h_ready
- v2_writes_v2_redis
- legacy_still_running
- legacy_still_writes_production_redis
- v2_vs_legacy_comparison_available
- v2_prediction_matches_legacy_or_reason
- paper_fill_gate_state
- edge_state
- shutdown_recommendation
- live_gate / live_symbols
- next_required_fix

## Phase 6 - Frontend truth

frontend_truth_payload.json now includes:

- v2_paper_shadow_runtime_running, legacy_still_owns_production_runtime,
  do_not_shut_down_legacy_yet, v2_writing_v2_namespace_redis_keys,
  live_trading_is_blocked
- v2_runtime_loops (per-loop process status + Redis key count)
- v2_soak_progress (minutes_observed + soak flags)
- v2_vs_legacy_compared_symbols
- v2_replacement_readiness_scoreboard_summary
- current_blocker_in_plain_english pointing at the right thing
  (soak stability + production-equivalence burndown)

## Live runtime evidence

- V2 processes running: 10 (5 chain loops + payload freshness
  refresher + runtime guard + comparator + soak observer + legacy
  comparator)
- Runtime guard: V2_PRODUCTION_REPLACEMENT_RUNTIME_READY_STABLE
- v2:* total = 30 across 8 required namespaces
- Legacy still running (10 production processes, ~3+ days uptime
  each)
- Legacy still writes production prediction:*, signals:*, kc:*,
  rl:*, heartbeat:*, binance:*

## Hard constraints upheld

- AI BOT (legacy directory) NOT modified.
- Legacy processes NOT stopped.
- Every V2 write guarded with key.startswith("v2:") in the writers.
- 0 exchange orders placed, cancelled, or modified.
- Leverage and margin unchanged.
- No live, canary, Redis-trim, or paper-only-acceptance approval
  files created by this packet.
- live_gate stays blocked_human_only; live_symbols stays [].

## What READY_SOAKING means and does NOT mean

READY_SOAKING means:
- V2 loops are persistent and fresh
- v2:* Redis keys exist across every required namespace
- per-symbol V2-vs-legacy comparison is running
- frontend truth is current
- no live approval, no shutdown approval

It does NOT mean:
- live-ready (live_gate stays blocked_human_only)
- shutdown-ready (legacy still owns production)
- production equivalence proven (soak must accumulate 15m / 1h / 6h)

## Decision

V2_RUNTIME_SOAK_AND_PRODUCTION_EQUIVALENCE_READY_SOAKING.

The soak window is in progress and the comparator is running. The
next milestones are soak_15m_ready, then soak_1h_ready, then
soak_6h_ready. The operator must still create the paper-only
acceptance file and Codex must re-pass before any shutdown
reconsideration.
