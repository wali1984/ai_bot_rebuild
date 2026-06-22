# Codex 15M Runtime Status: V2 Production Replacement Runtime

Generated: `2026-06-22T00:20:44Z`

GO/NO-GO: `CODEX_PRODUCTION_REPLACEMENT_RUNTIME_GOVERNOR_BLOCKED`

## Decision

The governor is installed and reporting, but the production-equivalent V2 runtime is blocked.

This packet does not approve live, canary, exchange mutation, leverage/margin, legacy shutdown, or Redis trim.

## Current Runtime Facts

- Legacy production-like processes running: `1`
- Required V2 production-equivalent loops running: `7/7`
- Redis `v2:*` key count: `1023533`
- `live_gate`: `blocked_human_only`
- `live_symbols`: `[]`

## Frontend Status

- Legacy still owns production.
- V2 replacement runtime is running, but it is not cleared to replace legacy.
- Do not shut down legacy.

## Requested Command Checks

| Check | Command | Result | Count |
| --- | --- | --- | --- |
| `legacy_production` | `pgrep -af 'live_binance|live_coinank|live_kucoin|feature_pipeline|hybrid_trainer|orchestrator_worker'` | `matched=True` | `3` |
| `v2_replacement` | `pgrep -af 'v2_native_ingestors_live_loop|v2_feature_pipeline_native_loop|v2_rl_core_inference_loop|v2_orchestrator_arbitration_loop|v2_trade_management_paper_loop'` | `matched=True` | `5` |
| `redis_v2` | `redis-cli KEYS 'v2:*' | wc -l` | `returncode=0` | `1021408` |
| `redis_prediction` | `redis-cli KEYS 'prediction:*' | wc -l` | `returncode=0` | `1` |
| `redis_features` | `redis-cli KEYS 'features:*' | wc -l` | `returncode=0` | `5635` |
| `redis_signals` | `redis-cli KEYS 'signals:*' | wc -l` | `returncode=0` | `4` |

## Blockers

- `LEGACY_STILL_OWNS_PRODUCTION_RUNTIME`
- `LEGACY_PRODUCTION_REDIS_KEYS_STILL_ACTIVE`
- `PAYLOADS_CONTAIN_MOCK_STATIC_OR_FIXTURE_TERMS: v2_native_ingestors_live`
- `V2_SOURCE_STILL_SELF_DECLARES_MISSING_OR_NO_SHUTDOWN_APPROVAL`

## Required V2 Loops

| Loop | Running | Match count |
| --- | --- | --- |
| `v2_native_ingestors_live_loop` | `True` | `1` |
| `v2_feature_pipeline_native_loop` | `True` | `1` |
| `v2_rl_core_inference_loop` | `True` | `1` |
| `v2_orchestrator_arbitration_loop` | `True` | `1` |
| `v2_trade_management_paper_loop` | `True` | `1` |
| `v2_production_replacement_runtime_guard` | `True` | `1` |
| `legacy_v2_comparator` | `True` | `1` |

## Redis V2 Namespace

| Pattern | Count |
| --- | --- |
| `v2:*` | `1023533` |
| `v2:market:*` | `2694` |
| `v2:features:*` | `26076` |
| `v2:prediction:*` | `755` |
| `v2:orchestrator:*` | `3` |
| `v2:paper:*` | `442` |

## Remediation

Created/updated Claude remediation task: `claude_worklog/agent_supervisor/tasks/claude_v2_production_replacement_runtime_loop_implementation.json`
