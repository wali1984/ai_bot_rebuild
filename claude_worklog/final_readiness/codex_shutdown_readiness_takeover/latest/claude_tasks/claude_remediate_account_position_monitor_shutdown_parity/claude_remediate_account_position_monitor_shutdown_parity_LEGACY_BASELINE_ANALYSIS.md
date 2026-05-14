# Legacy Baseline Analysis: Account Position Monitor Shutdown Parity

The legacy account/position behavior reads exchange account and position state for margin, leverage, and open-position evidence. Codex reviewed preserved sources read-only and did not call exchange mutation endpoints.

## SHA Citations

- `trading/position_reporter.py` SHA256 `da0958cb11f8106593049bdfb7c48d2603bb009ed9b3f2b76ce5043b0e6aabd2`
- `utils/unified_position_loader.py` SHA256 `5e8b5e5dfb736a1808f3e638ea51c25cab7c33c50d34abf210cc863854c21abe`
- `config.py` SHA256 `98cfaa1c9650f013f8603c451f6f37491b8fa65e36ed1445a037c34d5f27f522`
- `monitor_portfolio_primary.py` SHA256 `ba51097c8229eb489e94c9af058b24680b41f8bcd6a8c4912bd18f73a31908cf` from `copied_baseline_manifest.json`
- `monitor_portfolio_asjad.py` SHA256 `e957f2d2f80ee2ad3f9676e4c7d9f330015a9dbebe3645f71b77c7f4089d3b1e` from `copied_baseline_manifest.json`
- `monitor_portfolio.py` SHA256 `06eb2afe4d15bc91d10048f8c92404356f1c7fc6e58e2584081b43fbd6e57a9b` from local `legacy_reference`; no copied-baseline manifest record exists for this file.

## V2 Mapping

V2 account evidence is intentionally fail-closed when read-only credentials are missing. The monitor may classify missing/stale account evidence and prove live remains blocked, but it cannot infer exchange key trade permissions without current read-only account/key metadata.

## Current Classification

`MISSING_CREDENTIALS`, `TRADE_PERMISSION_UNKNOWN_BLOCKS_CANARY`, margin evidence missing, and leverage evidence missing remain shutdown/canary blockers.

This packet is Codex-recovered because the supervised Claude child emitted no materialized files. It is valid only as a conservative blocked classification and must not be read as account/trade-permission parity clearance.
