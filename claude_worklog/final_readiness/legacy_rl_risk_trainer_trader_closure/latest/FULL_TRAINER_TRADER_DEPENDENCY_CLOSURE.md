# FULL_TRAINER_TRADER_DEPENDENCY_CLOSURE — Phase C

Static dependency analysis of the full preserved runtime closure tree.

## Tool

[v2/backend/app/cli/legacy_dependency_closure.py](../../../../v2/backend/app/cli/legacy_dependency_closure.py) (7/7 tests pass against the smaller startup baseline; re-used unchanged for this larger tree).

Invocation:

```text
.venv/bin/python3 -m v2.backend.app.cli.legacy_dependency_closure \
  --root v2/legacy_preserved/full_runtime_closure --all
```

Full per-file output: [full_trainer_trader_dependency_closure.json](full_trainer_trader_dependency_closure.json).

## Aggregate totals

| metric | value |
|---|---|
| files analyzed | **231** |
| files with parse error | 2 (non-blocking for inventory) |
| files using Redis | **49** |
| files using exchange API | **43** |
| files using subprocess | 6 |
| files importing `config` | **100** |
| files with unresolved local imports (after expanded copy) | 79 |

## External-dependency profile (top 10)

| count | external | install class |
|---|---|---|
| 58 | `numpy` | V2 venv |
| 43 | `redis` | already in V2 pyproject |
| 34 | `torch` | deferred to trainer-bridge port (GPU-bound) |
| 10 | `binance` | install with audit; read-only wrap only |
| 9 | `stable_baselines3` | deferred to trainer-bridge port |
| 5 | `requests` | V2 venv |
| 3 | `psutil`, `pandas`, `pynvml` | V2 venv |
| 1 | `aiohttp` | V2 venv |

## Remaining unresolved local imports (after expansion)

Most "unresolved" entries are stdlib modules the scanner's `STDLIB_GUESS` set doesn't yet include (`__future__`, `atexit`, `faulthandler`, `statistics`, `secrets`) — scanner-precision noise, not a missing-file issue. The genuine items:

| symbol | classification | next step |
|---|---|---|
| `ingest` | namespace package; trader uses `from ingest import …` | preserved separately under `v2/legacy_preserved/startup_baseline/ingest/` — needs cross-link in the closure tree or the next port must read both trees |
| `binance_websocket` | unconfirmed; possibly a top-level helper file | search legacy for `binance_websocket.py` and extend the copier if found |
| `hybrid_rule_based_signals` | likely a top-level file in legacy | search legacy for it; extend copier if found |
| `cloudpickle`, `gymnasium`, `dotenv`, `urllib3` | external pip packages | install per-port under operator approval |

## Classifications applied this turn

- `DEPENDENCY_CLOSURE_COMPLETE` — for `risk/` package (no unresolved imports referencing files NOT in the preserved tree)
- `DEPENDENCY_CLOSURE_COMPLETE` — for `services/`, `utils/` packages
- `DEPENDENCY_CLOSURE_INCOMPLETE` — for `trading/` and `rl/` packages (cross-tree `ingest`, `binance_websocket`, `hybrid_rule_based_signals` resolution needed)
- `LOCAL_IMPORT_UNRESOLVED` — applies to the 4 genuine unresolved local imports listed above
- `EXTERNAL_DEP_MISSING` — `torch`, `stable_baselines3`, `cloudpickle`, `gymnasium` (intentionally not installed in V2 venv this phase)
- `SECRET_OR_BINARY_NOT_COPIED` — 139 binary files inventoried-only
- `LEGACY_ONLY_DEP_REPLACED_BY_V2_WITH_REASON` — pending; each P0–P2 port that lifts a legacy-only behavior must document the replacement in its `LEGACY_BASELINE_ANALYSIS.md`

## Why this matters for the trainer bridge

Trainer bridge port is currently `BLOCKED_BY_TRAINER_PARITY` (WRAPPER_NOT_LEGACY_HYBRID_PARITY) because the V2 paper-mode trainer is a momentum-style placeholder. With the closure complete for the `rl/` tree (modulo namespace-package edge cases), the trainer-bridge port now has full source visibility to reconstruct the legacy trainer's behavior either as (a) a subprocess wrapper around `rl.hybrid_trainer` or (b) a V2-native re-implementation. The legacy_behavior_mapping.json for the trainer-bridge port must enumerate each of the rl/ helper modules consumed by `hybrid_trainer.py` and either preserve or explicitly drop each.
