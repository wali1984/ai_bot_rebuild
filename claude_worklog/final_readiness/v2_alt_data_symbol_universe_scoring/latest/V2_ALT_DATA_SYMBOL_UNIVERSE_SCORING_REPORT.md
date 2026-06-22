# V2 Alternative-Data Symbol Universe Scoring Report

Generated: `2026-06-22T00:24:59Z`

GO/NO-GO: `V2_ALT_DATA_SYMBOL_UNIVERSE_SCORING_READY`

This packet does NOT approve live trading, canary trading, exchange mutation, leverage/margin changes, legacy shutdown, Redis trim, checkpoint compatibility, or policy architecture parity.

## Scope

The scorer reads ONLY ``v2:altdata:nansen:*``, ``v2:altdata:lunarcrush:*``, ``v2:altdata:coingecko:*``, ``v2:altdata:surf:*``, ``v2:altdata:coinglass:*``, ``v2:altdata:public_intel:*``, ``v2:altdata:aicoin:*``, ``v2:altdata:whale_walls:*``, ``v2:market:*``, and ``v2:features:latest:{symbol}:{timeframe}``. It does NOT read ``v2:paper:*`` or ``v2:risk:*``; any paper/risk overlay belongs to a separately reviewed lane.

## Candidate Ranking

| Symbol | Alt-data score | Availability | Freshness | Providers | Missing | Stale |
| --- | ---: | ---: | ---: | --- | --- | --- |
| BTCUSDT | 0.692312 | 0.5 | 0.974444 | coingecko,public_intel,whale_walls | True | False |
| XRPUSDT | 0.65629 | 0.5 | 0.976296 | coingecko,public_intel,whale_walls | True | False |
| HYPEUSDT | 0.646445 | 0.5 | 0.981111 | coingecko,public_intel,whale_walls | True | False |
| AEROUSDT | 0.62613 | 0.5 | 0.977778 | coingecko,public_intel,whale_walls | True | False |
| BNBUSDT | 0.615152 | 0.5 | 0.979444 | coingecko,public_intel,whale_walls | True | False |
| SYNUSDT | 0.612676 | 0.5 | 0.985741 | coingecko,public_intel,whale_walls | True | False |
| SOLUSDT | 0.59648 | 0.5 | 0.976111 | coingecko,public_intel,whale_walls | True | False |
| ARBUSDT | 0.592862 | 0.4 | 0.966944 | public_intel,whale_walls | True | False |
| EIGENUSDT | 0.592786 | 0.5 | 0.97963 | coingecko,public_intel,whale_walls | True | False |
| BARDUSDT | 0.589746 | 0.4 | 0.961389 | public_intel,whale_walls | True | False |
| METUSDT | 0.58764 | 0.5 | 0.981667 | coingecko,public_intel,whale_walls | True | False |
| UNIUSDT | 0.587046 | 0.5 | 0.975926 | coingecko,public_intel,whale_walls | True | False |
| SLXUSDT | 0.583132 | 0.4 | 0.976389 | public_intel,whale_walls | True | False |
| JUPUSDT | 0.578393 | 0.5 | 0.981481 | coingecko,public_intel,whale_walls | True | False |
| ENAUSDT | 0.574842 | 0.5 | 0.97963 | coingecko,public_intel,whale_walls | True | False |
| XLMUSDT | 0.573407 | 0.5 | 0.985926 | coingecko,public_intel,whale_walls | True | False |
| XAUTUSDT | 0.568653 | 0.5 | 0.985926 | coingecko,public_intel,whale_walls | True | False |
| JTOUSDT | 0.565795 | 0.5 | 0.981296 | coingecko,public_intel,whale_walls | True | False |
| PAXGUSDT | 0.562747 | 0.5 | 0.982963 | coingecko,public_intel,whale_walls | True | False |
| ONDOUSDT | 0.561135 | 0.5 | 0.982963 | coingecko,public_intel,whale_walls | True | False |
| POLUSDT | 0.560835 | 0.5 | 0.982963 | coingecko,public_intel,whale_walls | True | False |
| CRVUSDT | 0.559229 | 0.5 | 0.97963 | coingecko,public_intel,whale_walls | True | False |
| AVAXUSDT | 0.557254 | 0.5 | 0.977963 | coingecko,public_intel,whale_walls | True | False |
| ASTERUSDT | 0.556568 | 0.5 | 0.974259 | coingecko,public_intel,whale_walls | True | False |
| SUNUSDT | 0.553109 | 0.5 | 0.985556 | coingecko,public_intel,whale_walls | True | False |
| PUMPUSDT | 0.552168 | 0.5 | 0.983148 | coingecko,public_intel,whale_walls | True | False |
| PENDLEUSDT | 0.550749 | 0.5 | 0.982963 | coingecko,public_intel,whale_walls | True | False |
| AAVEUSDT | 0.543945 | 0.5 | 0.977593 | coingecko,public_intel,whale_walls | True | False |
| AVNTUSDT | 0.543228 | 0.4 | 0.961389 | public_intel,whale_walls | True | False |
| PENGUUSDT | 0.538304 | 0.5 | 0.976111 | coingecko,public_intel,whale_walls | True | False |
| OPUSDT | 0.535585 | 0.5 | 0.982778 | coingecko,public_intel,whale_walls | True | False |
| BELUSDT | 0.534207 | 0.5 | 0.977963 | coingecko,public_intel,whale_walls | True | False |
| 1000FLOKIUSDT | 0.529564 | 0.4 | 0.961667 | public_intel,whale_walls | True | False |
| DOTUSDT | 0.528906 | 0.5 | 0.979444 | coingecko,public_intel,whale_walls | True | False |
| INJUSDT | 0.527072 | 0.5 | 0.981296 | coingecko,public_intel,whale_walls | True | False |
| TAOUSDT | 0.524187 | 0.5 | 0.985556 | coingecko,public_intel,whale_walls | True | False |
| BICOUSDT | 0.521368 | 0.5 | 0.978148 | coingecko,public_intel,whale_walls | True | False |
| RIVERUSDT | 0.512089 | 0.4 | 0.964167 | public_intel,whale_walls | True | False |
| DASHUSDT | 0.505286 | 0.5 | 0.979444 | coingecko,public_intel,whale_walls | True | False |
| MEGAUSDT | 0.50342 | 0.5 | 0.981481 | coingecko,public_intel,whale_walls | True | False |
| NEARUSDT | 0.503336 | 0.5 | 0.982593 | coingecko,public_intel,whale_walls | True | False |
| BTWUSDT | 0.503272 | 0.5 | 0.97963 | coingecko,public_intel,whale_walls | True | False |
| KITEUSDT | 0.503042 | 0.4 | 0.971944 | public_intel,whale_walls | True | False |
| WLDUSDT | 0.487571 | 0.5 | 0.985926 | coingecko,public_intel,whale_walls | True | False |
| 1000SHIBUSDT | 0.487159 | 0.5 | 0.974259 | coingecko,public_intel,whale_walls | True | False |
| LTCUSDT | 0.486692 | 0.5 | 0.976111 | coingecko,public_intel,whale_walls | True | False |
| TRUMPUSDT | 0.485422 | 0.5 | 0.985556 | coingecko,public_intel,whale_walls | True | False |
| AXSUSDT | 0.484564 | 0.5 | 0.977963 | coingecko,public_intel,whale_walls | True | False |
| ICPUSDT | 0.47937 | 0.5 | 0.981481 | coingecko,public_intel,whale_walls | True | False |
| ETHUSDT | 0.474097 | 0.5 | 0.976111 | coingecko,public_intel,whale_walls | True | False |
| TRXUSDT | 0.473844 | 0.5 | 0.985741 | coingecko,public_intel,whale_walls | True | False |
| BANKUSDT | 0.472197 | 0.4 | 0.961389 | public_intel,whale_walls | True | False |
| SUIUSDT | 0.469984 | 0.5 | 0.985556 | coingecko,public_intel,whale_walls | True | False |
| ZECUSDT | 0.469512 | 0.5 | 0.987222 | coingecko,public_intel,whale_walls | True | False |
| XMRUSDT | 0.463059 | 0.5 | 0.985926 | coingecko,public_intel,whale_walls | True | False |
| ADAUSDT | 0.458265 | 0.5 | 0.977778 | coingecko,public_intel,whale_walls | True | False |
| 1000PEPEUSDT | 0.456597 | 0.5 | 0.974259 | coingecko,public_intel,whale_walls | True | False |
| BCHUSDT | 0.45644 | 0.5 | 0.977778 | coingecko,public_intel,whale_walls | True | False |
| LINKUSDT | 0.454446 | 0.5 | 0.976111 | coingecko,public_intel,whale_walls | True | False |
| SANDUSDT | 0.454093 | 0.5 | 0.983333 | coingecko,public_intel,whale_walls | True | False |
| ETCUSDT | 0.453668 | 0.5 | 0.97963 | coingecko,public_intel,whale_walls | True | False |
| APTUSDT | 0.453501 | 0.5 | 0.977963 | coingecko,public_intel,whale_walls | True | False |
| REUSDT | 0.451683 | 0.5 | 0.983333 | coingecko,public_intel,whale_walls | True | False |
| FILUSDT | 0.448253 | 0.5 | 0.980926 | coingecko,public_intel,whale_walls | True | False |
| RENDERUSDT | 0.445499 | 0.5 | 0.983333 | coingecko,public_intel,whale_walls | True | False |
| HBARUSDT | 0.444319 | 0.5 | 0.981111 | coingecko,public_intel,whale_walls | True | False |
| XPLUSDT | 0.440112 | 0.5 | 0.987037 | coingecko,public_intel,whale_walls | True | False |
| DOGEUSDT | 0.43971 | 0.5 | 0.974259 | coingecko,public_intel,whale_walls | True | False |
| FETUSDT | 0.439236 | 0.5 | 0.98 | coingecko,public_intel,whale_walls | True | False |
| ALICEUSDT | 0.438519 | 0.5 | 0.974259 | coingecko,public_intel,whale_walls | True | False |
| AUCTIONUSDT | 0.435122 | 0.4 | 0.961389 | public_intel,whale_walls | True | False |
| VIRTUALUSDT | 0.430771 | 0.5 | 0.985926 | coingecko,public_intel,whale_walls | True | False |
| CHZUSDT | 0.430282 | 0.5 | 0.979444 | coingecko,public_intel,whale_walls | True | False |
| ORDIUSDT | 0.346402 | 0.4 | 0.974444 | public_intel,whale_walls | True | False |
| MANAUSDT | 0.34627 | 0.4 | 0.971667 | public_intel,whale_walls | True | False |
| EPICUSDT | 0.346177 | 0.4 | 0.969722 | public_intel,whale_walls | True | False |
| ALLOUSDT | 0.346045 | 0.4 | 0.966944 | public_intel,whale_walls | True | False |
| FARTCOINUSDT | 0.345926 | 0.4 | 0.964444 | public_intel,whale_walls | True | False |
| PIPPINUSDT | 0.345913 | 0.4 | 0.964167 | public_intel,whale_walls | True | False |
| RAVEUSDT | 0.345913 | 0.4 | 0.964167 | public_intel,whale_walls | True | False |
| WIFUSDT | 0.345913 | 0.4 | 0.964167 | public_intel,whale_walls | True | False |
| 1000BONKUSDT | 0.345794 | 0.4 | 0.961667 | public_intel,whale_walls | True | False |
| RAREUSDT | 0.322606 | 0.4 | 0.974722 | public_intel,whale_walls | True | False |
| IPUSDT | 0.322473 | 0.4 | 0.971944 | public_intel,whale_walls | True | False |
| ENSUSDT | 0.322341 | 0.4 | 0.969167 | public_intel,whale_walls | True | False |
| AGTUSDT | 0.322235 | 0.4 | 0.966944 | public_intel,whale_walls | True | False |

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
