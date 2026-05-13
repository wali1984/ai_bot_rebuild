# MISSING_V2_RUNTIME_WORKERS

Focused list of V2 runtime workers that have **no real implementation** in the V2 codebase.

## Tier 0 — placeholder service files exist, logic absent

| worker | v2 file | what's there | what's missing |
|---|---|---|---|
| signal_publisher | `v2/backend/app/services/signal_publisher.py` | 1-line `# placeholder` comment | the entire publisher: subscribing to OrchestratorDecisionRecord stream, emitting signal_lineage records to a V2 stream and to the public payload |
| monitor_runner | `v2/backend/app/services/monitor_runner.py` | 1-line `# placeholder` comment | the entire Monitor Center backend: enumerate scripts, run each, capture last_run/last_success/last_failure/metrics/alerts, write per-script status |
| config_admin_manager | `v2/backend/app/api/v1/accounts.py`, `governance.py`, `claude_admin.py` | OPTIONS metadata only; no handler bodies | runtime config CRUD; staged value + approval workflow; rollback; risk classification per setting |
| admin_ai_backend | `v2/backend/app/api/v1/claude_admin.py` | skeleton OPTIONS shim | Claude API integration; evidence-cited query answers; the safety statement enforcement preventing dangerous gate flips |

## Tier 1 — no file exists, must be built from scratch

| worker | why it matters | minimum scope |
|---|---|---|
| market_ingestor | without it, V2 has no real-time price feed it owns. paper online runtime currently fetches Binance public REST on each loop iteration, which is acceptable for paper mode but is not a durable ingestor. | Binance public klines + mark price + funding into a V2-namespaced stream/db, with health/freshness metrics |
| coinank_liquidation_bridge | CoinAnk-style market intelligence is a stated objective for the GUI. Today only a symbol-resolver exists. | liquidation feed, funding, OI, long/short, into `coinank_market_intelligence_status.json` |
| account_position_monitor | with legacy shut down, V2 has zero real account-state evidence. paper-mode simulations are NOT account evidence. | Binance read-only account & positions endpoints; freshness label; classify as `MISSING_CREDENTIALS` when no read-only keys, never `paper-only as truth` |
| pnl_accounting_worker | PnL today is paper-only simulation inline in paper online runtime. No durable journal. | append-only PnL journal; daily reconciliation; equity timeline |

## Tier 2 — library exists but no standalone runnable worker

These six are the **highest-leverage P0 work**: lifting library code into independently-runnable CLI workers immediately makes V2 less dependent on the embedded paper online runtime loop.

| worker | library | what to do |
|---|---|---|
| feature_snapshot_builder | `v2/backend/app/services/feature_snapshots/service.py` | wrap as `python3 -m v2.backend.app.cli.feature_snapshot_builder` that reads market state, builds snapshot, writes public payload |
| orchestrator_adapter | `v2/backend/app/composition/orchestrator_decision/runtime.py` | CLI worker consuming trainer_prediction stream, emitting OrchestratorDecisionRecord stream + payload |
| risk_gateway_runtime_worker | `v2/backend/app/composition/risk_gateway/runtime.py` | CLI worker consuming OrchestratorDecisionRecord, emitting RiskDecisionRecord with always-`blocked_human_only` gate + payload |
| paper_execution_worker | `v2/backend/app/composition/paper_execution_ledger/runtime.py` | CLI worker consuming RiskDecisionRecord, simulating fills, emitting PaperExecutionLedgerEntry |
| execution_ledger_worker | `v2/backend/app/composition/paper_execution_ledger/runtime.py` | CLI worker writing append-only ledger jsonl + tail payload |
| replay_backtest_runner | `v2/backend/app/composition/replay_backtest_runner/runtime.py` | CLI worker accepting a replay window, producing step records + summary |

## What is NOT missing (do not duplicate)

- `paper_online_runtime` — full standalone CLI exists; needs **restart**, not rebuild.
- `paper_shadow_observation` — read-only observer; needs **restart**.
- All Tier 2 libraries — the logic is already correct and tested; only CLI wrappers are missing.

## Frozen-legacy dependency flag

| worker | risk |
|---|---|
| trainer_bridge | trainer_parity composition observes legacy Redis streams that no longer have a producer. Until a real V2 trainer service (or a subprocess wrapper around a frozen legacy trainer binary) exists, "trainer-parity mode" produces `MISSING_RUNTIME_EVIDENCE`. paper online runtime's inline momentum wrapper is the only non-blocked path. |
