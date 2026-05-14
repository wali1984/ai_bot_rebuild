# Worker Report — v2_binance_usdm_adapter

Worker ID: `v2_binance_usdm_adapter`
Task: `claude_port_v2_p2_binance_usdm_adapter_stub`
Generated: 2026-05-14 (UTC)
Status: EMIT_COMPLETE (fail-closed Binance USD-M futures adapter stub; live remains `blocked_human_only`)
Live gate: **blocked_human_only** (unchanged; cannot be flipped from this worker)

---

## What was built

A fail-closed Binance USD-M futures adapter stub at the V2 worker layer:

| File | Role |
| --- | --- |
| `v2/backend/app/services/binance_usdm_adapter/service.py` | `BinanceUsdmAdapter` class. Five mutation methods raise `BlockedGateNotApprovedError` (code `BLOCKED_GATE_NOT_APPROVED`). Two read-only methods return presence-only observations and never make a real exchange call. |
| `v2/backend/app/cli/v2_binance_usdm_adapter_stub.py` | CLI worker. Instantiates the adapter, builds the Symbol Universe contract, and writes the public status payload to three sinks (public / local / worker). |
| `v2/backend/tests/integration/cli/test_v2_binance_usdm_adapter_stub.py` | Integration suite covering every required invariant. |
| `v2/frontend/public/operator_runtime/v2_binance_usdm_adapter/latest/v2_binance_usdm_adapter_status.json` | Seed public payload. |
| `claude_worklog/.../workers/v2_binance_usdm_adapter_status.json` | Worker-sink mirror of the public payload. |
| `claude_worklog/.../workers/v2_p2_binance_usdm_adapter_stub_LEGACY_BASELINE_ANALYSIS.md` | Legacy baseline analysis (mapping legacy Binance USD-M surface → V2 refusal/observation surface). |
| `claude_worklog/.../workers/v2_p2_binance_usdm_adapter_stub_legacy_behavior_mapping.json` | Structured mapping JSON. |

## Invariants enforced

| Invariant | How enforced |
| --- | --- |
| All five mutating endpoints (new order, cancel, change initial leverage, change margin type, change position mode) raise `BLOCKED_GATE_NOT_APPROVED` | `BinanceUsdmAdapter._refuse` raises before evaluating any argument; tests cover each method individually and via parametrise. |
| Read-only access does NOT unlock the live gate | `live_gate` is a class constant equal to `blocked_human_only`. Read-only methods never write to it. Test `test_read_only_methods_do_not_unlock_live_gate` asserts the gate stays blocked after calls to `account_info_v3` and `position_risk`. |
| No secret value is returned by any method | Read-only methods return only a presence-of-credentials boolean and structural observation. Tests serialize the returned dicts and assert the sentinel secret is not present. |
| No secret value is logged by the worker | Worker has no logging that touches env values. Test captures stdout/stderr/logging while running `main` with sentinel credentials in env and asserts the sentinel is not present. |
| No real exchange call from this stub | The module has no Binance/ccxt/Redis import. `exchange_call_taken` is always `False`. Static source check forbids the relevant method literals. |
| Adapter holds no exchange client and no credential value | Tests assert `hasattr(adapter, "exchange_client")`, `"api_key"`, `"api_secret"`, etc. are all `False`. |
| Live gate is permanently `blocked_human_only` | `LIVE_GATE_STATUS = "blocked_human_only"` is a single constant; no codepath assigns to it. Tests forbid the tokens `unblock`, `enable_live`, `approval_token`. |
| Stub state is `DISABLED` or `BLOCKED` only (never `ACTIVE`) | `ALLOWED_STUB_STATES = (STATE_DISABLED, STATE_BLOCKED)`. Tests assert `"ACTIVE" not in ALLOWED_STUB_STATES`. |
| Symbol Universe contract is honoured | Worker reads the V2 Symbol Universe service; classifies `MISSING_SYMBOL_UNIVERSE_PUBLIC_PAYLOAD` when no public payload exists; distinguishes `legacy_active_symbols`, `discovered_symbols`, `observed_symbols`, `training_symbols`, `paper_symbols`, `live_symbols`, `live_blocked_symbols`, `binance_usdm_confirmed_symbols`, `dynamic_discovered_symbols`. |
| The 25-symbol legacy active subset is preserved but never the full universe | `legacy_active_symbols == LEGACY_ACTIVE_SYMBOLS_25`; tests assert the worker source does not hardcode any of the 25 symbols inline. |
| No worker may train or trade all discovered symbols automatically | `train_all_discovered_symbols = False`, `trade_all_discovered_symbols = False`, `passive_monitor_all_discovered_symbols = True`. |
| CoinAnk-only symbols stay market-intelligence-only until Binance USD-M confirms | `coinank_symbols_tradability = "market_intelligence_only_until_binance_usdm_confirmed"`. The `_sanitize_selected_symbols` helper rejects any requested training/paper symbol that is not also `binance_usdm_confirmed`. |

## Live gate proof

- `live_gate == "blocked_human_only"` in the service module, the worker module, the status snapshot, and the written payload.
- No flag, kwarg, env var, or attribute can flip the gate from this worker.
- To permit a live order, this stub must be *replaced* by a real adapter — no toggle path exists.

## Codex review trigger

On emit, trigger `codex_review_v2_p2_binance_usdm_adapter_stub`. The codex reviewer must verify the seven required mapping fields in the legacy baseline analysis (`legacy_source_paths`, `legacy_inputs`, `legacy_outputs`, `legacy_redis_keys`, `legacy_config_dependencies`, `legacy_edge_cases`, `legacy_failure_modes`), the `V2_mapping`, `intentional_changes`, and `removed/deprecated` sections, and run the integration test suite.

## Blockers / open items

None for this worker. Live trading remains `blocked_human_only` by construction. The worker is ready for `codex_review_v2_p2_binance_usdm_adapter_stub`.
Files emitted: legacy baseline analysis + mapping JSON, service module, CLI worker, integration test suite, public payload seed, worker-sink status mirror, and worker report. Live gate stays `blocked_human_only`; five mutation methods raise `BLOCKED_GATE_NOT_APPROVED`; two read-only methods (`account_info_v3`, `position_risk`) are callable but never make a real exchange call and never return or log the credential value.
