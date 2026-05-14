# Resolve Remaining Unresolved Local Imports — Report

Task id: `claude_resolve_remaining_unresolved_local_imports`
Lane: `shutdown_readiness_remediation`
Managed by: `codex_legacy_shutdown_readiness_takeover`
Live gate: `blocked_human_only` (unchanged)
Live symbols: `[]` (unchanged)
Final approval token: `absent` (NOT created by this task)
Redis trim approval token: `absent` (NOT created by this task)

## Scope

Resolve or explicitly classify the three remaining genuine unresolved local imports flagged in the full RL/risk/trainer/trader dependency closure:

- `ingest`
- `binance_websocket`
- `hybrid_rule_based_signals`

Source of truth for "genuine unresolved" classification:
`claude_worklog/final_readiness/legacy_rl_risk_trainer_trader_closure/latest/FULL_TRAINER_TRADER_DEPENDENCY_CLOSURE.md`, section "Remaining unresolved local imports (after expansion)", lines 43–52.

The other unresolved entries called out in the same section (`__future__`, `atexit`, `faulthandler`, `statistics`, `secrets`) are stdlib modules the closure scanner's `STDLIB_GUESS` set does not yet enumerate — that is scanner-precision noise and is **not** in scope for this task. The 4 genuine externals (`cloudpickle`, `gymnasium`, `dotenv`, `urllib3`) are pip-distribution packages and were already classified `EXTERNAL_DEP_MISSING` in the closure review — also not in scope here.

## Findings (per symbol)

### 1. `ingest` — namespace package, ALREADY PRESERVED — needs closure-scanner cross-link

- Importers identified inside the runtime closure tree: trader/RL modules use `from ingest import …` (e.g. `from ingest.live_binance import …`, `from ingest.realtime_price_provider import …`).
- Source state: 11 `ingest/*.py` files are preserved under `v2/legacy_preserved/startup_baseline/ingest/` with SHA256s recorded in `claude_worklog/final_readiness/legacy_startup_baseline_v2_migration/latest/copied_baseline_manifest.json`. See LEGACY_BASELINE_ANALYSIS for the full SHA-cited table.
- Gap: the full-runtime closure scanner traversed `v2/legacy_preserved/full_runtime_closure/` only; it did not look across into the sibling `v2/legacy_preserved/startup_baseline/ingest/` tree, so it flagged `from ingest import …` as unresolved even though the source is preserved.
- Classification: **CLOSURE_TOOL_CROSS_LINK_REQUIRED** (not `LOCAL_IMPORT_UNRESOLVED`, not `LEGACY_ONLY_DEP_REPLACED_BY_V2_WITH_REASON`).
- Required remediation (no source movement, no new copies):
  1. Closure-scanner config must add an additional search root: `v2/legacy_preserved/startup_baseline/`.
  2. The closure JSON must record the namespace cross-link explicitly (see `full_runtime_closure_extension_delta.json`, field `additional_preserved_search_roots`).
- Source preservation safety: legacy `ingest/` files remain in `legacy_reference/ingest/` (read-only) and in the preserved tree. No edit, no copy, no deletion required by this task.

### 2. `binance_websocket` — top-level helper, source found in legacy_reference — needs copier-scope extension

- Importers identified inside the closure: `rl/hybrid_trainer.py` line 538 (`from binance_websocket import BinanceWebSocketHelper`) and `rl/CRITICAL_HEDGE_AND_PORTFOLIO_FIX.py` line 33 (same import).
- Source located at `legacy_reference/binance_websocket.py`:
  - SHA256: `aef4e1d6ac7b994cb96f2521b8bcc9810cd9f75a19f11ba4ed85f690133deb26`
  - Size: 21698 bytes, 610 lines.
- Manifest state: this file is **not** present in `claude_worklog/final_readiness/legacy_rl_risk_trainer_trader_closure/latest/full_runtime_copied_source_manifest.json` and **not** present in `claude_worklog/final_readiness/legacy_startup_baseline_v2_migration/latest/copied_baseline_manifest.json`. Verified by grep over both files; 0 occurrences of `binance_websocket.py`.
- Classification: **SOURCE_FOUND_COPIER_EXTENSION_REQUIRED**. This is *not* `LEGACY_ONLY_DEP_REPLACED_BY_V2_WITH_REASON`; the helper is a live legacy runtime dependency of the rl/ tree and must be preserved for parity reconstruction.
- Required remediation: copier subsystem (phase B `full_runtime_closure_copy`) must include this top-level helper in its next run. Target path: `v2/legacy_preserved/full_runtime_closure/binance_websocket.py`. SHA evidence is in the extension delta file emitted alongside this report.

### 3. `hybrid_rule_based_signals` — top-level helper, source found in legacy_reference — needs copier-scope extension

- Importer identified inside the closure: `rl/hybrid_trainer.py` line 56819 (`from hybrid_rule_based_signals import HybridRuleBasedSignalGenerator`). Also referenced from `legacy_reference/debug_rule_signals.py` (debug/diagnostic, not runtime).
- Source located at `legacy_reference/hybrid_rule_based_signals.py`:
  - SHA256: `c2ad008a489ca633ffa198afbe106c45ce20dca70f15aa91922e0dca1c41971f`
  - Size: 18754 bytes, 435 lines.
- Manifest state: not present in either `full_runtime_copied_source_manifest.json` or `copied_baseline_manifest.json`. Verified by grep — 0 occurrences.
- Classification: **SOURCE_FOUND_COPIER_EXTENSION_REQUIRED**. Not `LEGACY_ONLY_DEP_REPLACED_BY_V2_WITH_REASON` — V2 paper-mode trainer is a momentum-style placeholder and explicitly does not yet provide a parity replacement for the hybrid rule-based signal generator. Preserving the source is necessary so the trainer-bridge port (currently `BLOCKED_BY_TRAINER_PARITY` / `WRAPPER_NOT_LEGACY_HYBRID_PARITY`) has full visibility.
- Required remediation: copier extension. Target path: `v2/legacy_preserved/full_runtime_closure/hybrid_rule_based_signals.py`.

## Dependency closure status (post-classification)

| Package | Closure status (after this task's classification) | Notes |
|---|---|---|
| `risk/` | `DEPENDENCY_CLOSURE_COMPLETE` | unchanged from closure review |
| `services/`, `utils/` | `DEPENDENCY_CLOSURE_COMPLETE` | unchanged |
| `trading/` | `DEPENDENCY_CLOSURE_REMEDIATION_SPECIFIED` | depends on `ingest` cross-link + binance_websocket copier add — both specified, both pending copier re-run |
| `rl/` | `DEPENDENCY_CLOSURE_REMEDIATION_SPECIFIED` | depends on `binance_websocket` + `hybrid_rule_based_signals` copier add + `ingest` cross-link — all specified, all pending copier re-run |

No symbol in this task is classified `LEGACY_ONLY_DEP_REPLACED_BY_V2_WITH_REASON`. The closure review explicitly invited that classification as an option, but the evidence rules it out for all three: each helper is a live legacy runtime dependency with no equivalent V2 replacement (the V2 paper trainer is a placeholder, not a parity rewrite of `rl/hybrid_trainer.py`).

## Closure validation re-run specification

The exact closure validation required after the copier re-applies and the cross-link is recorded:

1. Copier (phase B `full_runtime_closure_copy`) re-runs with extended scope per `full_runtime_closure_extension_delta.json`. Expected new records:
   - `legacy_rel_path: "binance_websocket.py"` → `v2/legacy_preserved/full_runtime_closure/binance_websocket.py`, sha256 `aef4e1d6ac7b994cb96f2521b8bcc9810cd9f75a19f11ba4ed85f690133deb26`, size 21698, status `COPIED`.
   - `legacy_rel_path: "hybrid_rule_based_signals.py"` → `v2/legacy_preserved/full_runtime_closure/hybrid_rule_based_signals.py`, sha256 `c2ad008a489ca633ffa198afbe106c45ce20dca70f15aa91922e0dca1c41971f`, size 18754, status `COPIED`.
2. Closure scanner re-runs with `additional_preserved_search_roots = ["v2/legacy_preserved/startup_baseline/", "v2/legacy_preserved/full_runtime_closure/"]`.
3. Expected post-rerun assertion in `full_trainer_trader_dependency_closure.json`:
   - `files_with_unresolved_imports` drops by the count of files whose only unresolved local imports were in the set `{ingest, binance_websocket, hybrid_rule_based_signals}` (scanner-precision stdlib noise excluded — those remain until `STDLIB_GUESS` is extended in a separate scanner-precision task).
   - No file in the rl/ or trading/ tree has any of `ingest`, `binance_websocket`, `hybrid_rule_based_signals` in its `unresolved_local_imports` list.
4. Test/verification: no V2 runtime test is required for this task — the change is to preserved-source tree and to the closure scanner config only. The V2 paper trainer does not consume these legacy helpers in paper mode. Classification for this task's testing requirement: **V2_ENV_BLOCKED** (no V2-side import path is gained by this task; the helpers remain legacy-only sources preserved for parity reconstruction by the trainer-bridge port).

## Public payload / runtime-facing impact

- Public payloads (operator runtime, GUI, redis writes): **NONE**. This task does not touch any runtime payload, any V2 service, any Redis writer path, any GUI route, or any approval token.
- Live gate: unchanged `blocked_human_only`.
- Live symbols: unchanged `[]`.
- Old Redis: unchanged (zero writes).
- Exchange state, leverage, margin mode: unchanged (zero actions).

## GO/NO-GO

GO for the `codex_legacy_shutdown_readiness_takeover` next lane step, conditional on the copier subsystem running the extension delta and the closure scanner re-running with the extended search-root config. The remediation is specified, evidence-bound, and reversible. No live-trading or exchange-state risk introduced. See companion `_GO_NO_GO.md` file for the line.

## Evidence pointers

- `legacy_reference/binance_websocket.py` — sha256 `aef4e1d6ac7b994cb96f2521b8bcc9810cd9f75a19f11ba4ed85f690133deb26`, 21698 bytes (recomputed this task).
- `legacy_reference/hybrid_rule_based_signals.py` — sha256 `c2ad008a489ca633ffa198afbe106c45ce20dca70f15aa91922e0dca1c41971f`, 18754 bytes (recomputed this task).
- `claude_worklog/final_readiness/legacy_startup_baseline_v2_migration/latest/copied_baseline_manifest.json` — 11 `ingest/*.py` records with SHA256s (see LEGACY_BASELINE_ANALYSIS for the table).
- `claude_worklog/final_readiness/legacy_rl_risk_trainer_trader_closure/latest/full_runtime_copied_source_manifest.json` — confirmed absence (0 occurrences) of `binance_websocket.py` and `hybrid_rule_based_signals.py`.
- `claude_worklog/final_readiness/legacy_rl_risk_trainer_trader_closure/latest/FULL_TRAINER_TRADER_DEPENDENCY_CLOSURE.md` lines 43–52 — original closure-review classification of the three symbols.
- Importer citations:
  - `legacy_reference/rl/hybrid_trainer.py:538` — `from binance_websocket import BinanceWebSocketHelper`
  - `legacy_reference/rl/hybrid_trainer.py:56819` — `from hybrid_rule_based_signals import HybridRuleBasedSignalGenerator`
  - `legacy_reference/rl/CRITICAL_HEDGE_AND_PORTFOLIO_FIX.py:33` — `from binance_websocket import BinanceWebSocketHelper`
