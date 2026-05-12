# V2 Live Observer Shadow Twin Report

Status: V2_LIVE_OBSERVER_SHADOW_TWIN_READY

Generated at: 2026-05-12T19:58:03Z

- Legacy bridge importer: `LEGACY_LIVE_BRIDGE_IMPORTER_CURRENT`
- V2 paper runtime: `CURRENT`
- Trainer bridge/parity: `PARTIAL_RUNTIME_BRIDGE_PARITY_NOT_FULL_MODEL_PARITY`
- Orchestrator adapter: `LEGACY_OBSERVER_ADAPTER_ACTIVE`
- Risk Gateway: `CURRENT_SHADOW_SIGNAL_PROCESSED`
- Paper shadow ledger: `CURRENT_SHADOW_LEDGER_WRITTEN`
- Audit ledger: `V2_FILE_AUDIT_LEDGER_CURRENT_POSTGRES_SCHEMA_READY`
- V2 Redis namespace: `V2_REDIS_NAMESPACE_CONTRACT_READY_WRITE_DISABLED_FOR_SAFETY`
- Live gate: `blocked_human_only`

The bridge observes legacy processes and legacy Redis streams read-only, normalizes the latest legacy signal/proposal into a V2 shadow twin, routes it through a V2 fail-closed Risk Gateway decision, and writes only V2-owned local/public runtime artifacts. It does not modify legacy, write old Redis, place orders, or change leverage/margin.
