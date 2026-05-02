# Requirement 0002 - CoinAnk Uploaded Symbol List

The uploaded CoinAnk symbol list must be added to V2 symbol-universe source fixtures and documentation.

Uploaded source path:
`/home/wali/Downloads/coinanksymbols.odt`

Rules:
- Treat CoinAnk list as broad discovery/alias evidence.
- Do not treat CoinAnk list as direct tradable universe.
- Preserve raw rows:
  - symbol
  - baseCoin
  - exchangeName
  - expireAt
  - updateAt
- Normalize cautiously across Binance USD-M, optional COIN-M, KuCoin, CoinAPI WS, CoinAPI REST.
- Chinese-name symbols must be preserved raw and marked requires confirmation.
- Stock/commodity-like symbols must not be auto-eligible for training/trading.
- ETHBTC must not be auto-classified as USD-M futures.
- CoinAnk BTCUSDT may map to Binance USD-M BTCUSDT only when Binance USD-M confirms it.
- BTCUSD_PERP must remain separate from BTCUSDT.
- Dated contracts like BTCUSD_260626 must remain separate from perpetuals.
- USDC pairs must remain separate from USDT pairs.

REQ_COINANK_UPLOADED_SYMBOL_LIST_READY
