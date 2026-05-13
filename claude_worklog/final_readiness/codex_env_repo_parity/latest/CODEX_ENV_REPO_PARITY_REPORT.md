# Codex Env/Repo Parity And Missing Legacy Function Audit

Generated: 2026-05-13T22:29:50Z

Result: `CODEX_ENV_REPO_PARITY_AND_MISSING_LEGACY_FUNCTION_AUDIT_PASS`

## Environment Dependency Parity

- Tooling result: `PASS`
- Current Python: `/home/wali/Desktop/AI BOT REBUILD/.venv/bin/python3`
- Repo venv Python exists: `True`
- Repo venv pytest exists: `True`
- Current Python is repo venv: `True`
- Missing V2 runtime dependencies: `0`
- Missing V2 dev dependencies: `0`
- Missing legacy-reference dependencies: `0`

Dependency mismatch handling: mismatches are reported explicitly and are not hidden.

## Legacy/V2 Function Gap

- Category count: `17`
- Status counts: `{'BACKLOG_ONLY': 3, 'MIGRATED': 9, 'RUNNABLE': 3, 'WRAPPER_ONLY': 2}`
- Missing categories: `[]`
- Backlog-only categories: `['dynamic_margin_manager', 'adaptive_hedge_builder', 'market_regime_detector']`
- Backlog counted as migration: `False`

| Category | Status | Migration? | Next action |
| --- | --- | --- | --- |
| `feature_snapshot_builder` | `RUNNABLE` | `True` | keep runnable worker monitored and reviewed |
| `risk_gateway_runtime_worker` | `MIGRATED` | `True` | add or verify standalone worker wrapper and public payload |
| `paper_execution_worker` | `RUNNABLE` | `True` | keep runnable worker monitored and reviewed |
| `execution_ledger_worker` | `MIGRATED` | `True` | add or verify standalone worker wrapper and public payload |
| `signal_lineage_worker` | `MIGRATED` | `True` | add or verify standalone worker wrapper and public payload |
| `account_position_monitor` | `RUNNABLE` | `True` | keep runnable worker monitored and reviewed |
| `market_ingestor` | `MIGRATED` | `True` | add or verify standalone worker wrapper and public payload |
| `coinank_liquidation_bridge` | `WRAPPER_ONLY` | `False` | replace read-only wrapper with independent V2 worker when in P0/P1 scope |
| `trainer_bridge` | `WRAPPER_ONLY` | `False` | replace read-only wrapper with independent V2 worker when in P0/P1 scope |
| `orchestrator_adapter` | `MIGRATED` | `True` | add or verify standalone worker wrapper and public payload |
| `replay_worker` | `MIGRATED` | `True` | add or verify standalone worker wrapper and public payload |
| `config_manager` | `MIGRATED` | `True` | add or verify standalone worker wrapper and public payload |
| `admin_ai_backend` | `MIGRATED` | `True` | add or verify standalone worker wrapper and public payload |
| `live_execution_stub` | `MIGRATED` | `True` | add or verify standalone worker wrapper and public payload |
| `dynamic_margin_manager` | `BACKLOG_ONLY` | `False` | do not count backlog as migration; schedule dynamic_margin_manager |
| `adaptive_hedge_builder` | `BACKLOG_ONLY` | `False` | do not count backlog as migration; schedule adaptive_hedge_builder |
| `market_regime_detector` | `BACKLOG_ONLY` | `False` | do not count backlog as migration; schedule market_regime_detector |

## Safety

- Legacy mutation: none by Codex.
- Old Redis writes: none by Codex.
- Exchange mutation: none by Codex.
- Live gate: `blocked_human_only`.
- Final approval token: not created.

This audit is support-lane tooling only. Claude P0 worker porting remains primary.
