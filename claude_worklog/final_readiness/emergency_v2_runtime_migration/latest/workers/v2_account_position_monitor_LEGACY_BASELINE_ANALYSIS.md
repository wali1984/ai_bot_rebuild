# V2 Account Position Monitor Legacy Baseline Analysis

worker_id: `v2_account_position_monitor`
classification: `MISSING_IN_V2_PORTED_READONLY`
live_gate: `blocked_human_only`

## Legacy Source Paths

- `legacy_reference/monitor_portfolio.py`
- `legacy_reference/monitor_portfolio_primary.py`
- `legacy_reference/monitor_portfolio_asjad.py`
- `legacy_reference/trading/position_reporter.py`
- `legacy_reference/utils/unified_position_loader.py`
- `legacy_reference/config.py`

## Legacy Functions Preserved

- `PortfolioMonitor._display_portfolio_status()` reads Binance Futures account and position state for operator visibility.
- `PortfolioMonitor._fetch_account()` in the per-account monitors calls the account read path and returns `None` on failure.
- `PortfolioMonitor._fetch_positions()` in the per-account monitors derives active positions, side, leverage, margin type, notional, margin, liquidation price, and PnL.
- `PortfolioMonitor._margin_ratio()` derives maintenance-margin ratio from account totals.
- Redis portfolio display behavior is documented as legacy cached display only; it is not ported as a Redis writer or account truth source.

## Legacy Inputs

- Binance USD-M account evidence from `futures_account()`.
- Binance USD-M position evidence from `futures_position_information()`.
- Legacy config credentials via `get_live_config()`.
- Optional cached Redis display keys such as `portfolio:equity:*`, `stealth_stops:{account_id}`, and mark-price cache keys.

## Legacy Outputs

- Terminal display of total balance, available balance, unrealized PnL, active positions, side, leverage, margin used, entry/mark price, liquidation price, and account margin ratio.
- Optional Telegram summary in the generic monitor.
- Redis cached display rows were read and printed but not treated as authoritative exchange account state.

## Legacy Redis Keys

Read-only references only:

- `portfolio:equity:*`
- `stealth_stops:{account_id}`
- `latest:binance:mark_price:{symbol}`
- `regime:{symbol}`

V2 intentionally does not write old Redis and does not use cached paper or portfolio rows as live account evidence.

## Legacy Config Dependencies

- `BINANCE_FUT_API_KEY`
- `BINANCE_FUT_API_SECRET`
- Account margin and leverage safety config in `legacy_reference/config.py`.
- Symbol seed in `legacy_reference/config.py SYMBOLS`, now exposed through `SymbolUniverseService`.

## Legacy Edge Cases

- Binance client unavailable or keys absent disables live account visibility.
- API errors and bans fall back to cached display in legacy; V2 instead fail-closes as missing/exchange-read evidence.
- Missing mark price falls back to last cached mark or entry in legacy; V2 only reports exchange position fields it receives.
- Zero-size positions are excluded from active position output.
- Missing leverage or margin type is tolerated but explicitly labeled as `MISSING_EVIDENCE`.

## Legacy Failure Modes

- Missing Binance dependency.
- Missing credentials.
- Exchange read errors or rate limits.
- Partial account payloads without position leverage.
- Legacy Redis cache unavailable.

## V2 Mapping

- `v2/backend/app/services/account_position_monitor/service.py` owns the read-only account and position evidence contract.
- `v2/backend/app/cli/v2_account_position_monitor.py` is the standalone worker entry point.
- Public payload writes to `v2/frontend/public/operator_runtime/v2_account_position_monitor/latest/v2_account_position_monitor_status.json`.
- Worklog payload writes to `claude_worklog/final_readiness/emergency_v2_runtime_migration/latest/workers/v2_account_position_monitor_status.json`.
- Missing credentials emit `MISSING_CREDENTIALS`; no evidence is fabricated.
- Paper runtime positions are discovered only as a separation proof and are never relabeled as real account positions.
- Symbol scope is read from `v2/backend/app/services/symbol_universe/service.py` or a V2 public Symbol Universe payload if present.

## Intentional Changes

- V2 does not import the legacy Binance client wrapper and does not read `/home/wali/Desktop/AI BOT`.
- V2 does not use Telegram output.
- V2 does not write or query old Redis for account truth.
- V2 explicitly fail-closes on missing credentials and exchange errors.
- V2 derives and emits maintenance-margin ratio from read-only account totals.
- V2 tests cover active-position filtering, entry/mark/liquidation/notional/PnL fields, and balance fields.
- V2 exposes `legacy_active_symbols`, `dynamic_discovered_symbols`, `observed_symbols`, `training_symbols`, `paper_symbols`, `live_symbols`, and `live_blocked_symbols` separately.
- `live_symbols` is always empty while `live_gate` remains `blocked_human_only`.

## Removed Or Deprecated Behavior

- Redis cached portfolio display as account evidence: removed because it can be stale and is not exchange-confirmed.
- Terminal-only UI formatting: replaced by JSON public payloads for operator dashboard consumption.
- Telegram notification path: outside this worker's responsibility.

## Tests Or Expected Behavior

- Read-only account endpoint is called.
- Read-only position-risk endpoint is called.
- Missing credentials emits `MISSING_CREDENTIALS`.
- Paper positions are ignored for real account evidence.
- Exchange 5xx/timeout style errors fail closed.
- Rate limits use bounded backoff.
- Mutating client attributes fail the read-only contract.
- Symbol Universe roles are distinguished and the current 25 legacy symbols are not treated as the full universe.
