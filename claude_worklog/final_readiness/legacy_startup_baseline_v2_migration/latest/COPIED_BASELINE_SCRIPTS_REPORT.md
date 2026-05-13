# COPIED_BASELINE_SCRIPTS_REPORT — Phase C

Source: legacy bot root under `$HOME/Desktop/AI BOT` (read-only). Destination: `v2/legacy_preserved/startup_baseline/`.

Tool: [claude_worklog/tools/copy_legacy_startup_baseline.py](../../../tools/copy_legacy_startup_baseline.py) (idempotent; re-runs only refresh changed files).

## Totals

| metric | value |
|---|---|
| files required by manifest | 39 |
| copied this turn | **33** |
| unchanged (already present, identical) | 0 |
| MISSING_IN_LEGACY_BASELINE (explicit blockers) | 6 |
| refused as secret-like path | 0 |
| flagged for secret-content review | 0 |
| `safe_to_commit: true` count | 33 |
| total bytes copied | 6.2 MB |

Every copied file carries SHA256 + size + secret-heuristic scan in [copied_baseline_manifest.json](copied_baseline_manifest.json).

## Missing in legacy baseline (do not silently ignore — flagged here)

| missing path | why this is OK / not OK |
|---|---|
| `scripts/check_services_detailed.sh` | optional dashboard helper; not on the critical migration path |
| `rl/__init__.py` | rl package may use namespace packages; not strictly required to port the modules themselves |
| `trading/__init__.py` | same — namespace package |
| `requirements-dev.txt` | optional dev requirements; will be reconstructed for V2 separately |
| `pyproject.toml` | legacy uses `requirements.txt` + `setup.py` style; not strictly required |
| `setup.py` | not present in legacy root |

None of these blocks the migration: the actual logic-carrying scripts (ingestors, TA, feature pipeline, trainer, orchestrator, trader, portfolio monitors, paralysis detectors, universe validator, health probe, monitoring scripts, config) all copied successfully.

## Secret-content scan

All 33 files passed seven content heuristics with zero hits:

- `aws_access_key_like` (AKIA…)
- `hex_secret_64` (64-hex-char tokens)
- `private_key_block` (`BEGIN PRIVATE KEY` blocks)
- `binance_api_key_assignment` (`BINANCE_API_KEY = '…'` literal assignments)
- `binance_secret_assignment` (`BINANCE_SECRET = '…'`)
- `coinapi_key_assignment` (`COINAPI_KEY = '…'`)
- `telegram_token_assignment` (`TELEGRAM_BOT_TOKEN = '\d+:…'`)

This is a heuristic, not a guarantee: the operator must still apply judgment before pushing if these files have ever held sensitive constants. Path-level exclusions also reject `.env`, `.env.*`, `credentials*`, `secrets*`, `*api_keys*`, `*.pem`, `*.p12`, `id_rsa*`.

## Per-file copy summary (33 files preserved)

The full SHA256 + sizes are in [copied_baseline_manifest.json](copied_baseline_manifest.json). The destination tree mirrors the legacy structure:

```
v2/legacy_preserved/startup_baseline
├── config.py
├── feature_pipeline.py
├── ingest
│   ├── live_binance.py
│   ├── live_binance_liquidations.py
│   ├── live_coinank.py
│   ├── live_coinank_global_aggregator.py
│   ├── live_coinapi_v1.py
│   ├── live_coinapi_wsds.py
│   ├── live_kucoin.py
│   ├── live_technical_analysis.py
│   ├── liquidation_bridge.py
│   ├── liquidation_levels_engine.py
│   └── realtime_price_provider.py
├── monitor_portfolio_asjad.py
├── monitor_portfolio_primary.py
├── monitor_system_memory.py
├── ohlcv_resampler_hotfix.py
├── requirements.txt
├── rl
│   ├── hybrid_trainer.py
│   └── orchestrator_worker.py
├── scripts
│   ├── health_probe.py
│   ├── memory_monitor.py
│   ├── monitor_dashboard.sh
│   ├── monitor_trainer_predictions.py
│   ├── paralysis_detectors.py
│   ├── start_all_services_production.sh
│   ├── stop_all_services_production.sh
│   ├── stop_ingestors.sh
│   └── validate_symbol_universe_data.py
├── system_telegram_monitor.py
├── trading
│   ├── trader-asjad.py
│   └── trader.py
└── vpn_monitor.py
```

## What the manifest enables

The manifest's per-file `sha256` is the **stable input contract** for every future `claude_port_v2_*_from_legacy_baseline` worker: that worker's `LEGACY_BASELINE_ANALYSIS.md` must cite the same SHA so reviewers can detect drift between the analysis and the actual source it was written against. Codex reviews fail when the cited SHA does not match.

## Forbidden operations during this phase

- No edits to the legacy bot root — verified: this script opens source as read-only `.read_bytes()`.
- No copies of `.env`, secrets, credentials, private keys — verified by path filter.
- No Redis writes — this script has no Redis client import.
- No exchange/leverage/margin codepath — this script has no exchange SDK import.
- Live gate untouched — this script does not touch any approval token.
