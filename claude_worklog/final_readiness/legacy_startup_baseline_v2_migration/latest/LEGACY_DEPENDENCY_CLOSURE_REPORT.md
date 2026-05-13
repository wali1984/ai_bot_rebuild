# LEGACY_DEPENDENCY_CLOSURE_REPORT — Phase D

Static dependency analysis of every file in `v2/legacy_preserved/startup_baseline/`.

## Tool

[v2/backend/app/cli/legacy_dependency_closure.py](../../../../v2/backend/app/cli/legacy_dependency_closure.py) (AST-based scanner using py3 `ast` module; tests at [v2/backend/tests/unit/cli/test_legacy_dependency_closure.py](../../../../v2/backend/tests/unit/cli/test_legacy_dependency_closure.py)). **7 of 7 tests pass.**

Run via:

```text
.venv/bin/python3 -m v2.backend.app.cli.legacy_dependency_closure \
  --root v2/legacy_preserved/startup_baseline --all
```

Full per-file JSON output: [legacy_dependency_closure_matrix.json](legacy_dependency_closure_matrix.json).

## Aggregate totals

| metric | value |
|---|---|
| files analyzed | 32 |
| files with parse error | 0 |
| files with Redis usage | **20** (~63%) |
| files with exchange API usage | **16** (~50%) |
| files with subprocess usage | 5 |
| files with config-module import | **25** (~78%) |
| files with unresolved local imports | 21 |

## External dependency profile (count = number of files using)

| count | external module | notes |
|---|---|---|
| 19 | `redis` | Pervasive. V2 ports must **read-only** against legacy Redis namespace and write only V2-namespaced streams. |
| 6 | `requests` | HTTP — fine for read-only public REST calls in V2. |
| 5 | `psutil` | Process inspection — used by monitoring scripts. |
| 5 | `websockets` | Live exchange feeds; V2 may use read-only WS. |
| 4 | `binance` | python-binance SDK; V2 must wrap as read-only only (the P2 stubs raise `BLOCKED_GATE_NOT_APPROVED` on mutation). |
| 4 | `aiohttp` | Async HTTP — used by CoinAPI ingestors. |
| 2 | `numpy` | Feature pipeline, technical analysis. |
| 2 | `torch` | Trainer only. |
| 2 | `ccxt` | Exchange abstraction — wrap as read-only only in V2. |
| 1 | `pynvml` | NVIDIA GPU telemetry — monitoring. |
| 1 | `stable_baselines3` | RL trainer. |

`ta` / `TA-Lib` / `talib` are NOT detected as imports — the legacy `live_technical_analysis.py` may use them by another import name (e.g., `from ta import ...` under the `KNOWN_EXTERNAL` set as `ta`, which the scanner does recognize but no file in the copied set imports it directly). Verify before P0 feature_pipeline_and_ta worker implementation.

## Unresolved local imports (top 8)

These are top-level module names imported by the preserved scripts but **not present** in `v2/legacy_preserved/startup_baseline/`. They are local-but-uncopied helpers that the ports will need either copied additionally or replaced with V2 equivalents.

| missing local module | first seen in |
|---|---|
| `telegram_alerts` | `vpn_monitor.py` |
| `config_accounts` | `trading/trader.py` |
| `dotenv` | `trading/trader.py` (external — `python-dotenv`; classifier missed it) |
| `risk` | `trading/trader.py` |
| `secrets` | `trading/trader.py` (likely the stdlib `secrets`; classifier missed because of name shadowing risk) |
| `services` | `trading/trader.py` |
| `urllib3` | `trading/trader.py` (external) |
| `utils` | `trading/trader.py` |

**Action items for the next worker tasks** (already encoded in the new P0 task descriptors created in Phase H):

- `claude_port_v2_market_ingestor_from_legacy_baseline` must verify and copy any uncovered local helpers required by the ingestor scripts in the preserved baseline before declaring closure complete.
- `claude_port_v2_trader_fail_closed_stub_from_legacy_trader` (P2) must NOT attempt to port the trader's `risk`/`services`/`config_accounts`/`utils` helpers as-is — those are trade-side dependencies that should be replaced with V2-native fail-closed gates.

## Per-script Redis/exchange/subprocess use (selected)

See full JSON for the complete table. Notable observations:

- 20 of 32 files use Redis. The V2 ports must classify each as **read-only reference** (consumer of legacy stream for parity) or **V2-namespaced writer** (writing only `v2:*` keys). The orchestrator-enforced `LEGACY_BASELINE_ANALYSIS.md` requires the worker to document each Redis key's role explicitly.
- 16 of 32 files touch exchange API. Of these, the ingestor and feature-pipeline files are read-only; the two trader files (`trading/trader.py`, `trading/trader-asjad.py`) are the live trade-side code. **V2 must never start the trader files**; only the P2 fail-closed stub may exist.
- 5 files use subprocess (mostly monitoring scripts shelling out to nvidia-smi, redis-cli for status checks, etc.). The V2 ports may reuse these patterns but must NOT shell to anything that mutates legacy state.

## What this enables for the next P0 worker

The new task descriptor `claude_port_v2_market_ingestor_from_legacy_baseline` (Phase H) requires the sub-agent to:

1. Read the relevant ingestor files from `v2/legacy_preserved/startup_baseline/ingest/live_binance.py`, `live_kucoin.py`, `realtime_price_provider.py`, `live_coinapi_wsds.py`, `live_coinapi_v1.py`
2. Run the closure scanner against the chosen entry-point set and confirm every transitive local dependency is present (or explicitly documented as a known-blocker)
3. Cite the SHA256 from `copied_baseline_manifest.json` for each preserved source
4. Produce `LEGACY_BASELINE_ANALYSIS.md` + `legacy_behavior_mapping.json` before any V2 implementation code is written
