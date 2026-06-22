# Codex Review: 031_codex_review_phase2_symbol_universe

GO/NO-GO: `PHASE2_SYMBOL_UNIVERSE_USDM_CORRECTION_CODEX_PASS`

## Command

```text
/home/wali/.local/bin/codex exec review ...
```

## Raw Output (tail)

```text
v2/backend/app/cli/v2_risk_gateway_runtime_worker.py:38:    LEGACY_ACTIVE_SYMBOLS_25,
v2/backend/app/cli/v2_risk_gateway_runtime_worker.py:149:    "legacy_active_symbols",
v2/backend/app/cli/v2_risk_gateway_runtime_worker.py:240:        source_payload.get("legacy_active_symbols")
v2/backend/app/cli/v2_risk_gateway_runtime_worker.py:241:        or overrides.get("legacy_active_symbols")
v2/backend/app/cli/v2_risk_gateway_runtime_worker.py:242:        or LEGACY_ACTIVE_SYMBOLS_25
v2/backend/app/cli/v2_risk_gateway_runtime_worker.py:244:    universe_service = SymbolUniverseService(legacy_active_symbols=legacy_seed)
v2/backend/app/cli/v2_risk_gateway_runtime_worker.py:287:                or universe_service.legacy_active_symbols()
v2/backend/app/cli/v2_risk_gateway_runtime_worker.py:297:        "legacy_active_symbols": universe_service.legacy_active_symbols(),
v2/backend/app/cli/v2_default_blocked_execution_adapter_stub.py:27:    ``legacy_active_symbols`` and is never the full universe.
v2/backend/app/cli/v2_default_blocked_execution_adapter_stub.py:55:    LEGACY_ACTIVE_SYMBOLS_25,
v2/backend/app/cli/v2_default_blocked_execution_adapter_stub.py:120:    "legacy_active_symbols",
v2/backend/app/cli/v2_default_blocked_execution_adapter_stub.py:236:    canonical_legacy_active = universe_service.legacy_active_symbols()
v2/backend/app/cli/v2_default_blocked_execution_adapter_stub.py:237:    public_legacy_active = _as_symbol_list(source_payload.get("legacy_active_symbols"))
v2/backend/app/cli/v2_default_blocked_execution_adapter_stub.py:243:        evidence_gaps.append("public_payload_legacy_active_symbols_mismatch_ignored")
v2/backend/app/cli/v2_default_blocked_execution_adapter_stub.py:301:        "legacy_active_symbols": canonical_legacy_active,
v2/backend/app/cli/v2_default_blocked_execution_adapter_stub.py:305:        "symbol_universe_payload_legacy_active_symbols": public_legacy_active,
v2/backend/app/cli/v2_account_position_monitor.py:33:    LEGACY_ACTIVE_SYMBOLS_25,
v2/backend/app/cli/v2_account_position_monitor.py:108:    "legacy_active_symbols",
v2/backend/app/cli/v2_account_position_monitor.py:200:        source_payload.get("legacy_active_symbols")
v2/backend/app/cli/v2_account_position_monitor.py:201:        or overrides.get("legacy_active_symbols")
v2/backend/app/cli/v2_account_position_monitor.py:202:        or LEGACY_ACTIVE_SYMBOLS_25
v2/backend/app/cli/v2_account_position_monitor.py:204:    universe_service = SymbolUniverseService(legacy_active_symbols=legacy_seed)
v2/backend/app/cli/v2_account_position_monitor.py:240:    live_blocked = sorted(set(binance_confirmed or discovered or universe_service.legacy_active_symbols()))
v2/backend/app/cli/v2_account_position_monitor.py:249:        "legacy_active_symbols": universe_service.legacy_active_symbols(),
v2/backend/app/cli/symbol_universe_public_payload.py:11:    LEGACY_ACTIVE_SYMBOLS_25,
v2/backend/app/cli/symbol_universe_public_payload.py:136:    legacy_active = service.legacy_active_symbols()
v2/backend/app/cli/symbol_universe_public_payload.py:164:        "legacy_active_symbols": legacy_active,
v2/backend/app/cli/symbol_universe_public_payload.py:166:        "legacy_active_symbols_are_full_universe": False,
v2/backend/app/cli/v2_replay_worker.py:26:    ``legacy_active_symbols``; it is not treated as the full universe.
v2/backend/app/cli/v2_replay_worker.py:52:    LEGACY_ACTIVE_SYMBOLS_25,
v2/backend/app/cli/v2_replay_worker.py:166:    "legacy_active_symbols",
v2/backend/app/cli/v2_replay_worker.py:168:    "legacy_active_symbols_public_payload_status",
v2/backend/app/cli/v2_replay_worker.py:262:    legacy_seed = _as_symbol_list(LEGACY_ACTIVE_SYMBOLS_25)
v2/backend/app/cli/v2_replay_worker.py:263:    public_legacy_active = _as_symbol_list(public_payload.get("legacy_active_symbols"))
v2/backend/app/cli/v2_replay_worker.py:271:    service = SymbolUniverseService(legacy_active_symbols=legacy_seed)
v2/backend/app/cli/v2_replay_worker.py:302:                or service.legacy_active_symbols()
v2/backend/app/cli/v2_replay_worker.py:311:        "legacy_active_symbols": service.legacy_active_symbols(),
v2/backend/app/cli/v2_replay_worker.py:313:        "legacy_active_symbols_public_payload_status": public_legacy_active_status,
v2/backend/app/cli/v2_script_monitor.py:21:    LEGACY_ACTIVE_SYMBOLS_25,
v2/backend/app/cli/v2_script_monitor.py:65:    "legacy_active_symbols",
v2/backend/app/cli/v2_script_monitor.py:127:    canonical_legacy = _as_symbol_list(LEGACY_ACTIVE_SYMBOLS_25)
v2/backend/app/cli/v2_script_monitor.py:128:    public_legacy = _as_symbol_list(payload.get("legacy_active_symbols"))
v2/backend/app/cli/v2_script_monitor.py:136:    service = SymbolUniverseService(legacy_active_symbols=canonical_legacy)
v2/backend/app/cli/v2_script_monitor.py:148:        live_blocked = sorted(set(dynamic_discovered or discovered or observed_symbols or service.legacy_active_symbols()))
v2/backend/app/cli/v2_script_monitor.py:153:        "legacy_active_symbols": service.legacy_active_symbols(),
v2/backend/app/cli/v2_script_monitor.py:155:        "legacy_active_symbols_public_payload_status": public_legacy_status,
v2/backend/app/cli/v2_feature_pipeline_and_ta_worker.py:57:    LEGACY_ACTIVE_SYMBOLS_25,
v2/backend/app/cli/v2_feature_pipeline_and_ta_worker.py:238:        source_payload.get("legacy_active_symbols")
v2/backend/app/cli/v2_feature_pipeline_and_ta_worker.py:239:        or snapshot.get("legacy_active_symbols")
v2/backend/app/cli/v2_feature_pipeline_and_ta_worker.py:240:        or LEGACY_ACTIVE_SYMBOLS_25
v2/backend/app/cli/v2_feature_pipeline_and_ta_worker.py:242:    universe_service = SymbolUniverseService(legacy_active_symbols=legacy_seed)
v2/backend/app/cli/v2_feature_pipeline_and_ta_worker.py:274:            set(dynamic_discovered or discovered or observed or universe_service.legacy_active_symbols())
v2/backend/app/cli/v2_feature_pipeline_and_ta_worker.py:283:        "legacy_active_symbols": universe_service.legacy_active_symbols(),
v2/backend/app/cli/v2_signal_lineage_worker.py:24:    ``legacy_active_symbols`` and is not the universe.
v2/backend/app/cli/v2_signal_lineage_worker.py:48:    LEGACY_ACTIVE_SYMBOLS_25,
v2/backend/app/cli/v2_signal_lineage_worker.py:180:    "legacy_active_symbols",
v2/backend/app/cli/v2_signal_lineage_worker.py:300:        public_payload.get("legacy_active_symbols") or LEGACY_ACTIVE_SYMBOLS_25
v2/backend/app/cli/v2_signal_lineage_worker.py:302:    service = SymbolUniverseService(legacy_active_symbols=legacy_seed)
v2/backend/app/cli/v2_signal_lineage_worker.py:333:                or service.legacy_active_symbols()
v2/backend/app/cli/v2_signal_lineage_worker.py:342:        "legacy_active_symbols": service.legacy_active_symbols(),
v2/backend/app/cli/v2_signal_publisher.py:19:    LEGACY_ACTIVE_SYMBOLS_25,
v2/backend/app/cli/v2_signal_publisher.py:51:    "legacy_active_symbols",
v2/backend/app/cli/v2_signal_publisher.py:164:    legacy_seed = _as_symbol_list(source.get("legacy_active_symbols") or LEGACY_ACTIVE_SYMBOLS_25)
v2/backend/app/cli/v2_signal_publisher.py:165:    service = SymbolUniverseService(legacy_active_symbols=legacy_seed)
v2/backend/app/cli/v2_signal_publisher.py:179:        live_blocked = sorted(set(binance_confirmed or dynamic_discovered or discovered or observed_symbols or service.legacy_active_symbols()))
v2/backend/app/cli/v2_signal_publisher.py:184:        "legacy_active_symbols": service.legacy_active_symbols(),
v2/backend/app/cli/v2_trainer_bridge.py:19:    LEGACY_ACTIVE_SYMBOLS_25,
v2/backend/app/cli/v2_trainer_bridge.py:101:    "legacy_active_symbols",
v2/backend/app/cli/v2_trainer_bridge.py:176:        source_payload.get("legacy_active_symbols")
v2/backend/app/cli/v2_trainer_bridge.py:177:        or overrides.get("legacy_active_symbols")
v2/backend/app/cli/v2_trainer_bridge.py:178:        or LEGACY_ACTIVE_SYMBOLS_25
v2/backend/app/cli/v2_trainer_bridge.py:180:    service = SymbolUniverseService(legacy_active_symbols=legacy_seed)
v2/backend/app/cli/v2_trainer_bridge.py:210:    live_blocked = sorted(set(binance_confirmed or discovered or service.legacy_active_symbols()))
v2/backend/app/cli/v2_trainer_bridge.py:218:        "legacy_active_symbols": service.legacy_active_symbols(),
v2/backend/app/cli/v2_trainer_bridge.py:388:            "legacy_active_symbols": symbol_scope.get("legacy_active_symbols", []),
v2/backend/app/cli/v2_orchestrator_adapter.py:28:    ``legacy_active_symbols`` and is not the universe.
v2/backend/app/cli/v2_orchestrator_adapter.py:67:    LEGACY_ACTIVE_SYMBOLS_25,
v2/backend/app/cli/v2_orchestrator_adapter.py:197:    "legacy_active_symbols",
v2/backend/app/cli/v2_orchestrator_adapter.py:314:        public_payload.get("legacy_active_symbols") or LEGACY_ACTIVE_SYMBOLS_25
v2/backend/app/cli/v2_orchestrator_adapter.py:316:    service = SymbolUniverseService(legacy_active_symbols=legacy_seed)
v2/backend/app/cli/v2_orchestrator_adapter.py:347:                or service.legacy_active_symbols()
v2/backend/app/cli/v2_orchestrator_adapter.py:356:        "legacy_active_symbols": service.legacy_active_symbols(),
v2/backend/app/cli/v2_config_admin_manager.py:24:    LEGACY_ACTIVE_SYMBOLS_25,
v2/backend/app/cli/v2_config_admin_manager.py:66:    "legacy_active_symbols",
v2/backend/app/cli/v2_config_admin_manager.py:128:    canonical_legacy = _as_symbol_list(LEGACY_ACTIVE_SYMBOLS_25)
v2/backend/app/cli/v2_config_admin_manager.py:129:    public_legacy = _as_symbol_list(payload.get("legacy_active_symbols"))
v2/backend/app/cli/v2_config_admin_manager.py:137:    service = SymbolUniverseService(legacy_active_symbols=canonical_legacy)
v2/backend/app/cli/v2_config_admin_manager.py:149:        live_blocked = sorted(set(dynamic_discovered or discovered or service.legacy_active_symbols()))
v2/backend/app/cli/v2_config_admin_manager.py:154:        "legacy_active_symbols": service.legacy_active_symbols(),
v2/backend/app/cli/v2_config_admin_manager.py:156:        "legacy_active_symbols_public_payload_status": public_legacy_status,
v2/backend/app/cli/v2_execution_ledger_worker.py:28:    surfaced as ``legacy_active_symbols`` and is not treated as the
grep: write error: Broken pipe

exec
/bin/bash -lc "sed -n '160,230p' v2/backend/app/cli/v2_trainer_bridge.py" in /home/wali/Desktop/AI BOT REBUILD
 succeeded in 0ms:


def _load_first_payload(paths: List[Path]) -> Tuple[Dict[str, Any], Optional[str]]:
    for candidate in paths:
        if candidate.exists():
            data = _read_json(candidate)
            return (data if isinstance(data, dict) else {}), _rel(candidate)
    return {}, None


def build_symbol_scope(*, observed_symbols: List[str], input_overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    overrides = input_overrides or {}
    public_payload, public_path = _load_symbol_universe_public_payload()
    upstream_payload, upstream_path = _load_first_payload(UPSTREAM_SYMBOL_SCOPE_CANDIDATES)
    source_payload: Dict[str, Any] = public_payload or upstream_payload or overrides
    legacy_seed = _as_symbol_list(
        source_payload.get("legacy_active_symbols")
        or overrides.get("legacy_active_symbols")
        or LEGACY_ACTIVE_SYMBOLS_25
    )
    service = SymbolUniverseService(legacy_active_symbols=legacy_seed)
    discovered = _as_symbol_list(
        source_payload.get("discovered_symbols")
        or source_payload.get("symbols_discovered")
        or source_payload.get("all_discovered_symbols")
    )
    if not discovered:
        discovered = sorted(
            {
                identity.canonical_symbol_id.upper()
                for identity in service.all_discovered_symbols()
                if getattr(identity, "canonical_symbol_id", None)
            }
        )
    dynamic_discovered = _as_symbol_list(
        source_payload.get("dynamic_discovered_symbols")
        or source_payload.get("dynamic_symbols")
        or overrides.get("dynamic_discovered_symbols")
        or discovered
    )
    if not discovered and dynamic_discovered:
        discovered = list(dynamic_discovered)
    training_symbols = _as_symbol_list(source_payload.get("training_symbols") or overrides.get("training_symbols"))
    paper_symbols = _as_symbol_list(source_payload.get("paper_symbols") or overrides.get("paper_symbols"))
    observed = _as_symbol_list(observed_symbols)
    binance_confirmed = _as_symbol_list(
        source_payload.get("binance_usdm_confirmed_symbols")
        or source_payload.get("tradable_symbols")
        or overrides.get("binance_usdm_confirmed_symbols")
    )
    live_blocked = sorted(set(binance_confirmed or discovered or service.legacy_active_symbols()))
    return {
        "symbol_universe_contract": SYMBOL_UNIVERSE_CONTRACT,
        "symbol_universe_source_path": SYMBOL_UNIVERSE_SERVICE_PATH,
        "symbol_universe_public_payload_status": "PRESENT" if public_path else "MISSING_SYMBOL_UNIVERSE_PUBLIC_PAYLOAD",
        "symbol_universe_public_payload_path": public_path or "",
        "symbol_scope_upstream_payload_status": "PRESENT" if upstream_path else "MISSING_UPSTREAM_SYMBOL_SCOPE_PAYLOAD",
        "symbol_scope_upstream_payload_path": upstream_path or "",
        "legacy_active_symbols": service.legacy_active_symbols(),
        "legacy_active_symbol_source": LEGACY_ACTIVE_SYMBOL_SOURCE,
        "discovered_symbols": discovered,
        "dynamic_discovered_symbols": dynamic_discovered,
        "dynamic_symbol_sources": list(DYNAMIC_SYMBOL_SOURCES),
        "observed_symbols": observed,
        "training_symbols": training_symbols,
        "paper_symbols": paper_symbols,
        "live_symbols": [],
        "live_blocked_symbols": live_blocked,
        "binance_usdm_confirmed_symbols": binance_confirmed,
        "live_symbol_policy": "live_symbols_empty_while_live_gate_blocked_human_only",
        "passive_monitor_all_discovered_symbols": True,

exec
/bin/bash -lc "PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python - <<'PY'
from v2.backend.app.domain.symbols.normalization import normalize_source_symbol, resolve_symbol_alias
usdm=normalize_source_symbol('binance_usdm', {'symbol':'BTCUSDT','pair':'BTCUSDT','contractType':'PERPETUAL','status':'TRADING','baseAsset':'BTC','quoteAsset':'USDT','marginAsset':'USDT'})
coinapi=normalize_source_symbol('coinapi_ws', {'symbol':'BINANCE_PERP_BTC_USDT','pair':'BTC/USDT','base':'BTC','quote':'USDT','settlement':'USDT','contract_type':'PERPETUAL'})
for identities in ([coinapi, usdm], [usdm, coinapi]):
    r=resolve_symbol_alias('BTCUSDT','legacy_config', identities)
    print([i.source for i in identities], '->', r.source, r.canonical_symbol_id)
PY" in /home/wali/Desktop/AI BOT REBUILD
 succeeded in 0ms:
['coinapi_ws', 'binance_usdm'] -> coinapi_ws BTC-USDT-PERP-USDM-COINAPI
['binance_usdm', 'coinapi_ws'] -> binance_usdm BINANCE-USDM-BTC-USDT-PERP

codex
Targeted symbol-universe tests pass, but the alias resolver can map legacy active symbols to the wrong source identity, and the hot-reload contract misses same-symbol status/metadata changes. These issues affect the correctness of the symbol universe foundation.

Full review comments:

- [P2] Prefer Binance USD-M for legacy aliases — /home/wali/Desktop/AI BOT REBUILD/v2/backend/app/domain/symbols/normalization.py:185-187
  When resolving a legacy symbol such as `BTCUSDT` with identities from Binance USD-M plus CoinAPI/KuCoin, those non-Binance identities also contain `BTCUSDT` in `alias_set`; because the fallback returns the first alias match, the legacy 25-symbol active subset can bind to a non-Binance canonical identity depending on iteration order instead of the primary Binance USD-M identity.

- [P2] Include same-ID symbol updates in universe changes — /home/wali/Desktop/AI BOT REBUILD/v2/backend/app/services/symbol_universe/service.py:103-108
  If `/exchangeInfo` changes fields for an existing canonical symbol, such as `status` moving from `TRADING` to `SETTLING` or filters/precision changing, `prev_ids` and `curr_ids` remain equal, so `changed_symbols` and `hot_reload_required_components` stay empty. That leaves downstream components with no hot-reload signal for an exchange status or contract metadata change that should disable or refresh the symbol.
Targeted symbol-universe tests pass, but the alias resolver can map legacy active symbols to the wrong source identity, and the hot-reload contract misses same-symbol status/metadata changes. These issues affect the correctness of the symbol universe foundation.

Full review comments:

- [P2] Prefer Binance USD-M for legacy aliases — /home/wali/Desktop/AI BOT REBUILD/v2/backend/app/domain/symbols/normalization.py:185-187
  When resolving a legacy symbol such as `BTCUSDT` with identities from Binance USD-M plus CoinAPI/KuCoin, those non-Binance identities also contain `BTCUSDT` in `alias_set`; because the fallback returns the first alias match, the legacy 25-symbol active subset can bind to a non-Binance canonical identity depending on iteration order instead of the primary Binance USD-M identity.

- [P2] Include same-ID symbol updates in universe changes — /home/wali/Desktop/AI BOT REBUILD/v2/backend/app/services/symbol_universe/service.py:103-108
  If `/exchangeInfo` changes fields for an existing canonical symbol, such as `status` moving from `TRADING` to `SETTLING` or filters/precision changing, `prev_ids` and `curr_ids` remain equal, so `changed_symbols` and `hot_reload_required_components` stay empty. That leaves downstream components with no hot-reload signal for an exchange status or contract metadata change that should disable or refresh the symbol.
```
