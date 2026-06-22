# V2 Full Copied Runtime and Trading Platform Restart — Symbol-Drift Closure Report

- **Task ID**: `v2_full_copied_runtime_and_trading_platform_restart`
- **Generated**: 2026-05-26T18:30:00Z
- **Git HEAD**: 10513bbe0517fd81c9c87e4672bb15486a083c02
- **GO/NO-GO**: `V2_FULL_COPIED_RUNTIME_AND_TRADING_PLATFORM_RESTART_BLOCKED`

> Honest verdict: the symbol-drift portion of the Codex 5.5 punch list is now
> closed, but the full-restart `_READY` marker is intentionally withheld. The
> standing instruction "Do not call V2 full rebuild ready while copied
> components are not running" applies — `liquidation_bridge.py` and
> `liquidation_levels_engine.py` are not yet wrapped in dedicated systemd
> services, and the rendered trading-platform UI evidence + trainer-role
> relabel remain in the residual-blocker list.

## What this turn changed

### 1. Source-level 3-symbol / BTC-only defaults: closed

All 13 V2 source files Codex 5.5 flagged as still holding hard-coded
non-smoke defaults have been routed through the dynamic universe
resolver `v2/backend/app/services/v2_symbol_runtime_universe.py:resolve_symbols`.

| File | Type | Before | After |
|------|------|--------|-------|
| `v2_alt_data_symbol_universe_scoring.py:194` | fn default | `("BTCUSDT","ETHUSDT","SOLUSDT")` | `None` → `resolve_symbols(explicit=symbols, smoke_test=smoke_test)` |
| `v2_full_observation_builder_status.py:33` | argparse | `"BTCUSDT,ETHUSDT,SOLUSDT"` | `None` + `--smoke-test` flag |
| `v2_nansen_altdata_ingestor.py:167` | argparse | `"BTCUSDT,ETHUSDT,SOLUSDT"` | `None` + `--smoke-test` flag |
| `v2_alt_data_symbol_candidate_publisher.py:45` | constant | `("BTCUSDT","ETHUSDT","SOLUSDT")` | `_resolve_default_symbols()` at module load via `resolve_symbols(smoke_test=False)` |
| `v2_feature_pipeline_native.py:59` | argparse | `"BTCUSDT"` | `None` → resolver first symbol + `--smoke-test` |
| `v2_market_ingestor.py:231` | argparse | `"BTCUSDT"` | `None` → resolver first symbol + `--smoke-test` |
| `v2_alternative_data_status.py:145, 173` | fn default + argparse | `("BTCUSDT","ETHUSDT","SOLUSDT")` | `None` → resolver + `--smoke-test` |
| `v2_website_redis_bridge_status.py:54` | fn default | `("BTCUSDT","ETHUSDT","SOLUSDT")` | `None` → resolver |
| `v2_lunarcrush_altdata_ingestor.py:159` | argparse | `"BTCUSDT,ETHUSDT,SOLUSDT"` | `None` + `--smoke-test` flag |
| `readonly_market_exchange_data_plane.py:19` | argparse | `"BTCUSDT"` | `None` → resolver first symbol + `--smoke-test` |
| `native_runtime_migration/safety.py:43` | constant label | `V2_NATIVE_ACTIVE_SYMBOLS = ("BTCUSDT","ETHUSDT","SOLUSDT")` | Renamed semantically to `V2_NATIVE_INITIAL_BRIDGE_SYMBOLS`; backwards-compat alias preserved; `v2_native_currently_active_symbols()` helper added |
| `native_runtime_migration/v2_paper_startup_manifest.py:33, 703` | constant + emitted JSON | `"currently_active_symbols": list(V2_NATIVE_ACTIVE_SYMBOLS)` (3 symbols) | Emits `currently_active_symbols` via `resolve_symbols()` (≥25 symbols by default) + adds `initial_bridge_migration_symbols` + `currently_active_symbols_source` + `currently_active_symbol_count` |

The resolver itself was already in place at `v2/backend/app/services/v2_symbol_runtime_universe.py`
and provides:

- 25-symbol baseline (`BASELINE_25_SYMBOLS`) — production default;
- explicit smoke-test opt-in via `smoke_test=True` argument OR
  `V2_SYMBOL_PROFILE=smoke_test` environment variable;
- fail-closed on a literal `["BTCUSDT","ETHUSDT","SOLUSDT"]` explicit
  list without an opt-in (`raise ValueError("V2_SYMBOL_DEFAULT_DRIFT: …")`).

### 2. Regression coverage

Added [v2/backend/tests/unit/cli/test_v2_full_copied_runtime_default_symbol_drift.py](v2/backend/tests/unit/cli/test_v2_full_copied_runtime_default_symbol_drift.py)
with 18 tests:

- **12 parameterized source-string drift guards** (one per patched file)
  asserting the forbidden hard-coded default is gone and the resolver
  wiring or `--smoke-test` flag is present.
- **6 behavior tests**:
  - resolver returns ≥25 symbols by default;
  - resolver rejects explicit BTC/ETH/SOL triple without smoke opt-in;
  - resolver accepts opt-in via flag;
  - resolver accepts opt-in via environment variable;
  - `build_dynamic_symbol_paper_runtime_coverage()` emits dynamically
    resolved `currently_active_symbols` (≥25) plus `initial_bridge_migration_symbols`
    plus `currently_active_symbols_source` provenance string;
  - `safety` module exposes the initial-bridge constant and dynamic helper.

One existing test (`test_v2_alt_data_symbol_universe_scoring.py::test_run_once_reads_no_v2_paper_or_v2_risk_keys_during_full_pipeline`)
needed `smoke_test=True` added to acknowledge its explicit BTC/ETH/SOL
test fixture — the resolver now fails closed on that triple without an
opt-in, which is the desired Codex-blocker behavior.

### 3. Test totals

| Suite | Tests | Result |
|-------|-------|--------|
| New symbol-drift regression suite | 18 | 18 passed |
| Prior dynamic-runtime symbol-defaults suite | 4 | 4 passed |
| Patched-module test suites (11 files) | 171 | 171 passed |
| Native-runtime migration consumer tests (6 files) | 65 | 65 passed |
| **TOTAL** | **258** | **258 passed, 0 failed** |

## What this turn explicitly did NOT do

- Did NOT call V2 full rebuild ready while liquidation copied
  components (`liquidation_bridge.py`, `liquidation_levels_engine.py`)
  are not wrapped in systemd services.
- Did NOT re-dispatch completed tasks. The completed-task redispatch
  remediation Codex-passed earlier in this session
  (`V2_CLOSED_LOOP_COMPLETED_TASK_REDISPATCH_REMEDIATION_CODEX_PASS`).
- Did NOT call the checkpoint shape pass "model ready". The
  checkpoint-promotion shape-contract torch-native remediation
  Codex-passed earlier and is strictly a metadata-shape contract fix —
  no checkpoint is loaded, no model is adopted.
- Did NOT let the checkpoint-shape tasks distract from this runtime
  restart. Checkpoint-shape work is closed and isolated under its own
  readiness lane.
- Did NOT leave 3-symbol or BTC-only defaults in the modified files.
- Did NOT start raw old-Redis writers. The 11 currently-running
  copied-component lanes are all paper-only V2 wrappers that enforce
  the `v2:` Redis prefix.
- Did NOT restart legacy root, did NOT enable live or canary, did NOT
  approve legacy shutdown, did NOT approve Redis trim.

## Residual blockers (why GO_NO_GO = BLOCKED)

### A. `liquidation_bridge.py` and `liquidation_levels_engine.py` not yet wrapped

Both copied scripts exist at:

- `v2/legacy_preserved/startup_baseline/ingest/liquidation_bridge.py`
- `v2/legacy_preserved/startup_baseline/ingest/liquidation_levels_engine.py`

(and mirrored under `v2/legacy_owned_runtime/...`), but no dedicated
`ai-bot-v2-liquidation-bridge.service` /
`ai-bot-v2-liquidation-levels-engine.service` user systemd unit exists.
Wrapping them requires:

1. Audit each copied script for raw old-Redis writes (Codex flagged
   "Adapt old Redis writes to v2:* before starting any copied component").
2. Add `v2:` Redis prefix adapters where any non-v2: write is found.
3. Add new user-level systemd unit files (operator approval required).
4. Verify paper-only and that no exchange-mutation path is opened.

`live_binance_liquidations.py` is confirmed excluded — no service references
it; the only active liquidation lane is
`ai-bot-v2-liquidation-wss-paper-shadow.service` (public Binance WSS
forceOrder shadow only).

### B. Trading-platform UI rendered proof artifact missing

Codex 5.5 marked "Website is trading platform, not coding/report page"
as `PARTIAL` with "rendered proof of runtime/control-state coverage is
still missing". The frontend already has the right routes
(`/trader`, `/paper-trading`, `/risk-control`, `/monitor-center`,
`/market` per `v2/frontend/src/router.tsx`); what's missing is a
rendered evidence packet (screenshots + route coverage matrix +
control-state walkthrough) — a verification artifact, not a code change.

### C. Trainer role labeling in packet status

Codex 5.5 marked "Trainer bridge/parity mode is still described too
strongly as V2-native in packet status" as `FAIL`. This turn did not
touch any trainer-runtime packet files; that relabel must remain a
separate narrow task.

### D. Copied-runtime startup map proof

Codex 5.5 marked the copied-runtime startup map as having "inconsistencies
and wrappers counted as copied-script starts". A side-by-side proof
artifact (running copied safe scripts vs blocked raw copied scripts) needs
to be produced separately.

## Live-runtime health snapshot

- **56 active `ai-bot-v2-*` user services** post-reboot (supervisor,
  closed-loop workers x6, scheduler, watchdog, paper online runtime,
  feature pipeline native loop, native ingestors, orchestrator
  arbitration, liquidation WSS shadow, paper-shadow observation, etc.).
- **25+ timers firing on schedule** (8h war-room,
  autonomous-full-rebuild-self-healing-controller,
  autonomous-mission-backlog, closed-loop-executor + worker-pool +
  codex-review-runner, executive command center, codex governors, etc.).
- **Supervisor lock held by PID 3526** (alive since post-reboot
  2026-05-26T17:22:03Z).
- **`wma-audits.service` restart storm cleared**: `inactive (dead)`,
  `disabled`, restart-line delta over 60s after disable = 0 (vs. ~2/min
  before).
- **No system freeze risk** from the previously identified storm root
  cause.

## Safety invariants

- `live_gate = "blocked_human_only"`
- `live_symbols = []`
- `approves_live = false`
- `approves_canary = false`
- `approves_legacy_shutdown = false`
- `approves_redis_trim = false`
- `live_binance_liquidations_wrapped_in_service = false`
- legacy directory not modified, not started, not stopped
- no exchange-mutation call placed
- no Redis key written outside `v2:` prefix by any patched module
- no V2 runtime service restarted by this remediation
- no torch import added; no pickle deserialization added

## Path from BLOCKED to READY

To flip this lane to `_READY`, a future operator-approved turn must:

1. Audit + adapt `liquidation_bridge.py` and `liquidation_levels_engine.py`
   for `v2:` Redis namespace, then add their systemd unit files (paper-only,
   no live-binance-liquidations).
2. Produce rendered trading-platform UI evidence (screenshots + route
   coverage matrix).
3. Relabel trainer role in packet status as
   `copied/parity/baseline_bridge` (not `v2_native_readiness`).
4. Produce the side-by-side copied-runtime startup-map proof artifact.
5. Re-run Codex 5.5 review for `V2_FULL_COPIED_RUNTIME_AND_TRADING_PLATFORM_RESTART`.

This turn cleanly closes the **symbol-drift** sub-blocker. The remaining
sub-blockers above are scoped, named, and unambiguous.
