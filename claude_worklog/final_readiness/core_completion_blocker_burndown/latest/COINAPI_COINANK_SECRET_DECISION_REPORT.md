# Phase 3 - CoinAPI / CoinAnk Secret + Operator-Decision Closure

Generated: 2026-05-16T22:30:00Z
Git HEAD: 31a7fd70319f0d586c454b5ea2ea530ba9cb1541

## Method

Scanned the local secret vault `.local_secrets/legacy.env` for key
NAMES only (line-prefix match before `=`). No values were read,
recorded, or printed. Runtime presence is the OR of process env
and file presence.

## Result

- COINAPI_API_KEY: present
  -> coinapi_classification: AVAILABLE_FOR_READ_ONLY_DATA
- COINANK_API_KEY: present
  -> coinank_classification: AVAILABLE_FOR_READ_ONLY_DATA
- COINAPI_PRIMARY_EXCHANGE_ID: present
- ENABLE_COINAPI: present
- COINANK_ENABLED: present

raw_secret_values_recorded: false (never written; only env-name
presence flags emitted).

## What "AVAILABLE_FOR_READ_ONLY_DATA" means

The API key is present on this host's local vault. V2 may consume
it for paper/shadow read-only market-data calls only. It does NOT
authorize live trading, canary trading, legacy shutdown, exchange
mutation, leverage changes, margin changes, or Redis trim.

## Operator decisions still required

- live_coinank_global_aggregator: aggregator scope of CoinAnk
  global symbol universe remains OPERATOR_DECISION_REQUIRED_FOR_PAPER_ONLY.
- live_coinapi_wsds: paid WSDS streaming subscription remains
  OPERATOR_DECISION_REQUIRED_FOR_PAPER_ONLY.

These are intentionally separate from secret presence. Even with
the key present, the operator must accept the paid tier / global
universe scope before V2 spins up those ingestors.

## Public payload

- v2/frontend/public/core_completion_blocker_burndown/latest/coinapi_coinank_secret_decision_status.json
- claude_worklog/final_readiness/core_completion_blocker_burndown/latest/coinapi_coinank_secret_decision_status.json

## Safety posture

live_gate=blocked_human_only, live_symbols=[], approves_live=false,
approves_canary=false, approves_legacy_shutdown=false,
approves_redis_trim=false.
