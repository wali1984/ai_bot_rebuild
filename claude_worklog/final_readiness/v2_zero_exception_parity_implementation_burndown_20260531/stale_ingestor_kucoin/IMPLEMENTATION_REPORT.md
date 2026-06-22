# V2 Stale Ingestor Fix — KuCoin

Generated EST: 2026-06-03T18:32:40-0400  
Generated UTC: 2026-06-03T22:32:40Z

The stale KuCoin row is closed by the same implementation as `missing_impl_live_kucoin`: `v2_kucoin_ingestor_worker` now performs real public REST fetches and writes fresh V2 Redis/public payload evidence.

Evidence:

- Public payload `classification=NATIVE_V2_PUBLIC_REST_OK`
- `v2:market:kucoin:*` = 11
- `v2:features:kucoin:*` = 2
- No old Redis writes.

LIVE_GATE remains `blocked_human_only`; `live_symbols=[]`.
