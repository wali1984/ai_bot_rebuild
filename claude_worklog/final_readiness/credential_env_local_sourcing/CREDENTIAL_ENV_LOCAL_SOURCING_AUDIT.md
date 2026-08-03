# Credential Sourcing Audit + Fix — All Scripts Use API Keys From `env.local`

Generated EST: 2026-06-01T18:10:00-0400
Generated UTC: 2026-06-01T22:10:00Z
LIVE_GATE: blocked_human_only | live_symbols: [] | writes_legacy_redis: false

## Ask
> Ensure all scripts use API keys in `env.local`.

## Root cause found (raw evidence)
- The systemd `--user` units that run the V2 paper/shadow workers set **no
  `EnvironmentFile`** — only `PYTHONPATH` + `LIVE_GATE`:
  - `systemctl --user show ai-bot-v2-native-ingestors-live-loop -p Environment`
    -> `Environment="PYTHONPATH=..." LIVE_GATE=blocked_human_only`
  - same for `ai-bot-v2-feature-pipeline-native-loop` and peers.
- `claude_worklog/tools/v2_production_replacement_runtime_guard.py:120` launches
  probe commands with a **scrubbed env** (`{"PYTHONPATH","PATH"}`).
- `v2/backend/app/settings.py` deliberately does not read dotenv ("Secrets are
  injected via env at process start").
- Net effect: any credential-gated worker (CoinAnk, CoinAPI, TokenMetrics,
  LunarCrush, Nansen, Arkham) ran with **no API key in `os.environ`**. Only
  Binance public (keyless) endpoints worked.

## Credential landscape (names only — values never read)
| File | Keys | Role |
|---|---|---|
| `v2/.env.local` | 374 | Canonical operator file. Has BINANCE_*, COINANK_API_KEY, COINAPI_API_KEY, TOKENMETRICS_API_KEY, ARKHAM_API_KEY, COINGLASS_API_KEY, COINGECKO_API_KEY, TELEGRAM_*, + 360 tuning vars |
| `.local_secrets/alternative_data.env` | 5 | LUNARCRUSH_API_KEY, NANSEN_API_KEY, ARKHAM_API_KEY, ALT_DATA_* |
| `.local_secrets/live_credentials.env` | 15 | Back-compat subset (what `safe_env_loader` previously defaulted to) |

## Fix implemented
1. `v2/backend/app/services/safe_env_loader.py`
   - Added `ENV_LOCAL_PATH` (`v2/.env.local`) as the **canonical primary**
     source, with `LAYERED_CREDENTIAL_PATHS = (env.local, alternative_data.env,
     live_credentials.env)` — first file with a non-empty value wins.
   - Added `bootstrap_process_env()` which binds **only** data-provider API
     keys (`DATA_PROVIDER_CREDENTIAL_NAMES`) into `os.environ` (no-overwrite),
     returning a **redacted** presence report (`values_exposed: false`).
2. `v2/backend/app/cli/__init__.py`
   - Calls `bootstrap_process_env(apply=True)` on package import, so **every**
     CLI worker module run (incl. the systemd loops) auto-loads the
     data-provider keys from `env.local` — no per-script edits, no systemd
     `EnvironmentFile` changes required.

## Safety posture (intentional exclusions)
The auto-bootstrap binds data-provider keys ONLY:
`COINANK_API_KEY, COINAPI_API_KEY, TOKENMETRICS_API_KEY, ARKHAM_API_KEY,
COINGLASS_API_KEY, COINGECKO_API_KEY, LUNARCRUSH_API_KEY, NANSEN_API_KEY,
ALPHAVANTAGE_API_KEY`.

Deliberately **NOT** auto-bound (preserves the default-blocked posture):
- Exchange private keys (`BINANCE_API_KEY/SECRET`, `*_ASJAD`, `*_BROTHER`,
  `*_FUT_*`, testnet) — only the operator-gated canary/executor may bind these.
- Behaviour/risk flags (`LIVE_TRAINING_ENABLED`, `TRADE_MODE`, `MAX_LEVERAGE`,
  `ALLOW_LEVERAGE_SET`, `ENABLE_*` ...) — must flow through versioned config admin.
- Messaging enablement (`TELEGRAM_ENABLED`, channel IDs) — operator-gated.

## Verification (raw)
Command:
`python3 -c "import v2.backend.app.cli as c; print(c._CREDENTIAL_BOOTSTRAP_REPORT)"`
- `bound_count = 8` -> COINANK/COINAPI/TOKENMETRICS/ARKHAM/COINGLASS/COINGECKO
  (from `.env.local`), LUNARCRUSH/NANSEN (from `alternative_data.env`).
- `absent_names = ["ALPHAVANTAGE_API_KEY"]` (not present in any file — honest).
- `values_exposed = false`.
- LunarCrush client end-to-end: `safe_load_api_key()` returns present after
  import; client builds `Authorization: Bearer <key>` header
  (`lunarcrush_client.py:35,438-445`).
- Import smoke test: native_ingestors / feature_pipeline / lunarcrush / nansen
  CLIs all import OK with the bootstrap; feature pipeline still fresh
  (real=25 missing=0).

## Residual (separate from credential sourcing)
Keys now reach workers, but some ingestors still need real authenticated
fetchers / scheduling before their data appears (tracked in the data
completeness audit):
- `v2_coinank_and_liquidation_bridge` is a public-REST stub — it never sends an
  `apikey` header, so it does not yet consume `COINANK_API_KEY`.
- LunarCrush / Nansen / Arkham ingestor CLIs are not scheduled as systemd
  timers yet (clients are correct; they just need to run).
- `ALPHAVANTAGE_API_KEY` is absent from all credential files.
