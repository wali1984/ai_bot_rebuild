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
- Universe changes must apply through hot-reload propagation path (see requirement 14).
- Full platform restart is non-compliant for routine symbol updates.

4. Exchange metadata baseline
- Initial source: Binance Futures contract metadata.
- Design must support additional futures exchanges through connector abstraction.

5. Eligibility and scoring factors (minimum)
- Liquidity
- Volume
- Spread
- Volatility
- Funding
- Open interest
- Trend/regime factors

6. Universe policy controls
- Per-symbol and per-exchange allow/deny policies.
- Freeze/unfreeze symbol capability.
- Soft-disable and hard-disable modes.

## Data model minimum fields
- `symbol_id`
- `exchange_id`
- `contract_type`
- `quote_asset`
- `status` (active/disabled/frozen)
- `train_enabled`
- `trade_enabled`
- `paper_only`
- `live_disabled`
- `liquidity_score`
- `volume_score`
- `spread_score`
- `volatility_score`
- `funding_score`
- `open_interest_score`
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
