# Subproject 4 — Orchestrator Arbitration — Legacy Baseline Analysis

**Subproject id:** `4_orchestrator_arbitration`
**Migration contract:** `claude_worklog/final_readiness/permanent_migration_runtime/latest/migration_completion_contract.json`
**Generated UTC:** 2026-05-15
**Live gate:** `blocked_human_only`
**Live symbols:** `[]`
**Approves live:** `false`

## 1. Legacy files (read-only, preserved)

| Legacy path (preserved) | SHA256 | Size (bytes) | Lines |
|---|---|---|---|
| `v2/legacy_preserved/full_runtime_closure/rl/orchestrator_worker.py` | `a7ff83f992c6b0add14e4563241080cce431906642c0de6aa778d3fb9eb217c6` | 522,512 | 10,523 |
| `v2/legacy_preserved/full_runtime_closure/rl/proposal_bus.py` | `e6c7657b7b70d32773792005274d9d1bb08df8bce45c95c86e67e1fc61f0934d` | 2,012 | 70 |
| `v2/legacy_preserved/full_runtime_closure/rl/tradeplan_orchestrator.py` | `1e4ad19faed9dc3498f15401dc1065f1e1eedb400a662fc7272bed7df12fa4d0` | 64,956 | 1,427 |
| `v2/legacy_preserved/full_runtime_closure/rl/intent_engine.py` | `7d8d474237f08f3ab1f2775044f6e535c0a3934eb336c757b2cf4443f18b0975` | 6,648 | 164 |

SHA256 / size citations match
`claude_worklog/legacy_runtime_closure/full_runtime_copied_source_manifest.json`.

## 2. High-level legacy behavior

### `rl/orchestrator_worker.py` (10,523 lines)
The legacy "Orchestrator Worker" subscribes to a Redis proposal bus
(`wma:proposals`), arbitrates trader proposals across multiple accounts
(`ORCHESTRATOR_SIGNAL_STREAM_PRIMARY = signals:trading:primary`,
`ORCHESTRATOR_SIGNAL_STREAM_ASJAD = signals:trading:asjad`), and publishes
winners to the active execution streams. Key building blocks include:

- `_score_candidate_open_static(signal, policy)` — deterministic scoring of
  open candidates from `confidence`, `expected_edge_net`, `toxicity`,
  `liq_distance_pct`, and data-quality terms.
- `_score_keep_position_static(pos)` — deterministic scoring for
  keep-vs-close decisions on existing positions.
- Per-account flags (`ACCOUNT_PRIMARY_ENABLED`, `ACCOUNT_ASJAD_ENABLED`,
  `ACCOUNT_ASJAD_ALLOW_PUBLISH`) gate which streams receive arbitrated
  winners.
- Arbitration windows (`windows_arbitrated`) accumulate proposals across
  short time slices; CRITICAL proposals flush immediately but still
  arbitrate.

### `rl/proposal_bus.py` (70 lines)
A thin Redis Streams transport helper: `emit_proposal`, `drain_stream`,
`commit_last_id`. The bus does not decide anything; it only transports a
single payload format (`TRADE_PROPOSAL`).

### `rl/tradeplan_orchestrator.py` (1,427 lines)
Higher-level "TradePlan" orchestrator that computes utility scores using a
`MarketContext` (orderbook toxicity, liquidation risk, expected edge net,
protection-demand-score). Sorts scored proposals, drops vetoed entries,
and produces winner + proof structure. Far larger surface than the bare
`_score_candidate_open_static` shape.

### `rl/intent_engine.py` (164 lines)
Computes a per-symbol INTENT from higher timeframes (5m/15m/1h) driven
by PPO/MASA confidences. Returns `Intent(direction, strength,
effective_conf, agreement, reason)` with optional deterministic regime
prior + veto. Does NOT execute; intent is consumed elsewhere (e.g.
the 1m timing layer / orchestrator arbitration).

## 3. Behavior classification

### PORTED in this subproject (paper-only)

| Behavior | V2 module |
|---|---|
| Deterministic proposal scoring (confidence + expected-move + freshness) | `v2/backend/app/services/orchestrator_arbitration/proposal.py` |
| Stale-signal handling (score = `-inf` past `max_age_seconds`) | `v2/backend/app/services/orchestrator_arbitration/proposal.py` |
| `Proposal` dataclass with strict field validation | `v2/backend/app/services/orchestrator_arbitration/proposal.py` |
| `V2Signal` schema + `validate_signal` | `v2/backend/app/services/orchestrator_arbitration/signal_schema.py` |
| Deconflict across opposite sides (dominant-confidence wins, explicit `MISSING_EVIDENCE_CANNOT_COMPARE`) | `v2/backend/app/services/orchestrator_arbitration/deconflict.py` |
| Static stream routing labels `{primary, asjad, shadow}` (informational only) | `v2/backend/app/services/orchestrator_arbitration/stream_routing.py` |
| Top-per-`(symbol, side)` arbitration | `v2/backend/app/services/orchestrator_arbitration/service.py` |
| Public operator-runtime status payload + safety invariants | `v2/backend/app/services/orchestrator_arbitration/service.py` + `v2/backend/app/cli/v2_orchestrator_arbitration_worker.py` |

### PARTIALLY_PORTED

| Behavior | Why partial |
|---|---|
| Scoring weights | V2 keeps confidence + expected-move + freshness. Legacy adds toxicity, liq-distance, DQ-confidence, DQ-fallback, liquidity-soft-block. Those features are not yet wired into V2's snapshot bundles. |
| Multi-account routing | V2 stores stream labels (`primary`, `asjad`, `shadow`) but performs zero network publishing. |
| Intent engine | V2 does not yet implement the multi-timeframe PPO/MASA intent aggregator. |
| Tradeplan utility scoring | V2 does not yet implement the `MarketContext`-driven utility composition. |

### MISSING_IN_V2 (honest gaps)

- Full 10,523-line `rl/orchestrator_worker.py` arbitration runtime
  (per-account flag enforcement, CRITICAL flush, windows-arbitrated
  accounting, telemetry counters, dq_score-decomposition payloads).
- Live order routing.
- Live Redis `proposal_bus` integration (write/read of
  `wma:proposals`, `signals:trading:primary`, `signals:trading:asjad`).
- Hedge cage arbitration overlays.
- `IntentEngine` higher-timeframe PPO/MASA consensus with regime priors.
- `tradeplan_orchestrator.py` PDS-aware utility scoring.

These are all intentionally listed in
`subproject_4_orchestrator_arbitration_status.json:components_missing` so the
classification is `PARTIALLY_MIGRATED_PAPER_ONLY`, not `MIGRATED`.

## 4. Migration completion contract evidence

| Prerequisite | Evidence pointer |
|---|---|
| 1 — legacy_source_paths_identified | `legacy_behavior_mapping.json` |
| 2 — sha256_cited | This document + `legacy_behavior_mapping.json` |
| 5 — legacy_behavior_mapping_complete | `legacy_behavior_mapping.json` |
| 6 — v2_implementation_exists | `v2/backend/app/services/orchestrator_arbitration/`, `v2/backend/app/cli/v2_orchestrator_arbitration_worker.py` |
| 7 — tests_cover_legacy_equivalent_behavior | `v2/backend/tests/integration/cli/test_v2_orchestrator_arbitration_worker.py` (21 pass) |
| 8 — public_runtime_payload_exists | `v2/frontend/public/operator_runtime/v2_orchestrator_arbitration/latest/v2_orchestrator_arbitration_status.json` |
| 10 — no_old_redis_writes | No Redis client imported (verified by test_no_forbidden_imports_in_source) |
| 11 — no_exchange_mutation | No exchange SDK imported (verified by test_no_forbidden_imports_in_source) |
| 12 — live_gate_remains_blocked_human_only | Service hard-codes `LIVE_GATE_STATUS = "blocked_human_only"` |
| 13 — live_symbols_remains_empty | Service hard-codes `live_symbols=[]` in payload |

Prerequisites 3, 4, 9 are out of scope for this subproject (they are the
shared dependency closure, config parity, and codex review steps owned by
the parent migration).
