# 11 Dynamic Symbol Universe Requirements

## Requirement ID
V2-UNIVERSE-DYNAMIC-001

## Objective
Symbol universe must be managed from GUI without full-system restart, beginning with Binance Futures metadata and expandable to other futures exchanges.

## Mandatory capabilities
1. GUI lifecycle operations
- Add symbol
- Remove symbol
- Update symbol attributes/state
- Bulk import/sync from exchange metadata

2. Symbol operational states (required)
- `train_enabled`
- `trade_enabled`
- `paper_only`
- `live_disabled`

3. No full restart requirement
## Scope extension (required)
- Dynamic symbol universe must integrate with passive all-market discovery and adaptive selection requirements (see requirement 19).
- Universe changes must apply through hot-reload propagation path (see requirement 14).
- Full platform restart is non-compliant for routine symbol updates.
- Order book depth
- Liquidation activity
- Volume
6. Universe layers compatibility (required)
- `available_universe` (passive known instruments)
- `observed_universe` (read-only monitored instruments)
- `training_universe` (capacity-scored train set)
- `trading_universe` (stricter risk-gated trade candidates)
- Spread
- Volatility
- Manual include/exclude and force-state controls (`force_train_only`, `force_paper_only`, `force_disabled`).

- `live_allowed`
- `manual_override_state`
- `override_reason`
- `orderbook_depth_score`
- `liquidation_activity_score`
- `data_completeness_score`
- `feature_freshness_score`
- `model_confidence_history`
- `paper_performance`
- `trade_enabled`
- `paper_only`
- Manual overrides must capture: who, when, why, risk level, rollback value.
- Dangerous overrides require explicit confirmation and approval policy.
- `volume_score`
- `spread_score`
- Four-layer universe compatibility and adaptive selection integration defined.
- `trend_regime_score`
- `universe_version`
- `updated_by`
- `updated_ts_ms`

## Safety and governance
- Any transition enabling live trade path requires readiness gates + admin approval.
- Universe updates must produce audit events with before/after diff and request context.

## Pre-architecture acceptance
- GUI CRUD + policy transitions defined.
- State model includes required enablement modes.
- Restart-free update path specified and auditable.
