# LEGACY_BASED_WORKER_PORTING_ENFORCEMENT — Final Report

## Why this patch exists

The first worker shipped through the autonomous porting flow, `v2_feature_snapshot_builder`, was an extraction of the existing `FeatureSnapshotService` library out of `paper_online_runtime`. That was acceptable for that worker because the library already existed in V2 — but the **legacy_reference comparison was not produced**, so the worker was not, strictly speaking, ported from the 10-month legacy codebase. Without enforcement, the same gap could repeat for every remaining worker.

This patch makes legacy-baseline analysis a **gate** — every future Claude worker task must produce two files **before** implementation, and every Codex review must fail when those files are missing or dishonest.

GO/NO-GO: **`LEGACY_BASED_WORKER_PORTING_ENFORCEMENT_PATCH_READY`**.

## What changed (in one paragraph)

(1) The orchestrator gained two new state classifications (`LEGACY_BASELINE_REQUIRED`, `CODEX_PASS_BUT_LEGACY_BACKFILL_REQUIRED`) and a new action kind (`dispatch_legacy_baseline_analysis`) — workers now sit in `LEGACY_BASELINE_REQUIRED` until both baseline files exist on disk. (2) All 17 `claude_port_v2_*` task descriptors and all 17 `codex_review_v2_*` task descriptors were patched in place by `patch_worker_task_descriptors_with_legacy_baseline.py` — every Claude worker task gained a `LEGACY-FIRST MANDATE` prompt preamble, new forbidden items, and new required-output-file rows; every Codex review gained baseline files as required inputs plus eight new fail conditions. (3) A backfill task (`claude_backfill_v2_feature_snapshot_builder_legacy_analysis`) is queued so the already-shipped feature snapshot worker gets its retroactive legacy mapping. (4) A canonical template (`LEGACY_BASELINE_ANALYSIS_TEMPLATE.md`) and JSON schema (`legacy_behavior_mapping_schema.json`) ship alongside.

## Files emitted this turn

| path | role |
|---|---|
| `claude_worklog/tools/v2_worker_porting_orchestrator.py` | **patched** — adds two new state classes + legacy-baseline file checks in `check_worker_completion`, new `dispatch_legacy_baseline_analysis` action in `select_next_action`, two new fields in `aggregate_state`/dashboard |
| `claude_worklog/tools/patch_worker_task_descriptors_with_legacy_baseline.py` | new — idempotent patch tool for the 34 worker descriptors |
| `claude_worklog/agent_supervisor/tasks/claude_port_v2_*.json` (17 files) | **patched** — `required_legacy_baseline_files`, `legacy_baseline_required: true`, new forbidden items, `LEGACY-FIRST MANDATE` prompt preamble |
| `claude_worklog/agent_supervisor/tasks/codex_review_v2_*.json` (17 files) | **patched** — baseline files added to `required_input_files`, eight new `fail_conditions`, `LEGACY-BASELINE GATE` prompt suffix |
| `claude_worklog/agent_supervisor/tasks/claude_backfill_v2_feature_snapshot_builder_legacy_analysis.json` | new — backfill task for the already-shipped worker |
| `claude_worklog/agent_supervisor/tasks/codex_review_v2_feature_snapshot_builder_legacy_backfill.json` | new — paired Codex review for the backfill |
| `claude_worklog/final_readiness/legacy_based_worker_porting_enforcement/latest/LEGACY_BASELINE_ANALYSIS_TEMPLATE.md` | new — template every Claude worker task must follow |
| `claude_worklog/final_readiness/legacy_based_worker_porting_enforcement/latest/legacy_behavior_mapping_schema.json` | new — JSON Schema for the structured mapping file |
| `claude_worklog/final_readiness/legacy_based_worker_porting_enforcement/latest/worker_legacy_mapping_requirements.json` | new — machine-readable summary of the contract |
| `claude_worklog/final_readiness/legacy_based_worker_porting_enforcement/latest/LEGACY_BASED_WORKER_PORTING_ENFORCEMENT_REPORT.md` | new — this file |
| `claude_worklog/final_readiness/legacy_based_worker_porting_enforcement/latest/GO_NO_GO.md` | new — single-line PATCH_READY marker |
| `claude_worklog/final_readiness/legacy_based_worker_porting_enforcement/latest/operator_dashboard_payload.json` | new |
| `v2/frontend/public/legacy_based_worker_porting_enforcement/latest/operator_dashboard_payload.json` | new — public dashboard mirror |

## Orchestrator behaviour after the patch (verified this turn)

The orchestrator's `--once` run reports:
- `current_worker = v2_risk_gateway_runtime_worker`
- `next_action.kind = dispatch_legacy_baseline_analysis` (changed from `dispatch_claude`)
- `legacy_baseline_required_workers` = **16** workers (everything except the already-shipped feature snapshot builder)
- `legacy_backfill_required_workers` = `["v2_feature_snapshot_builder"]` — the already-shipped worker is flagged as needing backfill but is **not** demoted from the completed list

So the immediate effect of this patch is: the supervisor will pick up `claude_port_v2_risk_gateway_runtime_worker` and the LEGACY-FIRST MANDATE preamble in that descriptor will force the sub-agent to read `legacy_reference/` and produce the two baseline files **before** writing any V2 implementation code.

## The specific interpretation per worker (operator-provided guidance, encoded)

| worker | baseline must include |
|---|---|
| `v2_feature_snapshot_builder` | (backfill) legacy feature-pipeline comparison: feature_pipeline.py, live_binance.py, live_coinank.py, technical-analysis modules |
| `v2_risk_gateway_runtime_worker` | legacy risk checks + V2 hard gates |
| `v2_paper_execution_worker` | legacy execution/accounting behavior; paper-only and fail-closed |
| `v2_execution_ledger_worker` | legacy attribution/dedupe lessons |
| `v2_account_position_monitor` | legacy account/position logic; read-only V2 evidence only |
| `v2_signal_lineage_worker` | legacy signal/orchestrator/trader lineage; fix missing attribution |
| `v2_market_ingestor` | legacy ingestor coverage — not just Binance klines |
| `v2_coinank_liquidation_bridge` | patched legacy CoinAnk Plan-3 contracts |
| `v2_trainer_bridge` | legacy trainer features/checkpoints/metrics — NOT replaced with simple momentum wrapper |
| (P1/P2 remaining) | same legacy-first discipline |

## Hard-constraint compliance (this patch)

- No legacy mutation: yes — every patched descriptor explicitly forbids mutating `/home/wali/Desktop/AI BOT` and treats legacy_reference as read-only.
- No old Redis writes: yes — every Claude worker descriptor lists `old_redis_write` and `ignoring_legacy_redis_or_config_or_stream_contracts_without_reason` under `forbidden`; legacy keys appear only as read-only references in the schema.
- No exchange action / leverage / margin codepath: yes — pre-existing `forbidden` items kept and new legacy-baseline items added without weakening any existing constraint.
- No final live approval token created: yes — orchestrator refuses to dispatch when the token is present; this patch did not create one.
- Live gate `blocked_human_only`: yes — every worker status payload contract still asserts it.

## Failure-detection guarantees (what Codex must now block)

For any worker, Codex review now FAILS if any of these is true:

1. `<worker>_LEGACY_BASELINE_ANALYSIS.md` missing
2. `<worker>_legacy_behavior_mapping.json` missing
3. Greenfield implementation without documented justification (when `legacy_source_paths` is empty)
4. Legacy features dropped silently (no row in `removed_or_deprecated_behavior`)
5. Legacy Redis / config / stream contracts ignored without reason
6. Behavior changed without explanation in mapping
7. Tests do not cover legacy-equivalent behavior named in the mapping
8. Worker claims migrated while only newly scaffolded

These are appended to whatever per-worker fail conditions already existed (e.g., the risk-gateway-runtime review still also fails on `live_gate_not_blocked_human_only_in_payload`, etc.).

## Immediate operator effect

After this patch lands and `agent_supervisor.py` is alive again, picking up `claude_port_v2_risk_gateway_runtime_worker` will:

1. Force the sub-agent to read legacy_reference's risk/trader/orchestrator code first
2. Write `v2_risk_gateway_runtime_worker_LEGACY_BASELINE_ANALYSIS.md` + `_legacy_behavior_mapping.json`
3. Then implement the worker, with the legacy mapping as the contract
4. Then trigger `codex_review_v2_risk_gateway_runtime_worker`, which will FAIL the review if the analysis is vague or drops legacy behavior

## Open follow-up (queued, not done in this turn)

- `claude_backfill_v2_feature_snapshot_builder_legacy_analysis` — backfill the feature snapshot worker's legacy mapping (orchestrator flags it as `CODEX_PASS_BUT_LEGACY_BACKFILL_REQUIRED`).
