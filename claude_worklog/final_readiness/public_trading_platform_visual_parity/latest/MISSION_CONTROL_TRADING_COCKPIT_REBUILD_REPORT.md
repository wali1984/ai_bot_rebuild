# Mission Control Trading Cockpit Rebuild Report

Generated: 2026-05-13T06:10:50.961Z

## Changes
- Added a first-screen trading cockpit above truth/status sections.
- Added a read-only BTCUSDT chart-first layout with source/freshness label.
- Added top rail for live gate, mode, symbol, paper age, legacy bridge state, and Claude/Codex task.
- Added current prediction, signal, risk decision, execution intent, paper PnL, and shadow/risk block cards.
- Added CoinAnk-derived market strip for price, funding, OI, long/short, and liquidation status.
- Added legacy read-only import vs V2 risk outcome vs paper/execution comparison.

## Safety
No live controls were added. The first screen continues to show live blocked_human_only and paper/shadow mode.

## Evidence
- Public screenshot: `screenshots/after/public_mission-control.png`
- Local screenshot: `screenshots/after/local_mission-control.png`
