# V2 Nansen And LunarCrush Docs-Aligned API Repair Report

Generated: 2026-06-04T04:41:55Z

GO/NO-GO: `V2_NANSEN_LUNARCRUSH_DOCS_ALIGNED_API_REPAIR_CODEX_PASS_WITH_LUNARCRUSH_ACCOUNT_402`

## Result

Nansen and LunarCrush were reviewed against their current API docs, patched, tested, restarted, and revalidated over the 27-symbol V2 dynamic universe.

Execution remains down:

- `LIVE_GATE`: `blocked_human_only`
- `live_symbols`: `[]`
- `writes_legacy_redis`: `false`
- `writes_exchange_orders`: `false`

## Docs Alignment

Nansen:

- Docs reviewed: `https://docs.nansen.ai/api/smart-money`
- Auth docs reviewed: `https://docs.nansen.ai/getting-started/authentication`
- Credit docs reviewed: `https://docs.nansen.ai/getting-started/credits`
- Uses `POST https://api.nansen.ai/api/v1/smart-money/holdings`
- Uses `apikey` auth header.
- Sends `premium_labels: false`.
- Uses one shared Smart Money request per cycle, then maps rows to symbols.
- Persistent loop interval changed from `300` seconds to `21600` seconds to avoid burning credits.

LunarCrush:

- Docs reviewed: `https://lunarcrush.com/en/developers/api`
- Runtime base configured as `https://lunarcrush.com/api4`
- Uses `GET /public/coins/list/v2?limit=1000`
- Uses `Authorization: Bearer ...`.
- Loads the local custody vault, never prints raw credentials.
- Uses one shared coins-list request per cycle, then maps rows to symbols.
- Persistent loop interval changed from `300` seconds to `21600` seconds.

## Runtime Evidence

Nansen:

- `symbol_count`: `27`
- `key_present`: `true`
- `network_call_attempted`: `true`
- `successful_symbol_count`: `27`
- `source_status_counts`: `{"API_OK": 1, "CACHE_HIT": 26}`
- `daily_budget_remaining`: `799`
- symbol-level Nansen signals present for `6 / 27` symbols:
  - `BTCUSDT`
  - `ETHUSDT`
  - `FARTCOINUSDT`
  - `PENGUUSDT`
  - `SOLUSDT`
  - `UNIUSDT`

LunarCrush:

- `symbol_count`: `27`
- `key_present`: `true`
- `network_call_attempted`: `true`
- `successful_symbol_count`: `0`
- `source_status_counts`: `{"API_PAYMENT_REQUIRED_402": 27}`
- `daily_budget_remaining`: `499`

Scoring/candidates:

- Scorer now treats provider payloads with `API_OK`/`CACHE_HIT` but no symbol-level fields as present but not available.
- Nansen is consulted only for symbols with real Nansen fields.
- LunarCrush stays visible as `API_PAYMENT_REQUIRED_402`.
- Current candidate counts:
  - `MISSING_PROVIDER_DATA`: `17`
  - `SYMBOL_NOT_TRADABLE_ON_BINANCE`: `10`
  - `CANDIDATE_READY`: `0`

## Services

Active services verified:

- `ai-bot-v2-nansen-altdata-loop.service`
- `ai-bot-v2-lunarcrush-altdata-loop.service`
- `ai-bot-v2-alternative-data-status-loop.service`
- `ai-bot-v2-alt-data-symbol-scoring-loop.service`
- `ai-bot-v2-alt-data-candidate-publisher-loop.service`

Failed user services: `0`.

## Verification

Commands passed:

- `python -m py_compile` for touched provider/scoring modules and CLIs.
- `python -m pytest v2/backend/tests/integration/cli/test_v2_alternative_data_status.py v2/backend/tests/integration/cli/test_v2_alt_data_symbol_universe_scoring.py v2/backend/tests/integration/cli/test_v2_alt_data_symbol_candidate_publisher.py v2/backend/tests/integration/cli/test_v2_nansen_altdata_ingestor.py v2/backend/tests/integration/cli/test_v2_lunarcrush_altdata_ingestor.py`
- `systemctl --user restart ai-bot-v2-nansen-altdata-loop.service ai-bot-v2-lunarcrush-altdata-loop.service`
- `systemctl --user --failed --no-pager --plain`

Test result: `110 passed`.

## Remaining Blocker

LunarCrush is configured to the documented API4/Bearer path, but the current account/key returns `API_PAYMENT_REQUIRED_402` for the documented coins list endpoint. Code and runtime are live; provider access requires account/subscription correction with LunarCrush.
