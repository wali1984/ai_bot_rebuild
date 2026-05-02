# Ingestor and Feature Pipeline Preservation Matrix

## Objective

Preserve the production-learned legacy ingestor and feature pipeline behavior during the V2 rebuild.

The V2 system must not casually rewrite working ingestors. The first implementation strategy is:

1. inventory,
2. hash,
3. copy/reference,
4. wrap/adapt,
5. parity-test,
6. then enhance only where safe.

## Critical copy-as-is component

### `live_coinank.py`

`live_coinank.py` must be copied as-is into V2 preservation/reference space.

Rules:
- Do not refactor.
- Do not rewrite.
- Do not rename internal fields.
- Do not change timing.
- Do not change parsing.
- Do not change request handling.
- Do not change retry behavior.
- Do not change output payloads.
- Do not change symbol handling.
- Do not alter behavior unless explicitly approved after parity tests and Codex review.

Reason:
This script was made stable after extensive work. Minor changes can break the full CoinAnk ingestor path.

V2 may wrap it or adapter-call it, but must not alter its behavior by default.

## Components to preserve first, then enhance only after parity

The following legacy components should be preserved, inventoried, and wrapped/adapted first. Enhancements are allowed only after behavior capture, parity tests, and review.

| Component | Preservation rule | Enhancement rule |
|---|---|---|
| `live_binance.py` | Preserve behavior first | May enhance after parity tests |
| `live_kucoin.py` | Preserve behavior first | May enhance after parity tests |
| `live_binance_liquidations.py` | Preserve behavior first | May enhance after parity tests |
| `liquidation_bridge.py` | Preserve behavior first | May enhance after parity tests |
| `liquidation_levels_engine.py` | Preserve behavior first | May enhance after parity tests |
| `realtime_price_provider.py` | Preserve behavior first | May enhance after parity tests |
| `live_coinank_global_aggregator.py` | Preserve behavior first | May enhance after parity tests |
| `ingest.live_coinapi_wsds` | Preserve behavior first | May enhance after parity tests |
| `ingest.live_coinapi_v1` | Preserve behavior first | May enhance after parity tests |
| `ohlcv_resampler_hotfix.py` | Preserve behavior first | May enhance after parity tests |
| `feature_pipeline.py` | Preserve behavior first | May enhance after parity tests |
| `live_technical_analysis.py` | Preserve behavior first | May enhance after parity tests |

## Runtime process evidence

Current observed process presence from legacy environment:

| Component | Observed running |
|---|---|
| `live_binance.py` | Yes |
| `live_kucoin.py` | Yes |
| `live_coinank.py` | Yes |
| `live_binance_liquidations.py` | Yes |
| `liquidation_bridge.py` | Yes |
| `liquidation_levels_engine.py` | Yes |
| `realtime_price_provider.py` | Yes |
| `live_coinank_global_aggregator.py` | Yes |
| `ingest.live_coinapi_wsds` | Yes |
| `ingest.live_coinapi_v1` | Yes |
| `ohlcv_resampler_hotfix.py` | Yes |
| `feature_pipeline.py` | Yes |
| `live_technical_analysis.py` | Yes |

## V2 migration policy

### Step 1 - Inventory and hash

For every component:
- find source path,
- record SHA256,
- record file size,
- record process evidence if running,
- record output Redis keys/streams,
- record config dependencies,
- record symbol source,
- record startup command if available.

### Step 2 - Copy/reference

For `live_coinank.py`:
- copy as-is into V2 legacy preservation/reference space,
- record original hash,
- record copied hash,
- hashes must match.

For other components:
- copy/reference as needed,
- preserve behavior first,
- do not enhance until parity tests exist.

### Step 3 - Wrap/adapt

V2 should use wrappers/adapters around preserved behavior.

Adapters must:
- avoid writing to legacy Redis keys,
- write only V2 namespaces during V2 operation,
- preserve payload semantics,
- add freshness metadata,
- add lineage/audit metadata,
- support dynamic symbol universe input without breaking legacy symbol handling.

### Step 4 - Parity tests

Before enhancement:
- compare legacy output shape vs V2 adapter output shape,
- compare timestamps/freshness,
- compare symbol coverage,
- compare error behavior,
- compare rate-limit behavior,
- compare Redis key/stream semantics,
- compare feature output completeness.

### Step 5 - Enhancement gate

Enhancement allowed only after:
- parity test exists,
- parity baseline captured,
- Codex review passes,
- behavior delta is documented,
- rollback plan exists.

## Config/symbol preservation

`config.py` currently controls coin/symbol lists used across ingestors including CoinAnk.

Rules:
- Preserve current symbol configuration behavior.
- Do not break shared symbol propagation.
- V2 dynamic symbol universe must be additive and adapter-based.
- Symbol updates must be hot-reloadable, audited, and reversible.
- Manual override must exist in the enterprise admin GUI.
- No full service restart should be required for symbol updates in V2.

## Trainer/feature relationship

The feature pipeline and trainer are tightly coupled.

Rules:
- Do not alter `feature_pipeline.py` behavior until feature parity is captured.
- Any feature enhancement must record:
  - feature name,
  - source ingestor,
  - source key/pattern,
  - freshness timestamp,
  - stale/missing/unused flags,
  - contribution to prediction/confidence,
  - effect on realized PnL in replay/paper/shadow.

## Hard safety boundaries

- Do not modify `/home/wali/Desktop/AI BOT`.
- Do not write legacy Redis.
- Do not restart legacy ingestors.
- Do not alter live process command lines.
- Do not expose secrets.
- Do not commit local secrets.
- Do not enable live trading.

INGESTOR_AND_FEATURE_PIPELINE_PRESERVATION_MATRIX_READY
