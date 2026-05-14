# claude_backfill_v2_feature_snapshot_builder_full_closure_baseline_analysis — REPORT

**Task ID:** `claude_backfill_v2_feature_snapshot_builder_full_closure_baseline_analysis`
**Branch:** `master`
**HEAD at start:** `c8a392ab Resolve shutdown readiness risk gateway remediation dispatch`
**Run timestamp (UTC):** 2026-05-14
**Author of evidence:** Claude (single bounded task)
**Live gate:** `blocked_human_only` (unchanged; this task does not touch live)
**Live symbols:** `[]`
**Final approval token:** `absent`
**Trim approval token:** `absent`

---

## 1. Scope and read/write discipline

This task **backfills** the full-closure `LEGACY_BASELINE_ANALYSIS.md` and `legacy_behavior_mapping.json` for the `v2_feature_snapshot_builder` worker. The worker source itself
(`v2/backend/app/cli/v2_feature_snapshot_builder.py`) and its test suite
(`v2/backend/tests/integration/cli/test_v2_feature_snapshot_builder.py`) are
**green** (9 / 9 passing as recorded in
`claude_worklog/final_readiness/emergency_v2_runtime_migration/latest/workers/v2_feature_snapshot_builder_report.md`)
and were not modified by this task. The task scope is *evidence backfill only*; per instructions, V2 code is not changed unless a real parity bug is exposed, and no such bug is exposed by this analysis.

Reads:
- `legacy_reference/rl/unified_feature_builder.py` (frozen reference)
- `legacy_reference/rl/obs_schema.py` (frozen reference)
- `claude_worklog/final_readiness/legacy_rl_risk_trainer_trader_closure/latest/full_runtime_copied_source_manifest.json` (SHA256 source-of-truth)
- `v2/backend/app/cli/v2_feature_snapshot_builder.py`
- `v2/backend/app/services/feature_snapshots/service.py`
- `v2/backend/app/domain/features/{groups,models,freshness,validation,snapshot}.py`
- `v2/backend/tests/integration/cli/test_v2_feature_snapshot_builder.py`
- `claude_worklog/final_readiness/emergency_v2_runtime_migration/latest/workers/v2_feature_snapshot_builder_report.md`

Writes (this task):
- `claude_worklog/final_readiness/codex_shutdown_readiness_takeover/latest/claude_tasks/claude_backfill_v2_feature_snapshot_builder_full_closure_baseline_analysis/*` (REPORT.md, STATUS.json, GO_NO_GO.md, LEGACY_BASELINE_ANALYSIS.md, legacy_behavior_mapping.json)

Not written: no legacy files, no `.env`, no exchange state, no Redis, no approval tokens, no `live_symbols` change.

---

## 2. Legacy source-of-truth SHA256 citations (from `full_runtime_copied_source_manifest.json`)

| legacy_rel_path | v2_preserved_path | sha256 | size_bytes | status |
|---|---|---|---|---|
| `rl/unified_feature_builder.py` | `v2/legacy_preserved/full_runtime_closure/rl/unified_feature_builder.py` | `2af5c68d812c0a0a5db2e037204f0b2165d9084dea983d1737e09034e8c739a5` | 29925 | UNCHANGED |
| `rl/obs_schema.py` | `v2/legacy_preserved/full_runtime_closure/rl/obs_schema.py` | `9ec040fa1306ac28f4395aac103b104eb02644866ca8acec5577b155fd925f5f` | 17346 | UNCHANGED |

The two pyc compagnons (`rl/__pycache__/obs_schema.cpython-312.pyc` 20317 bytes, no SHA emitted because `SKIPPED_BINARY_OR_DISALLOWED_EXTENSION` per manifest line 443–447) are **not** evidence — they are skipped binary artifacts. Findings derive only from the cited `.py` SHAs.

`copied_baseline_manifest.json` (startup baseline) does **not** list the `rl/*` files — that manifest tracks the production startup baseline (`scripts/start_all_services_production.sh`, `ingest/live_*`, etc.) and therefore is **not relevant** to this task's legacy parity surface. Its existence is recorded here only to explain the absence of a citation, not because it contains baseline evidence for the feature-snapshot builder.

---

## 3. V2 worker — observed shape (the green code under analysis)

- Module: `v2/backend/app/cli/v2_feature_snapshot_builder.py` (302 lines)
- Service layer: `v2/backend/app/services/feature_snapshots/service.py` (82 lines)
- Domain layer:
  - `domain/features/groups.py` — `DEFAULT_FEATURE_GROUPS = [price (required), liquidity (required), liquidations (optional), technical (optional)]`
  - `domain/features/models.py` — frozen dataclasses (`FeatureSnapshot`, `FeatureGroup`, `FeatureFreshness`, `AttributionMetadata`)
  - `domain/features/freshness.py` — `assess_freshness`, `stale_feature_names`, `missing_feature_names`, `unused_feature_names`
  - `domain/features/validation.py` — `validate_trainer_input`, `is_trainer_ready`
- Output: three JSON files (public dashboard payload, local runtime payload, claude_worklog mirror) each containing `worker_id`, `last_run_ts`, `last_snapshot_id`, `last_snapshot_ts`, `feature_categories_present`, `stale_features`, `missing_features`, `trainer_readiness`, `source_payload_path`, `freshness_seconds`, `live_gate`, `current_gate_state`, and the full `snapshot` dict.

Behaviour summary:
- Categorical groups (`price`, `liquidity`, `liquidations`, `technical`), not torch tensors.
- `trainer_readiness ∈ {BLOCKED_MISSING_REQUIRED, DEGRADED_STALE_INPUTS, READY, NOT_READY}` — derived from `missing_features`, `stale_features`, and the library's `confidence_input_ready` boolean.
- Fail-closed contract: single-shot run returns rc=2 when `BLOCKED_MISSING_REQUIRED`.
- Live gate: hard-coded constant `LIVE_GATE_STATUS = "blocked_human_only"`; both `live_gate` and `current_gate_state` always emit this value (test 6 enforces).
- No `redis`, `binance.client`, `ccxt`, or `python-binance` import. Only `urllib.request` against Binance public REST (`/fapi/v1/ticker/price`, `/fapi/v1/klines`) — read-only, no auth header.
- No `create_order`, `cancel_order`, `futures_create_order`, `futures_change_leverage`, `futures_change_margin_type` substrings in source (test 7 enforces).

---

## 4. Legacy behaviour as observed in the cited SHAs

`rl/unified_feature_builder.py` (SHA `2af5c68d…e8c739a5`, 29925 bytes, 710 lines) is a torch-tensor builder:
- `class DataSource(Enum)` enumerates **8** sources: `BINANCE_KLINES`, `BINANCE_ORDERBOOK`, `CCXT_OHLCV`, `LIQUIDATIONS`, `TECHNICAL_ANALYSIS`, `TOKEN_METRICS`, `COINANK`, `PORTFOLIO_STATE`.
- `@dataclass FeatureDimensions` sums to `20+15+10+12+25+18+22+15 = 137` feature dims per (symbol, timeframe).
- `class UnifiedFeatureTensorBuilder` returns `UnifiedFeatureVector(features: torch.Tensor, source_mask: torch.Tensor, feature_age: Dict[str, float], quality_score: float)` — explicitly device-aware (`cuda` if available).
- `_build_feature_vector` concatenates per-source tensors in fixed order, filling absent sources with zero-tensors of the registered dim.
- Quality-score formula (lines 594–616): `0.7 * mean(exp(-age * decay_rate / max_age)) + 0.3 * source_mask.mean()`.
- Cache: in-memory `Dict[(symbol, timeframe), UnifiedFeatureVector]` with LRU prune at `cache_size=1000`.

`rl/obs_schema.py` (SHA `9ec040fa…fd925f5f`, 17346 bytes, 468 lines) is the PPO checkpoint-compatibility layer:
- `class ObsSchemaVersion(Enum) = {V1_LEGACY (1053), V2_ONCHAIN (1061), V3_ENHANCED (1911), UNKNOWN}`.
- `_build_schema_v3()` slices: `unified_features (1430) + portfolio_state (401) + onchain_btc (15, optional) + onchain_eth (15, optional) + position_context (50, optional) = 1911`.
- `class ObsSchemaManager` provides: schema selection (`select_schema`), checkpoint metadata read (`load_checkpoint_metadata`), SAFE_MODE activation/deactivation, protective-action allowlist (`is_protective_action`), action gating (`should_block_action`).
- Globals: `SCHEMA_REGISTRY`, `DIM_TO_SCHEMA`, `get_schema_manager()`, `get_active_schema()`, `is_safe_mode()`, `should_block_action(action)`.

These two legacy modules belong to the **trainer / observation** layer, not to a worker emitting a categorical readiness payload.

---

## 5. Behaviour mapping — legacy → V2

| Legacy concept (rl/unified_feature_builder.py & rl/obs_schema.py) | V2 equivalent | Coverage status |
|---|---|---|
| `DataSource` enum (8 sources) | `DEFAULT_FEATURE_GROUPS` (4 categorical groups) | **Intentional scope contraction.** The V2 worker reports group-presence and freshness; per-source tensorisation is a downstream trainer concern. |
| `FeatureDimensions` (137-dim concat) | (none) | **Out of scope by design.** Trainer-bridge (separate worker) is the correct owner of any tensor projection. |
| `UnifiedFeatureVector(features=Tensor, source_mask=Tensor, quality_score=float)` | `FeatureSnapshot(feature_values=Dict[str,float], feature_groups=List[FeatureGroup], freshness_by_source=Dict[str,FeatureFreshness], confidence_input_ready=bool)` | **Equivalent at the contract level**: presence/absence per source mapped to `feature_groups`; source-mask mapped to per-group `feature_names`; quality_score mapped to readiness state machine plus `freshness_seconds`. |
| `feature_age[source]` (seconds) | `freshness_by_source[source].age_ms` + `stale` boolean | **Direct equivalent**, semantics preserved (with a unit change s → ms and a `max_age_ms` threshold per source). |
| `quality_score = 0.7*age_decay + 0.3*availability` | `trainer_readiness` state machine + `confidence_input_ready` | **Categorical replacement** (preferred for the readiness gate; numeric scoring is a trainer-side concern). |
| LRU `feature_cache` (size 1000) | (none — V2 worker is stateless per single-shot) | **Intentional**: caching belongs to the snapshot store / repo layer; the CLI worker is a per-tick emitter. |
| `ObsSchemaVersion` (v1/v2/v3, 1053/1061/1911) | `TRAINER_INPUT_SCHEMA_VERSION = "trainer_features.v1"` constant | **Equivalent at the contract level** (single schema constant — versioning is the trainer-bridge worker's responsibility, not this worker's). |
| `ObsSchemaManager.select_schema(checkpoint, dim, force)` | (none in this worker) | **Out of scope by design** (trainer-bridge owns checkpoint compatibility). |
| SAFE_MODE / `should_block_action` | `LIVE_GATE_STATUS = "blocked_human_only"` constant + risk_gateway worker | **Equivalent safety posture**, enforced by a separate, dedicated worker (`v2_risk_gateway`). |

No behaviour drift is exposed by this mapping that would require modifying the green worker:

- The V2 worker's job is *snapshot emission and trainer-readiness classification*, not *tensor projection* and not *PPO checkpoint compatibility*. The legacy modules cover two adjacent-but-separate concerns. The V2 worker design intentionally splits those concerns across multiple workers (snapshot-builder vs trainer-bridge vs risk-gateway).
- All hard-constraint behaviours (no exchange mutation, no Redis writes, live-gate always blocked) are enforced by source-level constants and contract tests; they have **no legacy equivalent that would override them** (the legacy modules contain no exchange-mutation calls either — they are pure feature/observation code).

---

## 6. Dependency closure status

Imports in `v2/backend/app/cli/v2_feature_snapshot_builder.py`:

| Import | Target file | Resolved |
|---|---|---|
| `v2.backend.app.domain.features.groups.DEFAULT_FEATURE_GROUPS` | `v2/backend/app/domain/features/groups.py` | yes |
| `v2.backend.app.services.feature_snapshots.FeatureSnapshotService` | `v2/backend/app/services/feature_snapshots/__init__.py` → `service.py` | yes |

Transitive imports via `service.py`:

| Import | Target file | Resolved |
|---|---|---|
| `...domain.features.freshness.{assess_freshness, missing_feature_names, stale_feature_names, unused_feature_names}` | `v2/backend/app/domain/features/freshness.py` | yes |
| `...domain.features.groups.{group_features, required_feature_names}` | `v2/backend/app/domain/features/groups.py` | yes |
| `...domain.features.models.{AttributionMetadata, FeatureSnapshot}` | `v2/backend/app/domain/features/models.py` | yes |
| `...domain.features.validation.is_trainer_ready` | `v2/backend/app/domain/features/validation.py` | yes |

Stdlib only: `argparse`, `datetime`, `json`, `sys`, `time`, `urllib.{error,parse,request}`, `dataclasses`, `pathlib`, `typing`, `hashlib`. No third-party runtime dependencies. No torch, no redis, no ccxt, no binance.

**Dependency closure: FULLY_RESOLVED.**

---

## 7. Tests / runtime evidence

Existing report
`claude_worklog/final_readiness/emergency_v2_runtime_migration/latest/workers/v2_feature_snapshot_builder_report.md`
records **9 / 9 passing** on
`v2/backend/tests/integration/cli/test_v2_feature_snapshot_builder.py`
(MIGRATED_AND_RUNNABLE as of 2026-05-13). The test file (201 lines, this turn re-read) covers exactly the eight task-descriptor contracts plus two helper checks:

1. `test_build_snapshot_produces_expected_categories` — required fields + price/liquidity present
2. `test_stale_input_marked_explicitly_as_stale` — `DEGRADED_STALE_INPUTS` or `BLOCKED_MISSING_REQUIRED`
3. `test_fail_closed_when_required_feature_category_missing` — exit code 2 + `BLOCKED_MISSING_REQUIRED`
4. `test_snapshot_id_is_deterministic_given_inputs` — two runs same id
5. `test_trainer_readiness_signal_propagates_correctly` — `READY` when no missing/stale
6. `test_live_gate_is_always_blocked_human_only` — `live_gate == current_gate_state == "blocked_human_only"`
7. `test_worker_module_has_no_real_exchange_codepath` — forbidden substrings absent
8. `test_freshness_seconds_is_non_negative_for_present_ts` — ≥ 0 for valid ts
9. `test_freshness_seconds_returns_minus_one_for_garbage` — −1 for malformed ts

**Classification:** this backfill task introduces no V2 code change and therefore does not require a re-run of the suite as a new evidence artefact; the existing green-9 / 9 record is the binding evidence. The test file itself was re-read this turn to confirm it still covers the eight contract surfaces above (no test was deleted or skipped). If a new test invocation is required by Codex, it can be executed with `.venv/bin/pytest v2/backend/tests/integration/cli/test_v2_feature_snapshot_builder.py` against the same green code — no environment-blocked condition is asserted.

---

## 8. Public-payload impact

This backfill task **emits no runtime-facing payload change**:
- It does not modify the worker source, the service module, or any domain dataclass.
- It does not modify
  `v2/frontend/public/operator_runtime/v2_feature_snapshot_builder/latest/v2_feature_snapshot_builder_status.json`.
- It does not modify
  `v2/runtime/v2_feature_snapshot_builder/latest/v2_feature_snapshot_builder_status.json`.
- It does not modify
  `claude_worklog/final_readiness/emergency_v2_runtime_migration/latest/workers/v2_feature_snapshot_builder_status.json`.

The only new artefacts are in
`claude_worklog/final_readiness/codex_shutdown_readiness_takeover/latest/claude_tasks/claude_backfill_v2_feature_snapshot_builder_full_closure_baseline_analysis/`
which is a worklog directory, not a runtime/public payload. Operator dashboard payloads are unaffected.

---

## 9. Live posture (unchanged by this task)

- `live_gate=blocked_human_only` everywhere.
- `live_symbols=[]`.
- `final_approval_token=absent`.
- `trim_approval_token=absent`.
- Legacy: `frozen_reference_only` — no read-only or read-write file touched outside the worklog sub-tree above.

---

## 10. GO / NO-GO

Outcome: **READY** — backfill emitted, dependency closure verified, no parity bug exposed, no V2 code modified, live posture unchanged.

Token (mirror): `CLAUDE_BACKFILL_V2_FEATURE_SNAPSHOT_BUILDER_FULL_CLOSURE_BASELINE_ANALYSIS_BLOCKED_OR_READY` (the harness keeps a single canonical token regardless of READY vs BLOCKED so Codex can grep for one string; the body of this report supplies the actual READY classification).

Codex review surface for this task:
- This REPORT.md
- The companion LEGACY_BASELINE_ANALYSIS.md
- The companion legacy_behavior_mapping.json
- STATUS.json + GO_NO_GO.md
- The SHA citations against `full_runtime_copied_source_manifest.json`.

Nothing in this task escalates risk, mutates legacy state, or activates any live path.
