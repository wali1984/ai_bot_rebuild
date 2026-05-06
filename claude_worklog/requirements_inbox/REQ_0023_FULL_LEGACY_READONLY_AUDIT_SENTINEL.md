# Requirement 0023 - Full Legacy Read-Only Audit Sentinel

## Objective

The V2 rebuild must be based on the actual legacy bot, not assumptions.

Claude/Codex must continuously monitor and audit every relevant legacy component in read-only mode and use that evidence to build V2.

## Hard rule

No V2 milestone may pass unless it includes:

- legacy_evidence_consulted
- legacy_behavior_mapped
- legacy_failure_addressed
- V2 proof/test added

## Legacy source of truth

Read-only evidence must include:

- `/home/wali/Desktop/AI BOT/scripts/start_all_services_production.sh`
- current running process list
- all ingestors
- feature pipeline
- trainer
- orchestrator
- trader
- portfolio monitors
- trainer monitors
- read-only Redis key/stream metadata
- logs/audit files
- config.py symbol behavior, key names only
- failure cases such as LAB hedge unwind / squeeze exposure

## Components that must be mapped

Ingestors and data path:
- live_binance.py
- live_kucoin.py
- live_coinank.py
- live_binance_liquidations.py
- liquidation_bridge.py
- liquidation_levels_engine.py
- realtime_price_provider.py
- live_coinank_global_aggregator.py
- ingest.live_coinapi_wsds
- ingest.live_coinapi_v1
- ohlcv_resampler_hotfix.py
- feature_pipeline.py
- live_technical_analysis.py

Trainer/orchestrator/trader:
- rl.hybrid_trainer
- rl.orchestrator_worker
- trading/trader.py
- trading/trader-asjad.py if present
- monitor_trainer_predictions.py
- monitor_trainer_prices.py
- monitor_portfolio_primary.py
- monitor_portfolio_asjad.py

## Redis policy

Redis audit is read-only only.

Allowed:
- key pattern inventory
- TYPE
- XLEN
- LLEN
- HLEN
- ZCARD
- SCARD
- STRLEN
- TTL
- XINFO STREAM metadata
- INFO metadata

Forbidden:
- XADD
- XDEL
- DEL
- SET
- HSET
- LPUSH/RPUSH
- FLUSHDB
- FLUSHALL
- any write/delete/mutation command

Do not dump secret values. Do not commit Redis values. Prefer key names/patterns/counts/types/lengths/freshness only.

## V2 build enforcement

The master planner must reject any task in these lanes unless legacy evidence is referenced:

- trainer prediction output
- orchestrator decision
- risk gateway
- paper execution ledger
- replay/backtest runner
- paper mode
- shadow readiness
- explainability UI

## Required audit artifacts

Maintain:

- `claude_worklog/legacy_readonly_audit/00_AUDIT_INDEX.md`
- `claude_worklog/legacy_readonly_audit/01_PROCESS_SNAPSHOT.md`
- `claude_worklog/legacy_readonly_audit/02_STARTUP_SCRIPT_MAP.md`
- `claude_worklog/legacy_readonly_audit/03_LEGACY_CODE_FUNCTION_INVENTORY.md`
- `claude_worklog/legacy_readonly_audit/04_SERVICE_DEPENDENCY_GRAPH.md`
- `claude_worklog/legacy_readonly_audit/05_REDIS_READONLY_KEY_STREAM_INVENTORY.md`
- `claude_worklog/legacy_readonly_audit/06_TRAINER_RUNTIME_EVIDENCE.md`
- `claude_worklog/legacy_readonly_audit/07_ORCHESTRATOR_TRADER_RUNTIME_EVIDENCE.md`
- `claude_worklog/legacy_readonly_audit/08_FAILURE_CASE_REGISTER.md`
- `claude_worklog/legacy_readonly_audit/09_V2_BUILD_IMPACT_MAP.md`
- `claude_worklog/legacy_readonly_audit/10_GO_NO_GO.md`

GO/NO-GO marker:
`LEGACY_READONLY_AUDIT_SENTINEL_READY`

## Codex role

Codex must review:
- whether legacy evidence was actually consulted
- whether V2 work maps real legacy behavior
- whether known legacy failures are addressed
- whether no legacy mutation occurred
- whether no Redis write occurred
- whether no live service restart/exchange action occurred

## Hard safety

Never:
- modify `/home/wali/Desktop/AI BOT`
- write/delete Redis
- restart live services
- place/cancel orders
- change leverage/margin
- enable live trading
- deploy
- expose secrets

REQ_FULL_LEGACY_READONLY_AUDIT_SENTINEL_READY
