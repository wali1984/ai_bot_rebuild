# V2 Alternative-Data Symbol Universe Scoring Report

Generated: `2026-06-15T19:38:39Z`

GO/NO-GO: `V2_ALT_DATA_SYMBOL_UNIVERSE_SCORING_READY`

This packet does NOT approve live trading, canary trading, exchange mutation, leverage/margin changes, legacy shutdown, Redis trim, checkpoint compatibility, or policy architecture parity.

## Scope

The scorer reads ONLY ``v2:altdata:nansen:*``, ``v2:altdata:lunarcrush:*``, ``v2:altdata:coingecko:*``, ``v2:altdata:surf:*``, ``v2:altdata:coinglass:*``, ``v2:altdata:public_intel:*``, ``v2:altdata:aicoin:*``, ``v2:altdata:whale_walls:*``, ``v2:market:*``, and ``v2:features:latest:{symbol}:{timeframe}``. It does NOT read ``v2:paper:*`` or ``v2:risk:*``; any paper/risk overlay belongs to a separately reviewed lane.

## Candidate Ranking

| Symbol | Alt-data score | Availability | Freshness | Providers | Missing | Stale |
| --- | ---: | ---: | ---: | --- | --- | --- |
| BTCUSDT | None | 0.0 | 0.0 | none | True | False |
| ETHUSDT | None | 0.0 | 0.0 | none | True | False |

## Safety

- `live_gate`: `blocked_human_only`
- `live_symbols`: `[]`
- `paper_symbols_expanded`: `false`
- `may_not_override_strict_paper_fill_gate`: `true`
- `checkpoint_compatibility_claimed`: `false`
- `policy_architecture_parity_claimed`: `false`
- `writes_old_redis`: `false`
- `exchange_mutation`: `false`

## Final Decision

`V2_ALT_DATA_SYMBOL_UNIVERSE_SCORING_READY`
