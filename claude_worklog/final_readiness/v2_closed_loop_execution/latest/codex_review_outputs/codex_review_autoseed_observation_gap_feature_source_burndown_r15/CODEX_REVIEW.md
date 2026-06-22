# Codex Review: codex_review_autoseed_observation_gap_feature_source_burndown_r15

GO/NO-GO: `V2_AUTONOMOUS_OBSERVATION_GAP_FEATURE_SOURCE_BURNDOWN_CODEX_FAIL`

## Command

```text
/home/wali/.local/bin/codex exec review ...
```

## Blockers

- 1. Decide whether to extend V2-native unified_features beyond the current
- 1. `_project_liquidations` — accept and forward `v2_liquidation_per_symbol`

## Raw Output (tail)

```text
        except (ValueError, TypeError):
            out["aggregate"] = None
    out["any_populated"] = bool(out["latest"] or out["aggregate"])
    out["v2_per_symbol_aggregator_present"] = out["any_populated"]
    return out


def build_liquidation_subfamily(
    symbol: str,
    v2_features: Mapping[str, Any] | None,
    coinank_intel: Mapping[str, Any] | None,
    v2_liquidation_per_symbol: Mapping[str, Any] | None = None,
) -> list[tuple[str, float | None, str]]:
    """Return the 12-slot liquidation subfamily as
    ``(name, value, source)`` tuples (12 entries always)."""
    size = 12
    out: list[tuple[str, float | None, str]] = [
        (f"liquidations[{i}]", None, "MISSING_FROM_V2_LIQUIDATION_AGGREGATOR")
        for i in range(size)
    ]
    feats = v2_features or {}
    intel = coinank_intel or {}
    gar = intel.get("global_aggregate_result") or {}
    last_liq = _coerce_float(feats.get("last_liq_bps_24h"))
    liq_abs = abs(last_liq) if last_liq is not None else None
    liq_direction = (
        None
        if last_liq is None
        else (1.0 if last_liq > 0 else (-1.0 if last_liq < 0 else 0.0))
    )
    total_liquidations = _coerce_float(gar.get("total_liquidations"))
    persisted_total = _coerce_float(intel.get("liquidations_persisted_total"))
    coinank_freshness_seconds = _coerce_float(intel.get("freshness_seconds"))
    liq_notional_24h_proxy = last_liq
    liq_direction_bias = liq_direction
    # V2 per-symbol liquidation aggregator (operator-decision-gated). When
    # ``v2:market:liquidations:latest:{sym}`` and
    # ``v2:market:liquidations:aggregate:{sym}`` are populated by a future
    # V2-owned WSS client, fill the 4 currently-missing slots from them.
    ls = v2_liquidation_per_symbol or {}
    latest_per_sym = (ls.get("latest") or {}) if isinstance(ls.get("latest"), dict) else {}
    aggregate_per_sym = (
        (ls.get("aggregate") or {}) if isinstance(ls.get("aggregate"), dict) else {}
    )
    latest_notional = _coerce_float(latest_per_sym.get("notional"))
    latest_side_raw = (
        (latest_per_sym.get("side") or "").lower() if latest_per_sym else ""
    )
    latest_side_long = (
        1.0
        if latest_side_raw in ("long", "buy")
        else (0.0 if latest_per_sym else None)
    )
    latest_side_short = (
        1.0
        if latest_side_raw in ("short", "sell")
        else (0.0 if latest_per_sym else None)
    )
    aggregate_1h_notional = _coerce_float(aggregate_per_sym.get("notional_1h"))
    v2_liq_source_available = (
        1.0 if ls.get("v2_per_symbol_aggregator_present") else 0.0
    )
    per_symbol_source_flag_src = (
        "V2_MARKET_LIQUIDATIONS_PER_SYMBOL_PRESENT"
        if ls.get("v2_per_symbol_aggregator_present")
        else "V2_PROBE_FLAG_NO_PER_SYMBOL_LIQUIDATION_AGGREGATOR_PRESENT"
    )
    rows: list[tuple[str, float | None, str]] = [
        ("latest_liquidation_notional", latest_notional,
         "V2_MARKET_LIQUIDATIONS_LATEST"
         if latest_notional is not None
         else "MISSING_FROM_V2_LIQUIDATION_AGGREGATOR"),
        ("latest_liquidation_side_long", latest_side_long,
         "V2_MARKET_LIQUIDATIONS_LATEST"
         if latest_side_long is not None
         else "MISSING_FROM_V2_LIQUIDATION_AGGREGATOR"),
        ("latest_liquidation_side_short", latest_side_short,
         "V2_MARKET_LIQUIDATIONS_LATEST"
         if latest_side_short is not None
         else "MISSING_FROM_V2_LIQUIDATION_AGGREGATOR"),
        ("last_liq_bps_24h", last_liq,
         "V2_NATIVE_FEATURE_SNAPSHOT"
         if last_liq is not None
         else "MISSING_FROM_V2_LIQUIDATION_AGGREGATOR"),
        ("last_liq_bps_24h_abs", liq_abs,
         "V2_DERIVED_FROM_FEATURES"
         if liq_abs is not None
         else "MISSING_FROM_V2_LIQUIDATION_AGGREGATOR"),
        ("last_liq_direction", liq_direction,
         "V2_DERIVED_FROM_FEATURES"
         if liq_direction is not None
         else "MISSING_FROM_V2_LIQUIDATION_AGGREGATOR"),
        ("liquidation_count_proxy_global", total_liquidations,
         "V2_COINANK_GLOBAL_AGGREGATE_NOT_PER_SYMBOL"
         if total_liquidations is not None
         else "MISSING_FROM_V2_LIQUIDATION_AGGREGATOR"),
        ("liquidation_notional_1h_proxy", aggregate_1h_notional,
         "V2_MARKET_LIQUIDATIONS_AGGREGATE"
         if aggregate_1h_notional is not None
         else "MISSING_FROM_V2_LIQUIDATION_AGGREGATOR"),
        ("liquidation_notional_24h_proxy", liq_notional_24h_proxy,
         "V2_NATIVE_FEATURE_SNAPSHOT"
         if liq_notional_24h_proxy is not None
         else "MISSING_FROM_V2_LIQUIDATION_AGGREGATOR"),
        ("liquidation_direction_bias", liq_direction_bias,
         "V2_DERIVED_FROM_FEATURES"
         if liq_direction_bias is not None
         else "MISSING_FROM_V2_LIQUIDATION_AGGREGATOR"),
        ("liquidation_freshness_seconds", coinank_freshness_seconds,
         "V2_COINANK_MARKET_INTELLIGENCE"
         if coinank_freshness_seconds is not None
         else "MISSING_FROM_V2_LIQUIDATION_AGGREGATOR"),
        ("v2_liquidation_source_available", v2_liq_source_available,
         per_symbol_source_flag_src),
    ]
    _ = persisted_total
    for i, (nm, val, src) in enumerate(rows[:size]):
        if val is None:
            out[i] = (f"liquidations.{nm}", None,
                      "MISSING_FROM_V2_LIQUIDATION_AGGREGATOR")
        else:
            out[i] = (f"liquidations.{nm}", val, src)
    return out


def build_aggregator_status(
    symbols: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "SOLUSDT"),
    timeframe: str = "1m",
) -> dict[str, Any]:
    intel = load_coinank_intelligence()
    try:
        import redis  # type: ignore

        r = redis.Redis(host="127.0.0.1", port=6379, db=0, decode_responses=True)
        r.ping()
    except Exception:
        r = None
    per_symbol: list[dict[str, Any]] = []
    total_present = 0
    total_target = 0
    for sym in symbols:
        feats = None
        if r is not None:
            try:
                raw = r.get(f"v2:features:latest:{sym}:{timeframe}")
                if raw:
                    feats = (json.loads(raw) or {}).get("features")
            except Exception:
                feats = None
        per_symbol_data = _read_v2_liquidation_per_symbol(sym)
        rows = build_liquidation_subfamily(sym, feats, intel, per_symbol_data)
        present = sum(1 for (_, v, _s) in rows if v is not None)
        missing = sum(1 for (_, v, _s) in rows if v is None)
        total_present += present
        total_target += len(rows)
        per_symbol.append(
            {
                "symbol": sym,
                "subfamily_target": len(rows),

exec
/bin/bash -lc "sed -n '260,620p' v2/backend/app/services/rl_core/liquidation_observation_aggregator.py && git status --short -- v2/backend/app/services/rl_core/liquidation_observation_aggregator.py v2/backend/tests/integration/cli/test_v2_full_observation_liquidation_burndown.py claude_worklog/final_readiness/v2_full_observation_liquidation_burndown/latest v2/frontend/public/v2_full_observation_liquidation_burndown/latest v2/frontend/public/operator_runtime/v2_rl_core/latest/full_observation_builder_status.json" in /home/wali/Desktop/AI BOT REBUILD
 succeeded in 0ms:
                "subfamily_target": len(rows),
                "subfamily_present": present,
                "subfamily_missing": missing,
                "fields": [
                    {"name": nm, "value": val, "source": src}
                    for (nm, val, src) in rows
                ],
            }
        )
    return {
        "schema_version": "v2_liquidation_observation_aggregator_status_v1",
        "generated_utc": _utc_iso(),
        "target_per_symbol": 12,
        "symbols": list(symbols),
        "per_symbol": per_symbol,
        "subfamily_total_present_across_symbols": total_present,
        "subfamily_total_target_across_symbols": total_target,
        "v2_liquidation_aggregator_per_symbol_source_available": False,
        "v2_coinank_intelligence_payload_present": bool(intel),
        "no_zero_fill_for_unknown_fields": True,
        "no_torch_imported": True,
        "no_pickle_loaded": True,
        "no_legacy_filesystem_read": True,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
    }
?? claude_worklog/final_readiness/v2_full_observation_liquidation_burndown/latest/
?? v2/backend/app/services/rl_core/liquidation_observation_aggregator.py
?? v2/frontend/public/v2_full_observation_liquidation_burndown/latest/

codex
V2_AUTONOMOUS_OBSERVATION_GAP_FEATURE_SOURCE_BURNDOWN_CODEX_FAIL
V2_AUTONOMOUS_OBSERVATION_GAP_FEATURE_SOURCE_BURNDOWN_CODEX_FAIL
```
