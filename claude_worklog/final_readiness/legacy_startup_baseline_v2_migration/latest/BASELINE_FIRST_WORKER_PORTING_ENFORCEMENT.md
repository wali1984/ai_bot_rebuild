# BASELINE_FIRST_WORKER_PORTING_ENFORCEMENT — Phase F

This patch extends the prior legacy-baseline enforcement (commit `cf22a10`) with three changes specific to startup-script-anchored porting.

## What changed in `v2_worker_porting_orchestrator.py`

1. **`WORKER_SEQUENCE` updated** — three new baseline-anchored workers inserted at the front of P0 in the correct dependency order:
   - `v2_market_ingestor_from_legacy_baseline` (index 2)
   - `v2_coinank_and_liquidation_bridge_from_legacy_baseline` (index 3)
   - `v2_feature_pipeline_and_ta_worker_from_legacy_baseline` (index 4)
2. **Existing legacy-baseline gate (`LEGACY_BASELINE_REQUIRED`)** continues to apply: each new worker is classified `LEGACY_BASELINE_REQUIRED` until both baseline files exist on disk.
3. **Verified next_action** — orchestrator `--once` now returns `next_action.kind = dispatch_legacy_baseline_analysis` with `next_worker = v2_market_ingestor_from_legacy_baseline`.

## What changed in task descriptors

Three new `claude_port_v2_*_from_legacy_baseline.json` and three paired `codex_review_v2_*_from_legacy_baseline.json` descriptors were created. Each carries:

- `required_legacy_baseline_files` listing the two pre-implementation deliverables
- `legacy_baseline_required: true`
- `forbidden` items including `greenfield_without_legacy_baseline`, `dropping_legacy_behavior_silently`, `ignoring_legacy_redis_or_config_or_stream_contracts_without_reason`, `behavior_change_without_explanation`, **and the new** `skipping_sha256_citation_from_copied_baseline_manifest`
- `depends_on` listing the specific preserved files under `v2/legacy_preserved/startup_baseline/`
- prompt preamble with the **LEGACY-FIRST MANDATE — BASELINE-ANCHORED** instruction set

Each Codex review descriptor carries `fail_conditions` including:

- `sha256_not_cited_or_does_not_match_copied_baseline_manifest`
- `data_source_priority_does_not_match_startup_script_table`
- `v2_worker_writes_to_legacy_namespace_instead_of_v2_namespace`

## What the worker port must produce

Beyond the existing per-worker artifacts, baseline-anchored workers must produce:

1. `<worker_id>_LEGACY_BASELINE_ANALYSIS.md` citing SHA256 from `copied_baseline_manifest.json` for every preserved source it depends on
2. `<worker_id>_legacy_behavior_mapping.json` with structured baseline_sha256 list

If a worker discovers an uncovered helper module during closure analysis (e.g., `utils`, `services`, `telegram_alerts`), it must:

- Run `python3 -m v2.backend.app.cli.legacy_dependency_closure` to confirm the gap
- Either (a) copy the additional file from the legacy root by extending `copy_legacy_startup_baseline.py`'s `REQUIRED_FILES` list and re-running, or (b) classify the dependency `MISSING_IN_LEGACY_BASELINE` with a documented reason for replacement

## Codex aggregate behaviour

The existing aggregate `CODEX_EMERGENCY_MIGRATION_REVIEW.md` continues to gate on every per-worker `_CODEX_PASS`. The new aggregate `CODEX_LEGACY_STARTUP_BASELINE_REVIEW.md` (Phase I descriptor at [codex_review_legacy_startup_baseline_v2_migration.json](../../../agent_supervisor/tasks/codex_review_legacy_startup_baseline_v2_migration.json)) audits the baseline copy itself.

## Hard-constraint compliance for this phase

- No legacy mutation: yes — the orchestrator patch only added new sequence entries and did not modify legacy paths.
- No old Redis writes from V2: yes — `forbidden` array forbids it on every new descriptor.
- No exchange/leverage/margin codepath: yes — every new descriptor forbids it.
- No final approval token created: yes.
- No legacy venv installs: yes.
- Live gate remains `blocked_human_only` throughout.
