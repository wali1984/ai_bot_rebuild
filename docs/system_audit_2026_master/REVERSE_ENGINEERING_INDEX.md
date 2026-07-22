# AI Bot V2 reverse-engineering index

**Audit snapshot:** 2026-07-16 America/New_York

**Scope:** source, deployed processes, configuration surfaces, data contracts, temporal lineage, trainer/model, decision and paper/live execution, API, security, persistence, web/mobile clients, operations, recovery, and tests.

**Safety state observed:** non-live; real exchange mutation code exists but the deployed live path is disarmed. This document is not authorization to enable it.

This directory is the canonical documentation set for reconstructing the current system. It deliberately separates three kinds of truth:

1. **Versioned design** — what the tracked source and unit files say.
2. **Deployed reality** — what was installed and running on the audited workstation.
3. **Behavioral confidence** — what static analysis, tests, or live read-only evidence actually proves.

Do not collapse those categories. A source file is not proof that its service is installed; a running service is not proof that its source is committed; a Redis status payload is not proof that the operation it describes succeeded.

## Canonical human documents

| Document | Use |
|---|---|
| [AI_BOT_V2_FULL_REBUILD_MASTER_AUDIT_REPORT.md](AI_BOT_V2_FULL_REBUILD_MASTER_AUDIT_REPORT.md) | Current executive truth, subsystem status, risks, and NO-GO decision. |
| [AI_BOT_V2_MASTER_OPERATOR_MANUAL.md](AI_BOT_V2_MASTER_OPERATOR_MANUAL.md) | Safe observation, triage, recovery, restart constraints, and incident procedures. |
| [V2_SYSTEM_TECHNICAL_REFERENCE.md](../../v2/docs/V2_SYSTEM_TECHNICAL_REFERENCE.md) | Code-level architecture, contracts, entrypoints, state transitions, and implementation semantics. |
| [RUNTIME_PROCESS_AND_DEPLOYMENT.md](components/RUNTIME_PROCESS_AND_DEPLOYMENT.md) | Installed-versus-versioned process topology, systemd, namespaces, and startup behavior. |
| [DATA_TEMPORAL_LINEAGE_AND_FEATURES.md](components/DATA_TEMPORAL_LINEAGE_AND_FEATURES.md) | Provider inputs, timestamps, candle finality, feature assembly, masks, and point-in-time gaps. |
| [TRAINER_PPO_MASA_REPLAY_AND_CHECKPOINTS.md](components/TRAINER_PPO_MASA_REPLAY_AND_CHECKPOINTS.md) | The 477-feature/1,908-input model, training objectives, replay labels, holdout, publishing, and persistence. |
| [PROFILED_TRAINING_EXTERNAL_WITNESS_JOURNAL_V1.md](components/PROFILED_TRAINING_EXTERNAL_WITNESS_JOURNAL_V1.md) | Exact prepared-request, signed-receipt, signed-head, crash-recovery, SQLite, CAS, and no-authority journal contract. |
| [PROFILED_TRAINING_EXTERNAL_WITNESS_RUNTIME_V1.md](components/PROFILED_TRAINING_EXTERNAL_WITNESS_RUNTIME_V1.md) | Ordered pending recovery, durable-before-network dispatch, signed-head anchoring, restart, and zero-authority runtime contract. |
| [DECISION_RISK_PAPER_AND_LIVE_EXECUTION.md](components/DECISION_RISK_PAPER_AND_LIVE_EXECUTION.md) | Prediction-to-orchestrator-to-risk-to-paper flow, actual admission semantics, position lifecycle, and dormant live mutation paths. |
| [API_AUTH_STORAGE_WEB_AND_MOBILE.md](components/API_AUTH_STORAGE_WEB_AND_MOBILE.md) | FastAPI, middleware, authentication, Redis/SQLite/file state, React, SwiftUI, and exposure boundaries. |
| [CONFIG_KEYS_CONTRACTS_AND_CHANGE_IMPACT.md](components/CONFIG_KEYS_CONTRACTS_AND_CHANGE_IMPACT.md) | How to locate every config key, Redis pattern, payload field, route, caller, importer, and affected test. |
| [REBUILD_BLUEPRINT.md](REBUILD_BLUEPRINT.md) | Minimum reproducible specification and ordered reconstruction plan. |
| [CURRENT_FINDINGS_AND_RISK_REGISTER.md](CURRENT_FINDINGS_AND_RISK_REGISTER.md) | Evidence-linked defect and drift register. |
| [VALIDATION_AND_LIMITATIONS_2026-07-16.md](VALIDATION_AND_LIMITATIONS_2026-07-16.md) | Exact scoped test outcomes, snapshot integrity, secret/document checks, and deliberate safety boundaries. |
| [HISTORICAL_ARTIFACT_CLASSIFICATION.md](HISTORICAL_ARTIFACT_CLASSIFICATION.md) | Prevents legacy JSON/JSONL/inventory/graph fields from being consumed as current truth. |
| [COMMANDS_RUN.md](COMMANDS_RUN.md) | Exact audit/build/test tool ledger, including the complete verbatim local session records. |

The older component audits and root JSON/JSONL/inventory/graph artifacts in this directory are retained as historical pre-2026-07-16 evidence. Their current-sounding fields are not authority. Use `HISTORICAL_ARTIFACT_CLASSIFICATION.md` before consuming any legacy machine artifact. Where old artifacts conflict with this index or the 2026-07-16 documents, the later evidence wins. Values such as process counts, key counts, PnL, service state, and current Git commit are snapshots and must be refreshed before an operational decision.

## Exhaustive machine atlas

The `atlas/` directory is the function-level navigation layer. It was generated from Git-tracked worktree content at one recorded HEAD, and every tracked input was content-hash revalidated before publication; dirty tracked content is deliberately included. Secret-like files and values are excluded. The expanded JSON catalogs are deterministic local build artifacts and intentionally ignored by Git because they occupy hundreds of megabytes; regenerate them after source changes and validate them against the build manifest.

| Artifact | Cardinality/question |
|---|---|
| [FILE_MODULE_CATALOG.json](atlas/FILE_MODULE_CATALOG.json) | 9,272 tracked paths: hash, bytes, LOC, language, stratum, parse status. |
| [PYTHON_SYMBOL_CATALOG.json](atlas/PYTHON_SYMBOL_CATALOG.json) | 32,272 module/function/class/method records with location, signature, decorators, calls, fields, Redis/config/API and side effects. |
| [TYPESCRIPT_JAVASCRIPT_ATLAS.json](atlas/TYPESCRIPT_JAVASCRIPT_ATLAS.json) | 3,334 symbols plus imports, client routes, contracts, env keys, and calls. |
| [SWIFT_SYMBOL_CONTRACT_CATALOG.json](atlas/SWIFT_SYMBOL_CONTRACT_CATALOG.json) | 693 Swift declarations and client/data-contract references. |
| [PYTHON_IMPORT_GRAPH.json](atlas/PYTHON_IMPORT_GRAPH.json) | 25,389 import edges; 8,708 statically resolved to internal files. |
| [PYTHON_CALL_GRAPH.json](atlas/PYTHON_CALL_GRAPH.json) | 161,112 call references; 38,744 statically resolved to internal symbols. |
| [DATA_CONTRACTS.json](atlas/DATA_CONTRACTS.json) | 1,807 dataclass, TypedDict, Pydantic, TypeScript, and Swift contracts. |
| [DATA_CONTRACT_FIELD_REGISTRY.json](atlas/DATA_CONTRACT_FIELD_REGISTRY.json) | 39,538 field names with declaration/read/write sites. |
| [API_ROUTE_REGISTRY.json](atlas/API_ROUTE_REGISTRY.json) | 905 server definitions and client/reference sites; this is not the same as the current OpenAPI operation count. |
| [CONFIG_ENV_REGISTRY.json](atlas/CONFIG_ENV_REGISTRY.json) | 2,918 environment/static key names, safe defaults, and consumer sites. |
| [REDIS_KEY_USAGE_REGISTRY.json](atlas/REDIS_KEY_USAGE_REGISTRY.json) | 2,040 key patterns and literal/derived read/write sites. |
| [ENTRYPOINT_SERVICE_REGISTRY.json](atlas/ENTRYPOINT_SERVICE_REGISTRY.json) | Python mains, package scripts, shell entrypoints, Make targets, and systemd directives. |
| [EXCHANGE_MUTATION_REFERENCE_REGISTRY.json](atlas/EXCHANGE_MUTATION_REFERENCE_REGISTRY.json) | 37 order/cancel/leverage/margin/transfer-related source references requiring manual review. |
| [CHANGE_IMPACT_INDEX.json](atlas/CHANGE_IMPACT_INDEX.json) | Reverse importers, callers, shared fields, Redis consumers, route clients, tests, and side effects per module/symbol/surface. |
| [ATLAS_BUILD_MANIFEST.json](atlas/ATLAS_BUILD_MANIFEST.json) | Generation commit marker with source/analyzer provenance and size/SHA-256 for every staged artifact; validate catalogs against it. |
| [MODULE_BY_MODULE_INDEX.md](atlas/MODULE_BY_MODULE_INDEX.md) | Human-readable one-row-per-module navigation table. |

Static resolution is intentionally conservative. Dynamic imports, dependency injection, Redis keys assembled from runtime data, framework callbacks, reflection, shell indirection, provider-side behavior, installed drop-ins, and cloud-side routing can escape a static graph. An unresolved edge means “inspect manually,” not “no dependency.”

## Rebuild the atlas

From the repository root:

```bash
python3 tools/build_system_reverse_engineering_atlas.py \
  --repo-root . \
  --out-dir docs/system_audit_2026_master/atlas
```

Validation:

```bash
python3 -m py_compile \
  tools/build_system_reverse_engineering_atlas.py \
  tools/tests/test_build_system_reverse_engineering_atlas.py
node --check tools/build_typescript_reverse_engineering_atlas.cjs
node tools/build_typescript_reverse_engineering_atlas.cjs --self-test --repo-root .
.venv/bin/pytest -q tools/tests/test_build_system_reverse_engineering_atlas.py
```

The generator records Git HEAD/worktree state, revalidates the tracked path list and every tracked regular-file hash/symlink/nonregular input, cross-checks TypeScript module hashes, stages all outputs, and publishes `ATLAS_BUILD_MANIFEST.json` last. Do not call a snapshot consistent unless `snapshot_consistent` and `content_inputs_unchanged` are true, start/end HEAD match, the TypeScript mismatch list is empty, and artifact hashes match the manifest.

## Change-impact workflow

For any proposed change, use this order:

1. Identify the exact symbol, field, key, route, env key, unit, or file.
2. Read its source and invariants; do not infer behavior from its name.
3. Query `CHANGE_IMPACT_INDEX.json` for direct callers/importers and shared contracts.
4. Query the Redis, config, data-field, API, and entrypoint registries for indirect consumers.
5. Recursively inspect the dependents; static results are a lower bound.
6. Check installed systemd units and drop-ins because the workstation does not exactly match versioned deployment files.
7. Check point-in-time ordering for any data/training change: `event_time`, `ingested_at`, `available_at`, `generated_at`, `feature_cutoff`, `decision_time`, and `execution_time` are distinct.
8. Check finalized-candle, dirty-sample, position-transition, risk, and exchange-mutation invariants.
9. Run focused unit/integration tests against isolated state. Do not point broad integration suites at live paper-state files or production Redis.
10. Rebuild the atlas and inspect the diff before deployment.

## Audit boundary

This audit did not enable live trading, submit/cancel/modify an order, rotate credentials, change running services, alter Redis, repair failed timers, prune replay data, run destructive retention, or execute the full integration suite against live workspace state. Those omissions are deliberate safety boundaries, not shortcuts.
