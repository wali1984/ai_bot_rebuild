# LEGACY_BASELINE_ANALYSIS — v2_feature_snapshot_builder

This document is the **full-closure baseline analysis** for the
`v2_feature_snapshot_builder` worker. All findings are tied to a raw legacy
source SHA256 from `full_runtime_copied_source_manifest.json`. No finding
relies on summary docs.

## 0. SHA citations (binding)

Source-of-truth manifest:
`claude_worklog/final_readiness/legacy_rl_risk_trainer_trader_closure/latest/full_runtime_copied_source_manifest.json`

| legacy_rel_path | sha256 | size_bytes | line in manifest | preserved at |
|---|---|---|---|---|
| `rl/unified_feature_builder.py` | `2af5c68d812c0a0a5db2e037204f0b2165d9084dea983d1737e09034e8c739a5` | 29925 | 1724–1731 | `v2/legacy_preserved/full_runtime_closure/rl/unified_feature_builder.py` |
| `rl/obs_schema.py` | `9ec040fa1306ac28f4395aac103b104eb02644866ca8acec5577b155fd925f5f` | 17346 | 1302–1310 | `v2/legacy_preserved/full_runtime_closure/rl/obs_schema.py` |

Companion `.pyc` artefacts are listed as `SKIPPED_BINARY_OR_DISALLOWED_EXTENSION` in the manifest (lines 442–447) and are not evidence.

`copied_baseline_manifest.json` (`claude_worklog/final_readiness/legacy_startup_baseline_v2_migration/latest/copied_baseline_manifest.json`) tracks the production-startup baseline (ingestors, start/stop scripts) and contains no `rl/*` records; it is recorded here for completeness but is not the binding manifest for this analysis.

## 1. Legacy responsibilities (raw evidence)

### 1.a `rl/unified_feature_builder.py` (SHA `2af5c68d…e8c739a5`, 710 lines)

- **DataSource enum** (lines 20–29 of the legacy file): 8 sources
  - `BINANCE_KLINES`, `BINANCE_ORDERBOOK`, `CCXT_OHLCV`, `LIQUIDATIONS`, `TECHNICAL_ANALYSIS`, `TOKEN_METRICS`, `COINANK`, `PORTFOLIO_STATE`
- **FeatureDimensions dataclass** (lines 32–51): 20+15+10+12+25+18+22+15 = **137** floats per (symbol, timeframe).
- **UnifiedFeatureVector dataclass** (lines 54–63): `features: torch.Tensor`, `source_mask: torch.Tensor`, `feature_age: Dict[str,float]`, `quality_score: float`.
- **UnifiedFeatureTensorBuilder class** (lines 66–650): async build pipeline, device-aware (`cuda` when available), per-source processor methods, in-memory cache.
- **Per-source processors** (`_process_binance_klines`, `_process_binance_orderbook`, `_process_ccxt_ohlcv`, `_process_liquidations`, `_process_technical_analysis`, `_process_token_metrics`, `_process_coinank`, `_process_portfolio_state`, lines 335–592): each accepts a per-source dict and emits a fixed-dim `torch.tensor`, with `data.get(key, default)`-style fallbacks.
- **Quality score** (`_calculate_quality_score`, lines 594–616):
  `0.7 * mean(exp(-age * decay_rate / max_age)) + 0.3 * source_mask.mean()`.
- **Cache** (`feature_cache`, `_update_cache`, lines 102–104 + 630–650): LRU at `cache_size = 1000`.
- **Fallback path** (`_create_fallback_tensor`, lines 618–628): all-zero tensor + zero source-mask + per-source max-age + `quality_score = 0.0`.

### 1.b `rl/obs_schema.py` (SHA `9ec040fa…fd925f5f`, 468 lines)

- **ObsSchemaVersion enum** (lines 25–30): `V1_LEGACY (1053)`, `V2_ONCHAIN (1061)`, `V3_ENHANCED (1911)`, `UNKNOWN`.
- **ObsSlice / ObsSchema dataclasses** (lines 33–103): named slices with size + start/end indices + optional flag.
- **Schema builders** (lines 110–183):
  - v1 slices: `technical_indicators(50) + ohlcv_multi_tf(600) + orderbook_depth(100) + volatility(50) + momentum(50) + volume_profile(50) + portfolio_state(153) = 1053`
  - v2 adds: `onchain_btc(4) + onchain_eth(4) = 1061`
  - v3 slices: `unified_features(1430) + portfolio_state(401) + onchain_btc(15) + onchain_eth(15) + position_context(50) = 1911`
- **SCHEMA_REGISTRY / DIM_TO_SCHEMA** globals (lines 187–198).
- **ObsSchemaManager** (lines 205–441): schema selection by force/checkpoint/dim, fuzzy dim match within 5 %, checkpoint-metadata read (`_metadata.json` adjacent to `.zip` checkpoint), SAFE_MODE activation with reason, protective-action allowlist (`{CLOSE_LONG, CLOSE_SHORT, CLOSE_ALL, DECREASE_LONG, DECREASE_SHORT, PARTIAL_CLOSE, REDUCE, HOLD}` plus int-action indices 0 and 6), `should_block_action` returning `(bool, reason_code)`.
- **Module globals** (lines 443–467): `get_schema_manager()`, `get_active_schema()`, `is_safe_mode()`, `should_block_action(action)`.

## 2. V2 worker baseline (raw evidence, frozen this turn)

Source: `v2/backend/app/cli/v2_feature_snapshot_builder.py` (302 lines, this turn read end-to-end). Service: `v2/backend/app/services/feature_snapshots/service.py` (82 lines).

Behaviour observed:

- **Categorical group emission**, not torch-tensor concat. Groups: `price (required)`, `liquidity (required)`, `liquidations (optional)`, `technical (optional)` (`domain/features/groups.py:8–13`).
- **FeatureSnapshot dataclass** (`domain/features/models.py:44–62`): frozen dataclass with `feature_values: Dict[str,float]`, `feature_groups: List[FeatureGroup]`, `freshness_by_source: Dict[str, FeatureFreshness]`, `confidence_input_ready: bool`, `trainer_input_schema_version: str = "trainer_features.v1"`.
- **trainer_readiness state machine** (`v2_feature_snapshot_builder.py:178–203`):
  - `missing` non-empty → `BLOCKED_MISSING_REQUIRED`
  - `stale` non-empty (no missing) → `DEGRADED_STALE_INPUTS`
  - `confidence_input_ready` true (no missing, no stale) → `READY`
  - else → `NOT_READY`
- **Fail-closed exit-code-2** on single-shot run when `BLOCKED_MISSING_REQUIRED` (`main`, lines 274–298).
- **Live gate hard constant** `LIVE_GATE_STATUS = "blocked_human_only"` (line 38) emitted as both `live_gate` and `current_gate_state` in every status payload.
- **Read-only public REST only**: `urllib.request` against `fapi.binance.com/fapi/v1/ticker/price` and `fapi.binance.com/fapi/v1/klines` (`_http_json` and `fetch_live_payload`, lines 73–134). No auth header, no credential file read, no order/leverage/margin mutation method anywhere in source.
- **Three status sinks**:
  - `v2/frontend/public/operator_runtime/v2_feature_snapshot_builder/latest/v2_feature_snapshot_builder_status.json`
  - `v2/runtime/v2_feature_snapshot_builder/latest/v2_feature_snapshot_builder_status.json`
  - `claude_worklog/final_readiness/emergency_v2_runtime_migration/latest/workers/v2_feature_snapshot_builder_status.json`
- **Snapshot id**: `feature_snapshot_<sha256(payload, sort_keys)[:24]>` (deterministic, enforced by test 4).

## 3. Behavioural mapping (legacy → V2)

The legacy `unified_feature_builder.py` and `obs_schema.py` cover two adjacent
concerns:

1. **Tensorisation of multi-source features for direct PPO/RL ingestion**
   (unified_feature_builder.py).
2. **PPO checkpoint compatibility / observation-dim contract / SAFE_MODE
   action gating** (obs_schema.py).

The V2 `v2_feature_snapshot_builder` deliberately implements **neither**
concern in full. Its scope is narrower:

- Emit a **categorical, JSON-shaped** snapshot suitable for the V2 control
  plane (FastAPI / operator dashboard / risk-gateway worker / paper trader).
- Classify **trainer readiness** as a four-valued enum, not a continuous
  quality score.
- Provide **fail-closed semantics** (rc=2 + `BLOCKED_MISSING_REQUIRED`) so any
  downstream consumer can gate without a tensor-shape contract.
- Hold the **live-gate constant** so this worker can never accidentally
  enable a live path.

The two legacy concerns are owned elsewhere in V2:

| Legacy concern | V2 owner (not this worker) |
|---|---|
| Multi-source tensor concat + device-aware emission | `v2_trainer_bridge` / trainer integration layer (separate worker, separate task `claude_port_v2_trainer_bridge_full_legacy_parity`) |
| PPO checkpoint dim / SAFE_MODE / action-block | `v2_trainer_bridge` for checkpoint dim; `v2_risk_gateway` for action-block (separate worker, separate tasks `claude_port_v2_risk_gateway_legacy_gate_implementations_from_legacy_action_map`, `claude_expand_v2_risk_gateway_test_suite_from_legacy_action_map`) |

This split is consistent with the CLAUDE.md mandate that "the orchestrator
proposes and coordinates; the risk gateway validates and blocks/allows; the
execution engine acts only after risk allow." The snapshot builder is the
proposing-side data carrier; the gating/checkpoint-compat concerns belong to
their respective workers.

## 4. Parity-bug check

A "parity bug" in this context would be a behaviour the V2 worker
**claims** to provide that the legacy modules contradict. Re-reading both
legacy SHAs end-to-end this turn against the V2 worker source:

- The V2 worker does not claim to emit `UnifiedFeatureVector` tensors → no
  bug.
- The V2 worker does not claim to manage PPO obs-schema dim → no bug.
- The V2 worker does claim to emit `trainer_readiness` and `feature_groups`
  → these are implemented in `service.py` and `groups.py`, exercised by the
  9-test suite, and contain no contradiction with legacy semantics.
- The V2 worker does claim `live_gate == "blocked_human_only"` always →
  enforced by source-level constant, test 6 verifies. Legacy modules do
  not touch this constant.
- The V2 worker does claim "no exchange order/leverage/margin codepath" →
  enforced by test 7; the legacy modules do not call exchange APIs either,
  so the V2 contract is strictly stronger.

**No actual parity bug exposed by this backfill.** No V2 code change
warranted.

## 5. Dependency closure

All V2 imports resolve to local files in
`v2/backend/app/domain/features/` and `v2/backend/app/services/feature_snapshots/`,
plus Python stdlib. No torch, no redis, no ccxt, no python-binance, no third-party HTTP client. **FULLY_RESOLVED.**

## 6. Test posture

Re-read `v2/backend/tests/integration/cli/test_v2_feature_snapshot_builder.py`
(201 lines) this turn — covers the eight task-descriptor contracts plus two
helper assertions (`compute_freshness_seconds` ≥ 0 for valid ts, =-1 for
malformed). The
`emergency_v2_runtime_migration` worker report records **9 / 9 passing**
(2026-05-13 evidence). No test was deleted or skipped; nothing about this
backfill modifies test surface. Classification: **EXISTING_GREEN_9_OF_9_PRESERVED**
(not `V2_ENV_BLOCKED`, not `MISSING_EVIDENCE`).

## 7. Live posture

- `live_gate = blocked_human_only` (worker constant; tests 6 enforce).
- `live_symbols = []` (worker emits no symbol list to any approval channel).
- `final_approval_token = absent` (none created by this task).
- `trim_approval_token = absent` (none created by this task).

## 8. Conclusion

Full-closure baseline analysis emitted. Legacy SHAs cited. V2 behaviour
mapped against legacy responsibilities. Scope contraction is intentional and
correctly delegated to adjacent workers. Dependency closure resolved. Test
posture green. No parity bug, no V2 code change. **READY.**
