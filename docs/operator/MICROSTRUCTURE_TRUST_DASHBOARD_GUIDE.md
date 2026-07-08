# Microstructure Trust — Operator Dashboard Guide

Last verified: 2026-07-07 00:15 EST

## Services that must be green
```bash
systemctl --user status ai-bot-v2-microstructure-runtime-supervisor.service   # feeds books (binance+kucoin children)
systemctl --user status ai-bot-v2-microstructure-feed-quality-monitor.service # scores trust every 2s
```
If the supervisor dies, book keys expire in ~30s and every symbol fails closed to
NO_TRADE within a minute (BOOK_UPDATE_AGE_TOO_HIGH). That is correct behavior —
fix the feed, never the threshold.

## Health checks (copy/paste)
```bash
# coverage: expect ~85 binance, ~82 kucoin
redis-cli --scan --pattern "v2:orderbook:depth:binance:*" | wc -l
redis-cli --scan --pattern "v2:orderbook:depth:kucoin:*" | wc -l
# freshness: TTL should sit 20-30s and refresh continuously
redis-cli TTL v2:orderbook:depth:binance:BTCUSDT
# trust for one symbol
redis-cli GET v2:microstructure:trust_score:BTCUSDT:1m | python3 -m json.tool | grep -E '"microstructure_trust_score"|persistence|cross_venue|action|adaptive_minimum|fail_reasons'
```

## Reading the dashboard fields
- `book_depth_persistence_reason`: STABLE_DEPTH_WINDOW is healthy;
  INSUFFICIENT_DEPTH_WINDOW across many symbols = recorder gap (check supervisor);
  MISSING_DEPTH_FIELDS = schema problem (escalate); DEPTH_UNSTABLE on a few thin
  alts is normal market truth.
- `depth_persistence_unavailable_exchanges`: ["kucoin"] on a symbol = KuCoin not
  listed or its child is down; cross-venue for that symbol stays "unconfirmed".
- `microstructure_action` distribution (expect mix): NO_TRADE (low trust,
  fail-closed), SHADOW_ONLY, REDUCE_SIZE (paper bootstrap), ALLOW (rare until
  trust matures past 0.65).

## Alarms worth raising
- persistence reason INSUFFICIENT on >30% symbols for >10 min -> supervisor/recorder issue
- kucoin depth keys = 0 for >10 min -> kucoin children crashlooping (journalctl --user -u ai-bot-v2-microstructure-runtime-supervisor)
- any symbol with trust >= 0.65 AND single venue -> should be impossible; report as bug
- full-size (non-reduced) paper entry while trust < 0.65 -> bug, halt and report

## Never do
- Do not lower adaptive_minimum (0.65) to make trades flow.
- Do not mark public books trusted by default.
- Do not restart legacy services or paper_online_runtime as part of trust debugging.

## Purpose
Show operators how to verify the current microstructure trust feed, distinguish stale feed failure from honest low-trust symbols, and keep public orderbook data from being treated as final trust by itself.

## Source Files
- `v2/backend/app/services/microstructure_trust/status.py`
- `v2/backend/app/services/microstructure_trust/trust_score.py`
- `v2/backend/app/cli/v2_microstructure_feed_quality_monitor.py`
- `v2/backend/app/cli/v2_microstructure_runtime_supervisor.py`

## Runtime Redis Keys/API Routes
- Redis: `v2:microstructure:trust_score:{SYMBOL}:{timeframe}`
- Redis: `v2:orderbook:depth:{exchange}:{SYMBOL}`
- API: `/api/v2/paper/runtime-status`
- API: `/api/v2/system/health`

## Failure Modes
- Supervisor down, causing depth keys to expire and symbols to fail closed.
- KuCoin children missing, causing honest single-venue confirmation caps.
- `REDUCE_SIZE` incorrectly shown as final A+ evidence.

## Debug Commands
- `redis-cli GET v2:microstructure:trust_score:BTCUSDT:1m | python3 -m json.tool`
- `systemctl --user status ai-bot-v2-microstructure-runtime-supervisor.service`

## Validation Commands
- `python -m py_compile v2/backend/app/services/microstructure_trust/*.py`
- `.venv/bin/pytest -q v2/backend/tests/unit/services/microstructure_trust`

## Evidence Artifacts
- `goal_state/V2_CODEX_A_TO_Z_FABLE_PHASE_VALIDATION_FIX_RESOLUTION_AND_GO_LIVE_READINESS_COMPLETION/PHASE_C_ORDERBOOK_PERSISTENCE_STATUS.json`
- `goal_state/V2_CODEX_A_TO_Z_FABLE_PHASE_VALIDATION_FIX_RESOLUTION_AND_GO_LIVE_READINESS_COMPLETION/PHASE_C_CROSS_VENUE_CONFIRMATION_STATUS.json`

