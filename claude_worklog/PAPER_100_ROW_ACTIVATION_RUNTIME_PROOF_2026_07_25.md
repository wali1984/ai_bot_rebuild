# 114-Row Cohort Provisional Activation — Runtime Proof (2026-07-25)

Goal: `PAPER_AUTONOMOUS_OPERATIONAL_AT_100_ROWS` using the existing 114 strict-admitted
rows. Live submission stays BLOCKED (human-only gate). No fabricated finality/lineage.

## Verified DONE (with raw evidence)

| Phase | Result | Raw evidence pointer |
|-------|--------|----------------------|
| 0 Importer stop | stopped by exact PID (no broad pkill) | logs preserved |
| 1 114-row identity audit | 114 rows, 55/14/45, 0 dup, 0 split-overlap, 0 finality-unproven, 0 missing cost/label, 0 future-time | `.local_models/paper_provisional/admitted_114_identity.json` |
| 2 Durable 100-row manifest | 80/10/10, 0 dup, 0 future-time; `feature_abi_sha256`, `source_manifest_id`, `source_append_receipt_sha256`, `source_high_watermark=60000` all populated from the real freeze | `.local_models/paper_provisional/provisional_100_row_manifest.json` (manifest_id `paper_provisional_100_row_manifest_c432006d0e838e45`) |
| 3 Provisional checkpoint | CUDA, optimizer_steps=120, finite_loss=true; paper_only / non-promotable / never-live / PROVISIONAL | `.local_models/paper_provisional/PAPER_PROVISIONAL_100_ROW_CHECKPOINT.{pt,meta.json}` |
| 4 Producer finality proof | producer redeployed @7447686f6f (active, NRestarts=0); direct capture 20/20 proven, deployed loop 8 proven — `LATEST_UNCLOSED_KLINE_EXCLUSION_UNPROVEN=0`; method `CLOSED_KLINE_FILTER_DECISION_TIME_BOUNDED_V1`; no credentials, no durable-file-archive write | `/tmp/.../scratchpad/phase4_deployed_result.json` |
| 5-6 Cohort isolation | commit `539fb83d04`; cohort breaker `ACTIVE_INSUFFICIENT_COHORT_SAMPLE` (governed_rows=0) published by the running loop while global stays `HALTED_PERFORMANCE` (governed_rows=23); 12 equality/isolation/resolver tests pass | `redis v2:paper:performance_circuit_breaker_status[:cohort]`; `test_paper_cohort_isolation.py` |
| 7 Exposure policy | `min_valid_notional = venue_min / microstructure_liquidity_multiplier`; hardcoded $10 removed; cap 100 | commit `7447686f6f`, `policy_v1.py` |
| 8 Paper loop deploy | immutable @539fb83d04, ActiveState=active, NRestarts=0, canonical_paper_writer_count=1, live_gate=blocked_human_only | `systemctl --user show ai-bot-v2-trade-management-paper-loop` |
| 9 Directional prediction | 5 directional (long) predictions from the checkpoint over fresh proven-finality snapshots, microstructure_action=REDUCE_SIZE (real sweep_risk/trust_score), fresh | `.local_models/paper_provisional/phase9_directional_predictions.json` |
| 13 Exact-path dry-run | EXECUTED: `submit_function_called=false`, `places_real_order=false`, `exchange_action_taken=false` | `run_pass3b` report — status `PASS3B_BLOCKED_BEFORE_REALISTIC_PREFLIGHT` (`INSUFFICIENT_AVAILABLE_BALANCE_FOR_MIN_ORDER`) |

## Honest limitations

- **Phase 3/9 checkpoint quality**: the 80-row MLP is overconfident (conf≈1.0) and long-biased
  (11 higher-timeframe features absent at inference). It is PROVISIONAL / non-promotable /
  never-live by design; it proves runtime *mechanics*, not economic edge.
- **Phase 13**: the submit guard is proven (no order ever placed), but the exact path is
  `BLOCKED_BEFORE_REALISTIC_PREFLIGHT` (no live balance). Per the directive this is **NOT**
  described as complete live readiness.

## Phase 10-12 — genuine blocker (not a code checkpoint)

The full autonomous lifecycle (prediction→orchestrator→risk→signal→intent→cohort-breaker→
allocation→fill→open→stop→reduce-only close→closed-trade→margin→reconciliation) does not
complete because the running paper loop sees **zero routable supply**:

- `paper_signals_seen=0`, `intents_built=0`
- `fresh_strategy_supply_rows=0`, exploration `NO_CURRENT_EXPLORATION_CANDIDATES`

Both intake paths are starved:
- **Strict path** (`_read_paper_signals`) requires the trainer native-policy signal
  `v2:trainer:hybrid_cuda:signals:paper:{sym}:{tf}` with a PIT-matching `prediction_id`. That
  lane is deliberately held (Codex `99-codex-repair-hold.conf`).
- **Exploration path** builds its inventory from `v2:prediction:{sym}:{tf}` keys via
  `v2_a_plus_candidate_inventory.build_inventory` — currently zero prediction keys.

### Concrete unlock (real engineering, not fabrication)
Serve `PAPER_PROVISIONAL_100_ROW_CHECKPOINT` through the trainer's genuine prediction-publication
path so it emits real `v2:prediction:{sym}:{tf}` records **with authentic lineage** (feature
publication receipts, evidence hashes, market-state integrity id, replay readback). Then
`build_inventory` → strategy supply → exploration candidate → the paper loop's full lifecycle,
governed by the fresh cohort breaker (already ACTIVE). Hand-writing prediction records to the
trusted stream is refused here: it would either be honestly rejected by the re-validation gates
or require fabricating trainer lineage (violates the no-manufactured-evidence rail).

## Readiness verdict (honest)
`operational_ready = false`, `paper_autonomous_operational = false`,
`full_autonomous_lifecycle_ready = false`, `live_submission_ready = false`.
Ready sub-states: checkpoint, runtime, producer-finality, cohort-isolation, directional-prediction,
dry-run submit-guard. Persisted to `v2:paper:provisional_100_row_status` and
`.local_models/paper_provisional/provisional_100_row_status.json`.

## Safety invariants held
Live BLOCKED (human-only); no exchange order/leverage/margin action; historical global breaker
stays HALTED for the 23-row losing cohort (never relabeled); single canonical paper writer; no
production durable-archive write; no fabricated finality/lineage; manifest+checkpoint persisted to
a durable project path (not /tmp).
