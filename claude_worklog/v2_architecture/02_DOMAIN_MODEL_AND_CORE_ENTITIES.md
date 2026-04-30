# 02 Domain Model and Core Entities

## Core entities
- `exchange`
- `exchange_connector`
- `exchange_account`
- `exchange_symbol`
- `available_universe_symbol`
- `observed_universe_symbol`
- `training_universe_symbol`
- `trading_universe_symbol`
- `symbol_score`
- `symbol_override`
- `feature_snapshot`
- `feature_value`
- `prediction_event`
- `confidence_event`
- `signal_event`
- `orchestrator_decision`
- `risk_decision`
- `execution_intent`
- `trader_instance`
- `audit_event`
- `ai_action_change`
- `config_version`
- `monitor_snapshot`
- `evidence_packet`

## Key relationships
- `exchange` 1:N `exchange_connector`
- `exchange` 1:N `exchange_symbol`
- `exchange_account` N:1 `exchange`
- `available_universe_symbol` references `exchange_symbol`
- `observed/training/trading_universe_symbol` reference `available_universe_symbol`
- `symbol_score` and `symbol_override` reference universe symbol and version
- `feature_value` N:1 `feature_snapshot`
- `prediction_event` references `feature_snapshot`
- `confidence_event` references `prediction_event`
- `signal_event` references `prediction_event`
- `orchestrator_decision` references `signal_event`
- `risk_decision` references `orchestrator_decision`
- `execution_intent` references `risk_decision`
- `trader_instance` receives assignments and intents under risk policy
- `audit_event` and `ai_action_change` reference all mutable governance actions

## Mandatory lineage chain
`feature_snapshot_id -> prediction_id -> signal_id -> decision_id -> risk_decision_id -> execution_intent_id`
