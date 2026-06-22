# V2 Nansen And LunarCrush Docs-Aligned API Repair Report

Generated: 2026-06-04T04:41:55Z

GO/NO-GO: `V2_NANSEN_LUNARCRUSH_DOCS_ALIGNED_API_REPAIR_CODEX_PASS_WITH_LUNARCRUSH_ACCOUNT_402`

Nansen is docs-aligned and live over the 27-symbol V2 dynamic universe. It uses one shared `smart-money/holdings` request per cycle and publishes V2-only symbol payloads. Real Nansen symbol signals are present for `BTCUSDT`, `ETHUSDT`, `FARTCOINUSDT`, `PENGUUSDT`, `SOLUSDT`, and `UNIUSDT`.

LunarCrush is docs-aligned to `https://lunarcrush.com/api4` with `Authorization: Bearer ...`, but the current account/key returns `API_PAYMENT_REQUIRED_402` for `/public/coins/list/v2?limit=1000`.

Safety remains pinned:

- `LIVE_GATE`: `blocked_human_only`
- `live_symbols`: `[]`
- `writes_legacy_redis`: `false`
- `writes_exchange_orders`: `false`
- Test result: `110 passed`
