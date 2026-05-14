# Legacy Baseline Analysis — Three Unresolved Local Imports

All SHA256 values below are recomputed in this task from the files under `legacy_reference/` (read-only) or cited verbatim from the indicated manifest file. No legacy bytes are mutated.

## 1. `ingest` (namespace package)

The `ingest/` directory is a Python namespace package used by trader and rl modules via `from ingest.<module> import …`. The directory is preserved under `v2/legacy_preserved/startup_baseline/ingest/` (phase C of the legacy-startup-baseline migration). The 11 entries recorded in `copied_baseline_manifest.json` with verified SHA256:

| legacy_rel_path | sha256 | size_bytes | manifest status |
|---|---|---|---|
| `ingest/live_binance.py` | `6c1eb771a3842e2d94b797eedd55aa624075c51c6d50aec701397f81dbace798` | 125730 | COPIED |
| `ingest/live_kucoin.py` | `73b852db1bf69062d4028091cf17c126f5cb666e94bf784cdb2bb9b47328a976` | 36382 | COPIED |
| `ingest/live_coinank.py` | `cd13dab55c0906c379e4116102c05f960908dd28d6b6e883ca76347cd1f144c8` | 127414 | COPIED |
| `ingest/live_coinank_global_aggregator.py` | `1f85c4532e4829aa99ddadbd6a5cd2325ef9e5c4012208eb05876c1b0187eeae` | 14475 | COPIED |
| `ingest/live_binance_liquidations.py` | `19711590a3d194fd05ae3be85ef7bd6dec397f6394d02f7e91008c44c310131b` | 46088 | COPIED |
| `ingest/liquidation_bridge.py` | `5d70e395938228b61162b531310cd751403ddfeebb8920429e73cdcdbe35d48a` | 6327 | COPIED |
| `ingest/liquidation_levels_engine.py` | `fed3c90b5193c27d24dc183089730bda49ff69a1758b597e23a154397f839df7` | 18539 | COPIED |
| `ingest/realtime_price_provider.py` | `dfdc2568368c134b9afcc4fa0faff312cc93a6ecc501ecaac747e7c20d7344ba` | 45009 | COPIED |
| `ingest/live_coinapi_wsds.py` | `a6973d887d1c52a4bb48f3b6f222b04e97d92e500ab889e94d6026cf504471b6` | 77253 | COPIED |
| `ingest/live_coinapi_v1.py` | `c8ca17d21b972510b92c4e84c477cd3440b3cfd1e2ec8e7411624a7454cee280` | 28497 | COPIED |
| `ingest/live_technical_analysis.py` | `5cdd4ea1d43271d0199e1ca92ecad3a8b76308838898a611df6ef4602f7388ac` | 6103 | COPIED |

Source manifest: `claude_worklog/final_readiness/legacy_startup_baseline_v2_migration/latest/copied_baseline_manifest.json` (records starting line 44 in that file). Note: additional `ingest/*.py` files exist in `legacy_reference/ingest/` (e.g. `base_ingestor.py`, `alphavantage_client.py`, `tokenmetrics_normalizer.py`, etc., per `legacy_reference/ingest/` directory listing) — these were not in the startup-baseline copy scope. Whether each additional file is needed by the rl/trading closure must be resolved by the closure scanner rerun: any further `from ingest.<x> import …` references not in the table above must be added to the copier scope in a separate extension delta.

Baseline behavior (summary, not parity claim): the `ingest/` package provides live and historical market-data ingestors for Binance, KuCoin, CoinAnk, CoinAPI, liquidation feeds, technical-analysis feeds, and a realtime price provider. Trader and rl modules consume these to fill the feature pipeline and to detect liquidation/price events. No V2 replacement is currently active for these ingestors — V2's paper mode reads from preserved snapshots / replay artifacts, not live exchange feeds — so the legacy `ingest/` package is preserved for parity reconstruction by the future live-readiness gate. Live-readiness remains blocked.

## 2. `binance_websocket` (top-level helper)

Source file: `legacy_reference/binance_websocket.py`.
- SHA256 (recomputed this task): `aef4e1d6ac7b994cb96f2521b8bcc9810cd9f75a19f11ba4ed85f690133deb26`
- Size: 21698 bytes.
- Line count: 610.
- Manifest presence: **absent** from `full_runtime_copied_source_manifest.json` and from `copied_baseline_manifest.json` (verified by grep, 0 occurrences in either file).
- Importer evidence (read-only grep):
  - `legacy_reference/rl/hybrid_trainer.py:538` — `from binance_websocket import BinanceWebSocketHelper`
  - `legacy_reference/rl/CRITICAL_HEDGE_AND_PORTFOLIO_FIX.py:33` — `from binance_websocket import BinanceWebSocketHelper`
  - (Reference-only): `legacy_reference/ENHANCEMENT_VALIDATION_REPORT.md:295` documents the same import.

Baseline behavior (summary): exports `BinanceWebSocketHelper`, used by the legacy hybrid trainer and by the critical-hedge/portfolio-fix module. The helper wraps Binance websocket subscription primitives for the trainer's price/liquidation feeds. It is not a V2 path — V2 has no equivalent — and must be preserved verbatim for parity reconstruction. Live trading remains blocked.

## 3. `hybrid_rule_based_signals` (top-level helper)

Source file: `legacy_reference/hybrid_rule_based_signals.py`.
- SHA256 (recomputed this task): `c2ad008a489ca633ffa198afbe106c45ce20dca70f15aa91922e0dca1c41971f`
- Size: 18754 bytes.
- Line count: 435.
- Manifest presence: **absent** from `full_runtime_copied_source_manifest.json` and from `copied_baseline_manifest.json` (verified by grep, 0 occurrences in either file).
- Importer evidence (read-only grep):
  - `legacy_reference/rl/hybrid_trainer.py:56819` — `from hybrid_rule_based_signals import HybridRuleBasedSignalGenerator`
  - (Reference-only, not in primary runtime closure): `legacy_reference/debug_rule_signals.py:8`, plus several `legacy_reference/archive/hybrid_trainer.py.backup*` snapshots — confirms long-standing import contract.

Baseline behavior (summary): exports `HybridRuleBasedSignalGenerator`, used by the legacy hybrid trainer to combine rule-based signals with model output. The V2 paper trainer is a momentum-style placeholder and does not currently implement this hybrid blend — the legacy source is preserved so the trainer-bridge port (status `BLOCKED_BY_TRAINER_PARITY` / `WRAPPER_NOT_LEGACY_HYBRID_PARITY`) has the source needed to either subprocess-wrap or re-implement the behavior under operator gate. Live trading remains blocked.

## Why not `LEGACY_ONLY_DEP_REPLACED_BY_V2_WITH_REASON`

The closure-review classification list (lines 54–62 of `FULL_TRAINER_TRADER_DEPENDENCY_CLOSURE.md`) invited `LEGACY_ONLY_DEP_REPLACED_BY_V2_WITH_REASON` as an option for each port that lifts a legacy-only behavior. For all three symbols in this task:

- The V2 control-plane has **no** active replacement for live exchange websockets (`binance_websocket`), live ingestor namespace (`ingest`), or the hybrid rule-based signal generator (`hybrid_rule_based_signals`).
- The V2 paper trainer is explicitly a placeholder; the trainer-bridge port is gated `BLOCKED_BY_TRAINER_PARITY`.
- Therefore declaring any of these "replaced by V2" would constitute `dropping_legacy_behavior_silently`, which is in the supervisor's `forbidden` list for this task.

The correct path is to preserve the legacy source (via copier extension or existing preserved tree) and re-run closure validation. No replacement claim is made and none is recorded as an approval token.
