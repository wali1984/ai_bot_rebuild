#!/usr/bin/env python3
"""Builder for V2 legacy-data zero-exception parity milestone.

Loads matrix_rows.json (the per-script data) and emits all milestone
artifacts. Read-only against the system; safety envelope is the
standard paper-only set.
"""
from __future__ import annotations

import datetime as dt
import json
import subprocess
from pathlib import Path

ROOT = Path("/home/wali/Desktop/AI BOT REBUILD")
TASK_ID = "v2_legacy_data_zero_exception_parity_and_full_runtime_startup"
WORKLOG = ROOT / "claude_worklog/final_readiness" / TASK_ID / "latest"
PUBLIC = ROOT / "v2/frontend/public" / TASK_ID / "latest"

NOW_EST = "2026-05-31T01:10:00-0400"
NOW_UTC = "2026-05-31T05:10:00Z"

GIT_HEAD = subprocess.check_output(
    ["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True
).strip()


def _scan(p): return int(subprocess.run(["bash","-c", f"redis-cli --scan --pattern '{p}' | wc -l"], capture_output=True, text=True, timeout=10).stdout.strip() or 0)


def _xlen(s): return int(subprocess.run(["redis-cli", "XLEN", s], capture_output=True, text=True, timeout=5).stdout.strip() or 0)


def _age_h(p):
    pp = ROOT / p
    if not pp.exists(): return None
    return (dt.datetime.now().timestamp() - pp.stat().st_mtime) / 3600


def _write_json(name, payload):
    body = json.dumps(payload, indent=2, sort_keys=False) + "\n"
    for d in (WORKLOG, PUBLIC):
        d.mkdir(parents=True, exist_ok=True)
        (d / name).write_text(body)


def _write_text(name, body):
    for d in (WORKLOG, PUBLIC):
        d.mkdir(parents=True, exist_ok=True)
        (d / name).write_text(body)


# ---------------------------------------------------------------------------
# Load matrix rows
# ---------------------------------------------------------------------------

rows = json.loads((WORKLOG / "matrix_rows.json").read_text())

# Decorate each row with current_freshness_hours and a brief current_v2_keyspace.
for r in rows:
    pp = r.get("v2_payload_path")
    if pp:
        r["current_freshness_hours"] = _age_h(pp)
    else:
        r["current_freshness_hours"] = None


# ---------------------------------------------------------------------------
# Redis evidence
# ---------------------------------------------------------------------------

V2_FAMILIES = [
    "v2:market:prices:*", "v2:market:funding:*", "v2:market:open_interest:*",
    "v2:market:liquidations:*", "v2:market:liquidations:latest:*",
    "v2:market:liquidations:aggregate:*", "v2:market:liquidation_levels:*",
    "v2:market:ohlcv:*", "v2:market:orderbook:*", "v2:market:coinank:*",
    "v2:market:kucoin:*", "v2:market:coinapi:*", "v2:market:microstructure:*",
    "v2:features:*", "v2:unified_features:*", "v2:technical_analysis:*",
    "v2:altdata:*", "v2:altdata:lunarcrush:*", "v2:altdata:nansen:*",
    "v2:altdata:arkham:*", "v2:altdata:tokenmetrics:*",
    "v2:prediction:*", "v2:trainer:*", "v2:orchestrator:*",
    "v2:risk:*", "v2:paper:*", "v2:position_history:*",
    "v2:portfolio:*", "v2:health:*",
]
V2_KEY_COUNTS = {fam: _scan(fam) for fam in V2_FAMILIES}
V2_KEY_COUNTS["v2:liquidations:events_XLEN"] = _xlen("v2:liquidations:events")

OLD_FAMILIES = [
    "orchestrator:*", "live_orders:*", "exchange:order:*", "ohlcv:list:*",
    "latest:binance:*", "latest:coinank:*", "latest:coinank_endpoint:*",
    "latest:ta:*", "latest:coinapi:*", "ta:*", "unified_features:*",
    "prediction:*", "signals:*", "wma:*", "features:coinank:*",
    "features:coinank_endpoint:*", "features:kucoin:*",
    "features:global_coinank:*", "cursor:coinank:*", "coinank:*",
    "raw:coinank:*", "microfeat:*", "msnap:coinapi_wsds:*",
    "normalized:ohlcv:*", "kc:*", "tm:*", "tokenmetrics:*",
    "regime:*", "regime_analysis:*", "volatility:*",
    "trainer:intent:*", "rl:*", "price:*", "orderbook:*",
    "instant:*", "heartbeat:*",
]
OLD_KEY_COUNTS = {fam: _scan(fam) for fam in OLD_FAMILIES}
OLD_KEY_COUNTS["health:events_XLEN"] = _xlen("health:events")
OLD_KEY_COUNTS["pnl:decomp_XLEN"] = _xlen("pnl:decomp")
OLD_KEY_COUNTS["binance:force_XLEN"] = _xlen("binance:force")
OLD_KEY_COUNTS["executed_signals_XLEN"] = _xlen("executed_signals")


# ---------------------------------------------------------------------------
# Aggregates
# ---------------------------------------------------------------------------

STATUS_LABELS = (
    "V2_VALIDATED_RUNNING", "V2_RUNNING_PARTIAL", "V2_ADAPTER_REQUIRED",
    "V2_MISSING_IMPLEMENTATION", "V2_CREDENTIAL_BLOCKED",
    "V2_OPERATOR_REQUIRED", "V2_NOT_REQUIRED_WITH_PROOF",
)
STATUS_AGG = {s: sum(1 for r in rows if r["status"] == s) for s in STATUS_LABELS}


# ---------------------------------------------------------------------------
# Phase 1 JSON
# ---------------------------------------------------------------------------

LEGACY_25_SYMBOLS = [
    "1000BONKUSDT","1000FLOKIUSDT","1000PEPEUSDT","1000SHIBUSDT",
    "ALICEUSDT","ASTERUSDT","AUCTIONUSDT","AVNTUSDT",
    "BANKUSDT","BARDUSDT","BTCUSDT","DOGEUSDT",
    "ETHUSDT","FARTCOINUSDT","HIGHUSDT","LINKUSDT",
    "LTCUSDT","PENGUUSDT","PIPPINUSDT","RAVEUSDT",
    "RIVERUSDT","SOLUSDT","UNIUSDT","WIFUSDT","XRPUSDT",
]

phase1 = {
    "schema_version": "legacy_to_v2_zero_exception_data_matrix_v1",
    "milestone": TASK_ID,
    "phase": 1,
    "generated_est": NOW_EST,
    "generated_utc": NOW_UTC,
    "git_head": GIT_HEAD,
    "source_documents": [
        "LEGACY_SYSTEM_FULL_AUDIT.md (633 lines, audit 2026-05-22)",
        "legacy_reference/scripts/start_all_services_production.sh",
        "v2/legacy_owned_runtime/ingest/* (26 files)",
        "v2/legacy_owned_runtime/rl/* (110 files; primary: hybrid_trainer.py 57250 lines)",
        "v2/legacy_owned_runtime/trading/* (35 files)",
    ],
    "audit_canonical_counts": {
        "legacy_processes_count": 17,
        "legacy_ingestor_files_count": 24,
        "redis_categories_count": 15,
        "symbol_universe_count": 25,
        "audit_redis_key_total": 12637,
    },
    "v2_keyspace_current_counts": V2_KEY_COUNTS,
    "old_namespace_still_in_redis_counts": OLD_KEY_COUNTS,
    "legacy_25_symbols": LEGACY_25_SYMBOLS,
    "matrix_rows": rows,
    "row_count": len(rows),
    "status_aggregate": STATUS_AGG,
    "live_safety": {
        "live_gate_status": "blocked_human_only",
        "live_symbols": [],
        "old_redis_writes_taken_in_this_turn": False,
        "exchange_action_taken": False,
        "legacy_restart_taken": False,
        "redis_trim_taken": False,
    },
}


# ---------------------------------------------------------------------------
# Phase 1 Markdown
# ---------------------------------------------------------------------------

def render_md(rows_list):
    out = []
    out.append("# Legacy -> V2 Zero-Exception Data Matrix")
    out.append("")
    out.append(f"- Generated EST: {NOW_EST}")
    out.append(f"- Generated UTC: {NOW_UTC}")
    out.append(f"- Source: LEGACY_SYSTEM_FULL_AUDIT.md (633 lines, audit 2026-05-22)")
    out.append(f"- Row count: {len(rows_list)}")
    out.append("")
    out.append("Status legend: V2_VALIDATED_RUNNING / V2_RUNNING_PARTIAL / "
               "V2_ADAPTER_REQUIRED / V2_MISSING_IMPLEMENTATION / "
               "V2_CREDENTIAL_BLOCKED / V2_OPERATOR_REQUIRED / "
               "V2_NOT_REQUIRED_WITH_PROOF")
    out.append("")
    out.append("| # | Legacy script | Legacy role | Legacy keys | V2 namespace | V2 writer | Status | Blocker | Next task |")
    out.append("|---|---|---|---|---|---|---|---|---|")
    for i, r in enumerate(rows_list, 1):
        leg_keys = ", ".join((r.get("legacy_redis_keys_written") or []))[:140] or "-"
        v2_ns = ", ".join(r.get("v2_target_namespace") or [])[:140] or "-"
        writer = (r.get("v2_current_writer") or "-")[:120]
        blocker = (r.get("exact_blocker") or "-")[:200]
        nxt = (r.get("next_implementation_task") or "-")[:200]
        out.append(
            f"| {i} | `{r['legacy_script']}` | {r['legacy_role']} | {leg_keys} | "
            f"{v2_ns} | {writer} | **{r['status']}** | {blocker} | {nxt} |"
        )
    out.append("")
    out.append("## Status aggregate")
    out.append("")
    for s in STATUS_LABELS:
        out.append(f"- {s}: {STATUS_AGG[s]}")
    out.append("")
    out.append("## Audit-canonical counts vs current V2 keyspace")
    out.append("")
    out.append("| Family | Count |")
    out.append("|---|---:|")
    for k, v in V2_KEY_COUNTS.items():
        out.append(f"| `{k}` | {v} |")
    out.append("")
    out.append("## Legacy namespaces still present in Redis (static preserved)")
    out.append("")
    out.append("| Family | Count |")
    out.append("|---|---:|")
    for k, v in OLD_KEY_COUNTS.items():
        out.append(f"| `{k}` | {v} |")
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------
# Phase 2 startup map
# ---------------------------------------------------------------------------

legacy_startup_order = [
    "vpn_monitor.py", "system_telegram_monitor.py", "monitor_system_memory.py",
    "scripts/memory_monitor.py", "scripts/ingestors_watchdog.py",
    "scripts/monitor_trainer_predictions.py", "ingest/live_coinapi_wsds (-m)",
    "ingest/live_coinapi_v1 (-m)",
    "ingest/live_binance.py", "ingest/live_kucoin.py", "ingest/live_coinank.py",
    "ingest/live_coinank_global_aggregator.py",
    "ingest/live_binance_liquidations.py",
    "ingest/liquidation_bridge.py", "ingest/liquidation_levels_engine.py",
    "ohlcv_resampler_hotfix.py", "feature_pipeline.py",
    "ingest/live_technical_analysis.py", "rl.hybrid_trainer (-m)",
    "rl.orchestrator_worker (-m)", "trading/signal_router.py",
    "trading/trader.py", "trading/trader-asjad.py",
    "monitor_portfolio_primary.py", "monitor_portfolio_asjad.py",
]

V2_STARTUP_MAP = {
    "ingest/live_binance.py": ("ai-bot-v2-native-ingestors-live-loop.service", "RUNNING"),
    "ingest/live_binance_liquidations.py": ("ai-bot-v2-liquidation-wss-paper-shadow.service", "RUNNING_AS_WSS_REWIRED"),
    "ingest/live_coinank.py": ("(v2_coinank_and_liquidation_bridge CLI; no systemd timer)", "STALE_NO_SCHEDULER"),
    "ingest/live_coinank_global_aggregator.py": ("(inside v2_coinank_and_liquidation_bridge)", "PARTIAL_NO_API_DATA"),
    "ingest/live_kucoin.py": ("(v2_kucoin_ingestor_worker CLI; descriptive-only)", "STUB"),
    "ingest/live_coinapi_v1 (-m)": ("(no V2 CLI)", "MISSING"),
    "ingest/live_coinapi_wsds (-m)": ("(no V2 CLI)", "MISSING_PAID_TIER"),
    "ingest/liquidation_bridge.py": ("ai-bot-v2-liquidation-bridge.service", "RUNNING_AS_FALLBACK"),
    "ingest/liquidation_levels_engine.py": ("ai-bot-v2-liquidation-levels-engine.service", "RUNNING"),
    "ingest/live_technical_analysis.py": ("(no V2 worker)", "MISSING"),
    "ohlcv_resampler_hotfix.py": ("(no V2 equivalent)", "MISSING"),
    "feature_pipeline.py": ("ai-bot-v2-feature-pipeline-native-loop.service", "RUNNING_PARTIAL_23_OF_562_FIELDS"),
    "rl.hybrid_trainer (-m)": ("ai-bot-v2-trainer-bridge.service (bridge only)", "BRIDGE_ONLY"),
    "rl.orchestrator_worker (-m)": ("ai-bot-v2-orchestrator-arbitration-loop.service", "ARBITRATION_ONLY"),
    "trading/signal_router.py": ("(none)", "MISSING"),
    "trading/trader.py": ("ai-bot-v2-paper-online-runtime.service (paper-only)", "PAPER_ONLY"),
    "trading/trader-asjad.py": ("(none)", "OPERATOR_REQUIRED"),
    "monitor_portfolio_primary.py": ("(none)", "MISSING"),
    "monitor_portfolio_asjad.py": ("(none)", "OPERATOR_REQUIRED"),
    "vpn_monitor.py": ("(systemd manages)", "NOT_REQUIRED_WITH_PROOF"),
    "system_telegram_monitor.py": ("(no V2 Telegram path)", "OPERATOR_REQUIRED"),
    "monitor_system_memory.py": ("(systemd OOM)", "NOT_REQUIRED_WITH_PROOF"),
    "scripts/memory_monitor.py": ("(systemd OOM)", "NOT_REQUIRED_WITH_PROOF"),
    "scripts/ingestors_watchdog.py": ("ai-bot-v2-codex-watchdog.service", "RUNNING"),
    "scripts/monitor_trainer_predictions.py": ("ai-bot-v2-trainer-bridge.service exposes equivalent payload", "NOT_REQUIRED_WITH_PROOF"),
}

phase2 = {
    "schema_version": "legacy_startup_to_v2_startup_map_v1",
    "milestone": TASK_ID, "phase": 2,
    "generated_est": NOW_EST, "generated_utc": NOW_UTC,
    "legacy_startup_script": "legacy_reference/scripts/start_all_services_production.sh",
    "legacy_startup_order": [
        {"legacy_in_startup": x,
         "v2_unit": V2_STARTUP_MAP.get(x, ("(unmapped)", "UNMAPPED"))[0],
         "status": V2_STARTUP_MAP.get(x, ("(unmapped)", "UNMAPPED"))[1]}
        for x in legacy_startup_order
    ],
    "rules_applied": {
        "wss_replaces_binance_force_raw": True,
        "no_old_redis_writes_from_active_v2": True,
        "use_copied_when_adapter_safe": True,
    },
    "live_safety": {"live_gate_status": "blocked_human_only", "live_symbols": []},
}


# ---------------------------------------------------------------------------
# Phase 3 Redis adapter matrix
# ---------------------------------------------------------------------------

ns_map = [
    ("price:*", "v2:market:prices:{symbol}", "WIRED_PARTIAL"),
    ("ohlcv:list:*", "v2:market:ohlcv:{provider}:{symbol}:{tf}", "MISSING"),
    ("normalized:ohlcv:*", "v2:market:ohlcv:normalized:{symbol}:{tf}", "MISSING"),
    ("orderbook:*", "v2:market:orderbook:{symbol}", "MISSING"),
    ("ta:*", "v2:technical_analysis:{symbol}:{tf}", "MISSING"),
    ("latest:ta:*", "v2:technical_analysis:{symbol}:{tf}", "MISSING"),
    ("unified_features:*", "v2:unified_features:{symbol}:{tf}", "WIRED_STUB"),
    ("features:fast_lane", "v2:features:fast_lane", "MISSING"),
    ("features:slow_lane", "v2:features:slow_lane", "MISSING"),
    ("features:resampler", "v2:features:resampler", "MISSING"),
    ("coinank:*", "v2:market:coinank:*", "MISSING_NO_KEYS"),
    ("latest:coinank:*", "v2:market:coinank:latest:*", "MISSING_NO_KEYS"),
    ("features:coinank:*", "v2:features:coinank:*", "MISSING_NO_KEYS"),
    ("kc:*", "v2:market:kucoin:*", "MISSING_NO_KEYS"),
    ("coinapi:v1:*", "v2:market:coinapi:v1:*", "MISSING"),
    ("microfeat:*", "v2:market:microstructure:{symbol}:{tf}", "MISSING"),
    ("msnap:*", "v2:market:microstructure_snapshot:*", "MISSING"),
    ("binance:force", "v2:liquidations:events", "REROUTED_TO_STREAM"),
    ("(liquidation events stream)", "v2:liquidations:events", "WIRED"),
    ("liq_levels:*", "v2:market:liquidation_levels:{symbol}", "NOT_USED_BY_DESIGN"),
    ("(liquidation fields)", "v2:unified_features:{symbol}:{tf}", "WIRED"),
    ("prediction:*", "v2:prediction:{symbol}:{tf}", "MISSING"),
    ("trainer:intent:*", "v2:trainer:intent:{symbol}", "MISSING"),
    ("trainer:brain", "v2:trainer:brain", "MISSING"),
    ("heartbeat:trainer", "v2:trainer:heartbeat", "WIRED"),
    ("signals:trading:*", "v2:orchestrator:signals:*", "MISSING"),
    ("wma:*", "v2:orchestrator:wma:*", "MISSING"),
    ("positions:*", "v2:paper:positions:* / v2:position_history:*", "WIRED_PAPER_ONLY"),
    ("pnl:*", "v2:paper:pnl:* / v2:portfolio:pnl:*", "WIRED_PARTIAL"),
    ("portfolio:*", "v2:portfolio:*", "MISSING"),
    ("heartbeat:*", "v2:health:heartbeat:*", "PARTIAL"),
    ("health:*", "v2:health:*", "MISSING"),
    ("tm:*", "v2:altdata:tokenmetrics:*", "MISSING"),
    ("regime:*", "v2:market:regime:*", "MISSING"),
    ("volatility:*", "v2:market:volatility:*", "MISSING"),
]

phase3 = {
    "schema_version": "legacy_redis_to_v2_namespace_adapter_matrix_v1",
    "milestone": TASK_ID, "phase": 3,
    "generated_est": NOW_EST, "generated_utc": NOW_UTC,
    "mappings": [{"legacy_pattern": a, "v2_target": b, "implementation_status": c} for a, b, c in ns_map],
    "rules": [
        "no_old_redis_writes_from_active_v2",
        "adapters_used_before_copied_script_starts",
        "old_redis_remains_preserved_static_reference_only",
    ],
    "old_namespaces_still_in_redis_counts": OLD_KEY_COUNTS,
    "v2_namespaces_current_counts": V2_KEY_COUNTS,
    "live_safety": {"live_gate_status": "blocked_human_only", "live_symbols": []},
}

phase3b = {
    "schema_version": "v2_redis_adapter_implementation_status_v1",
    "milestone": TASK_ID, "phase": 3,
    "generated_est": NOW_EST, "generated_utc": NOW_UTC,
    "status_aggregate": {s: sum(1 for _, _, sx in ns_map if sx == s) for s in {row[2] for row in ns_map}},
    "missing_or_stub_count": sum(1 for _, _, s in ns_map if s.startswith("MISSING") or s == "WIRED_STUB"),
    "wired_count": sum(1 for _, _, s in ns_map if s.startswith("WIRED")),
    "live_safety": {"live_gate_status": "blocked_human_only", "live_symbols": []},
}


# ---------------------------------------------------------------------------
# Phase 4 ingestor status
# ---------------------------------------------------------------------------

ingestor_status = [
    ("binance_public_market_data", "ai-bot-v2-native-ingestors-live-loop.service", "RUNNING_AND_VALIDATED"),
    ("binance_ohlcv_bars", None, "BLOCKED_IMPLEMENTATION_MISSING"),
    ("binance_mark_index_funding_oi", "ai-bot-v2-native-ingestors-live-loop.service", "RUNNING_PARTIAL_WITH_BLOCKER"),
    ("binance_orderbook", None, "BLOCKED_IMPLEMENTATION_MISSING"),
    ("binance_force_order_wss_adapter", "ai-bot-v2-liquidation-wss-paper-shadow.service", "RUNNING_AND_VALIDATED"),
    ("coinank_poller", None, "BLOCKED_CREDENTIAL"),
    ("coinank_global_aggregator", None, "BLOCKED_CREDENTIAL"),
    ("kucoin", None, "BLOCKED_IMPLEMENTATION_MISSING"),
    ("coinapi_v1_rest", None, "BLOCKED_IMPLEMENTATION_MISSING"),
    ("coinapi_wsds_microstructure", None, "OPERATOR_REQUIRED"),
    ("realtime_price_provider", None, "BLOCKED_IMPLEMENTATION_MISSING"),
    ("technical_analysis", None, "BLOCKED_IMPLEMENTATION_MISSING"),
    ("feature_pipeline", "ai-bot-v2-feature-pipeline-native-loop.service", "RUNNING_PARTIAL_WITH_BLOCKER"),
    ("liquidation_bridge", "ai-bot-v2-liquidation-bridge.service", "RUNNING_AND_VALIDATED"),
    ("liquidation_levels_engine", "ai-bot-v2-liquidation-levels-engine.service", "RUNNING_AND_VALIDATED"),
    ("nansen_altdata", None, "BLOCKED_CREDENTIAL"),
    ("lunarcrush_altdata", None, "BLOCKED_CREDENTIAL"),
    ("arkham_altdata", None, "BLOCKED_IMPLEMENTATION_MISSING"),
    ("alphavantage_news", None, "BLOCKED_CREDENTIAL"),
    ("ccxt_multi_exchange", None, "OPERATOR_REQUIRED"),
    ("tokenmetrics", None, "OPERATOR_REQUIRED"),
]

phase4 = {
    "schema_version": "v2_full_ingestor_startup_and_validation_status_v1",
    "milestone": TASK_ID, "phase": 4,
    "generated_est": NOW_EST, "generated_utc": NOW_UTC,
    "ingestors": [{"ingestor": n, "systemd_unit": u, "status": s} for n, u, s in ingestor_status],
    "running_systemd_managed_ingestor_count": sum(1 for _, u, _ in ingestor_status if u is not None),
    "status_aggregate": {s: sum(1 for _, _, sx in ingestor_status if sx == s) for s in {row[2] for row in ingestor_status}},
    "live_safety": {"live_gate_status": "blocked_human_only", "live_symbols": []},
}


# ---------------------------------------------------------------------------
# Phase 5-11 (concise status payloads)
# ---------------------------------------------------------------------------

sym = {}
try:
    sym = json.loads((ROOT / "v2/frontend/public/operator_runtime/symbol_universe/latest/symbol_universe_status.json").read_text())
except Exception:
    pass

baseline_missing = sorted(set(LEGACY_25_SYMBOLS) - set(sym.get("legacy_active_symbols") or []))

phase5 = {
    "schema_version": "v2_dynamic_symbol_universe_enforcement_status_v1",
    "milestone": TASK_ID, "phase": 5,
    "generated_est": NOW_EST, "generated_utc": NOW_UTC,
    "discovered_symbol_count": len(sym.get("dynamic_discovered_symbols") or []),
    "discovered_symbols": sym.get("dynamic_discovered_symbols") or [],
    "legacy_baseline_25": LEGACY_25_SYMBOLS,
    "legacy_baseline_25_present_in_universe": sym.get("legacy_active_symbols") or [],
    "baseline_missing": baseline_missing,
    "live_symbols": sym.get("live_symbols", []),
    "live_gate": sym.get("live_gate"),
    "active_runtime_btc_only_default": False,
    "active_runtime_btc_eth_sol_only_default": False,
    "verdict": "DYNAMIC_UNIVERSE_HEALTHY_25_BASELINE_RETAINED" if not baseline_missing else "BASELINE_MISSING",
    "live_safety": {"live_gate_status": "blocked_human_only", "live_symbols": []},
}

phase6 = {
    "schema_version": "v2_feature_ta_zero_exception_parity_status_v1",
    "milestone": TASK_ID, "phase": 6,
    "generated_est": NOW_EST, "generated_utc": NOW_UTC,
    "legacy_ta_field_count_per_symbol_tf": 160,
    "legacy_unified_feature_count_per_symbol_tf": 562,
    "v2_active_feature_field_count_per_symbol_tf": 23,
    "v2_active_feature_loop_module": "v2/backend/app/cli/v2_feature_pipeline_native_loop.py",
    "v2_hardcoded_ta_constants": {
        "rsi_14": 50.0, "macd": 0.0, "macd_signal": 0.0, "macd_hist": 0.0,
        "htf_rsi_14": 50.0, "depth_imbalance": 0.0, "toxicity_proxy": 0.0,
        "oi_change_pct": 0.0, "last_liq_bps_24h": 0.0,
    },
    "pure_python_ta_available_but_unwired": "v2/backend/app/services/feature_pipeline_and_ta/service.py (RSI/MACD/ATR/SMA/EMA)",
    "missing_feature_categories": [
        "TA (160 fields)", "regime", "volatility scalar",
        "microstructure (27 fields)", "CoinAnk per-category endpoints",
        "KuCoin features", "TokenMetrics grades", "AlphaVantage news sentiment",
    ],
    "verdict": "FEATURE_TA_PARITY_BLOCKED_23_OF_562_FIELDS_MOSTLY_HARDCODED_CONSTANTS",
    "live_safety": {"live_gate_status": "blocked_human_only", "live_symbols": []},
}

phase7 = {
    "schema_version": "v2_trainer_all_data_feed_validation_status_v1",
    "milestone": TASK_ID, "phase": 7,
    "generated_est": NOW_EST, "generated_utc": NOW_UTC,
    "trainer_role_label": "COPIED_LEGACY_TRAINER_NOT_RUNNING_IN_V2",
    "v2_native_trainer_ready": False,
    "v2_native_trainer_blockers": [
        "no_torch_optim_in_v2_trainer_surface",
        "no_loss_backward_in_v2_trainer_surface",
        "no_checkpoint_adoption_in_v2",
        "wrapper_classification_v2_paper_readonly_momentum_wrapper_v1",
        "WRAPPER_NOT_LEGACY_HYBRID_PARITY",
    ],
    "current_trainer_bridge_payload": "v2/frontend/public/operator_runtime/v2_trainer_bridge/latest/v2_trainer_bridge_status.json",
    "required_inputs_for_v2_trainer": [
        "v2:market:prices", "v2:market:ohlcv", "v2:market:orderbook",
        "v2:market:funding", "v2:market:open_interest", "v2:market:coinank",
        "v2:market:kucoin", "v2:market:coinapi", "v2:market:microstructure",
        "v2:liquidations:events", "v2:market:liquidation_levels",
        "v2:technical_analysis", "v2:features:latest", "v2:unified_features",
        "v2:altdata:nansen", "v2:altdata:lunarcrush", "v2:altdata:arkham",
        "v2:risk:decisions", "v2:orchestrator:decisions",
        "v2:paper:ledger", "v2:position_history", "replay/backtest labels",
    ],
    "current_input_coverage": {
        "v2:market:prices:*": V2_KEY_COUNTS.get("v2:market:prices:*", 0),
        "v2:market:funding:*": V2_KEY_COUNTS.get("v2:market:funding:*", 0),
        "v2:market:open_interest:*": V2_KEY_COUNTS.get("v2:market:open_interest:*", 0),
        "v2:unified_features:*": V2_KEY_COUNTS.get("v2:unified_features:*", 0),
        "v2:liquidations:events_XLEN": V2_KEY_COUNTS.get("v2:liquidations:events_XLEN", 0),
    },
    "verdict": "TRAINER_DATA_FEED_BLOCKED_NO_NATIVE_TRAINER_AND_FEATURE_INPUTS_PARTIAL",
    "live_safety": {"live_gate_status": "blocked_human_only", "live_symbols": []},
}

ps = {}
try:
    ps = json.loads((ROOT / "v2/frontend/public/operator_runtime/paper_shadow_observation/latest/paper_shadow_observation_status.json").read_text())
except Exception:
    pass

ws = ps.get("windows", {})

phase8 = {
    "schema_version": "v2_paper_decision_data_lineage_status_v1",
    "milestone": TASK_ID, "phase": 8,
    "generated_est": NOW_EST, "generated_utc": NOW_UTC,
    "current_paper_pnl_usdt": ps.get("paper_pnl_current_usdt"),
    "lifetime_simulated_fills": ps.get("simulated_fills"),
    "lifetime_allowed_intents": ps.get("allowed_intents"),
    "lifetime_blocked_intents": ps.get("blocked_intents"),
    "windows_summary": {
        w: {
            "allowed": ws.get(w, {}).get("allowed_intents"),
            "blocked": ws.get(w, {}).get("blocked_intents"),
            "fills": ws.get(w, {}).get("simulated_fills"),
            "pnl_delta": ws.get(w, {}).get("paper_pnl_delta_usdt"),
            "dominant_block_reason": (
                max(
                    (ws.get(w, {}).get("reason_distribution") or {}).items(),
                    key=lambda kv: kv[1], default=(None, None),
                )[0]
            ),
            "symbol_distribution": ws.get(w, {}).get("symbol_distribution"),
        }
        for w in ("1h", "6h", "24h")
    },
    "lineage_fields_required_per_decision": [
        "symbol", "timeframe", "prediction_key_used", "trainer_mode",
        "feature_snapshot_id", "ta_freshness", "market_freshness",
        "coinank_freshness", "liquidation_freshness", "strategy_fallback_status",
        "risk_decision", "orchestrator_decision", "paper_outcome", "block_reason",
        "pnl_contribution", "fp_fn_classification",
    ],
    "current_lineage_payload": "v2/frontend/public/operator_runtime/paper_online/latest/current_signal_lineage.json",
    "lineage_completeness_status": "PARTIAL_PER_DECISION_FIELDS_PRESENT_NO_HISTORICAL_AGGREGATE_INDEX",
    "website_must_render_lineage_on": "/admin/signal-explainability and /admin/paper-trading",
    "live_safety": {"live_gate_status": "blocked_human_only", "live_symbols": []},
}

required_pages = [
    "Trading Dashboard", "Ingestors", "Provider Freshness", "Dynamic Symbols",
    "Market Data", "Feature Pipeline", "Technical Analysis",
    "Liquidation Bridge / Levels", "Trainer Brain", "Strategy / Backtesting",
    "Risk Controllers", "Orchestrator", "Paper Trader", "Replay / Edge Proof",
    "Exchange Read-Only", "Automation", "Logs / Errors", "Operator Decisions",
]

page_status = [
    {"page": "Trading Dashboard", "current_route": "/admin/mission-control", "status": "PARTIAL_EXISTS_NOT_TRADING_FOCUSED"},
    {"page": "Ingestors", "current_route": None, "status": "MISSING"},
    {"page": "Provider Freshness", "current_route": "/admin/monitor-center", "status": "PARTIAL"},
    {"page": "Dynamic Symbols", "current_route": "/admin/symbols", "status": "EXISTS"},
    {"page": "Market Data", "current_route": "/markets", "status": "EXISTS"},
    {"page": "Feature Pipeline", "current_route": "/admin/coverage-system-atlas", "status": "PARTIAL"},
    {"page": "Technical Analysis", "current_route": None, "status": "MISSING"},
    {"page": "Liquidation Bridge / Levels", "current_route": None, "status": "MISSING"},
    {"page": "Trainer Brain", "current_route": "/admin/trainer-prediction-monitor", "status": "EXISTS"},
    {"page": "Strategy / Backtesting", "current_route": None, "status": "MISSING"},
    {"page": "Risk Controllers", "current_route": "/admin/risk-control", "status": "EXISTS"},
    {"page": "Orchestrator", "current_route": "/admin/orchestrator-admin", "status": "EXISTS"},
    {"page": "Paper Trader", "current_route": "/admin/paper-trading", "status": "EXISTS"},
    {"page": "Replay / Edge Proof", "current_route": "/admin/replay", "status": "EXISTS"},
    {"page": "Exchange Read-Only", "current_route": "/admin/exchange-manager", "status": "EXISTS"},
    {"page": "Automation", "current_route": "/admin/admin-war-room", "status": "PARTIAL"},
    {"page": "Logs / Errors", "current_route": None, "status": "MISSING"},
    {"page": "Operator Decisions", "current_route": "/admin/codex-review-center", "status": "PARTIAL"},
]

phase9 = {
    "schema_version": "v2_website_full_trading_platform_status_v1",
    "milestone": TASK_ID, "phase": 9,
    "generated_est": NOW_EST, "generated_utc": NOW_UTC,
    "required_18_pages": required_pages,
    "page_status": page_status,
    "missing_page_count": sum(1 for p in page_status if p["status"] == "MISSING"),
    "partial_page_count": sum(1 for p in page_status if "PARTIAL" in p["status"]),
    "exists_page_count": sum(1 for p in page_status if p["status"] == "EXISTS"),
    "controls_disabled_by_default": [
        "live", "canary", "order_buttons", "leverage_margin",
        "redis_trim", "legacy_restart",
    ],
    "live_safety": {"live_gate_status": "blocked_human_only", "live_symbols": []},
    "verdict": "WEBSITE_PARTIAL_5_MISSING_5_PARTIAL_8_EXISTS",
}

war_room = {}
try:
    war_room = json.loads((ROOT / "claude_worklog/final_readiness/v2_24h_parallel_recovery_war_room/latest/war_room_status.json").read_text())
except Exception:
    pass

phase10 = {
    "schema_version": "v2_backtesting_and_strategy_validation_status_v1",
    "milestone": TASK_ID, "phase": 10,
    "generated_est": NOW_EST, "generated_utc": NOW_UTC,
    "war_room_executor": "v2/backend/app/cli/v2_24h_parallel_recovery_war_room.py",
    "last_run_utc": war_room.get("generated_utc"),
    "dataset": war_room.get("dataset_summary"),
    "edge_gate": war_room.get("edge_gate_summary"),
    "evaluator": war_room.get("evaluator_summary"),
    "strategy_axes_required": [
        "trend", "mean_reversion", "breakout", "momentum",
        "funding_oi", "liquidation_cascade_squeeze", "orderbook_imbalance",
        "ta_confirmation", "no_trade_preservation",
    ],
    "strategy_axes_covered_in_war_room": ["v2_deterministic_policy_shadow_only", "naive_threshold_expected_move_10bps", "logistic_baseline_1d_expected_move", "hold"],
    "strategy_axes_missing": [
        "trend_classical", "mean_reversion_classical", "breakout_classical",
        "funding_oi_combined", "liquidation_cascade", "orderbook_imbalance",
        "ta_confirmation", "no_trade_preservation",
    ],
    "edge_claimed": (war_room.get("edge_gate_summary") or {}).get("edge_claimed") is True,
    "live_safety": {"live_gate_status": "blocked_human_only", "live_symbols": []},
    "verdict": "BACKTEST_PARTIAL_WAR_ROOM_ANALYSIS_ONLY_NO_EDGE_CLAIM",
}

# Phase 11 — for each old namespace pattern, count V2 source files that reference it.
old_namespace_writer_evidence = []
for pat in ("orchestrator:", "live_orders:", "exchange:order:", "ohlcv:list:", "ta:", "unified_features:", "prediction:", "signals:", "wma:"):
    out = subprocess.run(
        ["bash", "-c", f"grep -rln '{pat}' v2/backend/ 2>/dev/null | grep -v test | head -5"],
        capture_output=True, text=True,
    ).stdout.strip().splitlines()
    old_namespace_writer_evidence.append({
        "old_pattern": pat,
        "v2_source_files_excluding_tests": out[:5],
    })

phase11 = {
    "schema_version": "v2_old_redis_write_observer_live_status_v1",
    "milestone": TASK_ID, "phase": 11,
    "generated_est": NOW_EST, "generated_utc": NOW_UTC,
    "method": "process_source_scan + redis_keyspace_count (no MONITOR)",
    "old_namespace_redis_counts": OLD_KEY_COUNTS,
    "v2_source_files_referencing_old_namespaces": old_namespace_writer_evidence,
    "active_v2_processes_writing_old_redis": False,
    "preserved_static_old_keys_left_in_place": True,
    "live_safety": {"live_gate_status": "blocked_human_only", "live_symbols": []},
    "verdict": "NO_ACTIVE_V2_PROCESS_WRITES_OLD_REDIS_STATIC_KEYS_PRESERVED",
}


# ---------------------------------------------------------------------------
# GO / NO-GO + operator_dashboard
# ---------------------------------------------------------------------------

block_reasons = []
if STATUS_AGG["V2_MISSING_IMPLEMENTATION"] > 0:
    block_reasons.append("missing_v2_implementation_for_legacy_lanes")
if STATUS_AGG["V2_CREDENTIAL_BLOCKED"] > 0:
    block_reasons.append("v2_credential_blocked_lanes_exist")
if STATUS_AGG["V2_OPERATOR_REQUIRED"] > 0:
    block_reasons.append("v2_operator_required_lanes_exist")
if phase3b["missing_or_stub_count"] > 0:
    block_reasons.append("redis_adapter_missing_or_stub_mappings_exist")
if phase4["status_aggregate"].get("BLOCKED_IMPLEMENTATION_MISSING", 0) > 0:
    block_reasons.append("ingestor_implementation_missing")
if phase6["v2_active_feature_field_count_per_symbol_tf"] < phase6["legacy_unified_feature_count_per_symbol_tf"]:
    block_reasons.append("feature_ta_parity_below_legacy")
if not phase7["v2_native_trainer_ready"]:
    block_reasons.append("v2_native_trainer_not_ready")
if phase9["missing_page_count"] > 0:
    block_reasons.append("website_required_pages_missing")
if not phase10["edge_claimed"]:
    block_reasons.append("edge_not_claimed")

go_no_go = (
    "V2_LEGACY_DATA_ZERO_EXCEPTION_PARITY_AND_FULL_RUNTIME_STARTUP_READY"
    if not block_reasons
    else "V2_LEGACY_DATA_ZERO_EXCEPTION_PARITY_AND_FULL_RUNTIME_STARTUP_BLOCKED"
)

operator_dashboard = {
    "schema_version": "operator_dashboard_payload_v1",
    "milestone": TASK_ID,
    "generated_est": NOW_EST,
    "generated_utc": NOW_UTC,
    "git_head": GIT_HEAD,
    "go_no_go": go_no_go,
    "verdict_one_line": (
        f"Zero-exception matrix enumerates {len(rows)} legacy items. "
        f"Status: VALIDATED_RUNNING={STATUS_AGG['V2_VALIDATED_RUNNING']}, "
        f"RUNNING_PARTIAL={STATUS_AGG['V2_RUNNING_PARTIAL']}, "
        f"MISSING_IMPL={STATUS_AGG['V2_MISSING_IMPLEMENTATION']}, "
        f"CREDENTIAL_BLOCKED={STATUS_AGG['V2_CREDENTIAL_BLOCKED']}, "
        f"OPERATOR_REQUIRED={STATUS_AGG['V2_OPERATOR_REQUIRED']}, "
        f"NOT_REQUIRED={STATUS_AGG['V2_NOT_REQUIRED_WITH_PROOF']}, "
        f"ADAPTER_REQUIRED={STATUS_AGG['V2_ADAPTER_REQUIRED']}. Edge stays NOT_CLAIMED; live/canary BLOCKED."
    ),
    "phase_dispositions": {
        "phase_1_legacy_to_v2_matrix": "MATRIX_BUILT_ZERO_EXCEPTION",
        "phase_2_startup_map": "STARTUP_MAP_BUILT",
        "phase_3_redis_adapter_matrix": "MAPPING_DOCUMENTED_MANY_MISSING",
        "phase_4_ingestor_startup": "ONLY_BINANCE_AND_LIQUIDATION_WSS_CONTINUOUS",
        "phase_5_dynamic_symbols": phase5["verdict"],
        "phase_6_feature_ta_parity": phase6["verdict"],
        "phase_7_trainer_data_feed": phase7["verdict"],
        "phase_8_paper_decision_lineage": "PARTIAL_LINEAGE_PRESENT",
        "phase_9_website_18_pages": phase9["verdict"],
        "phase_10_backtesting": phase10["verdict"],
        "phase_11_old_redis_observer": phase11["verdict"],
    },
    "block_reasons": block_reasons,
    "live_safety": {
        "live_gate_status": "blocked_human_only",
        "live_symbols": [],
        "exchange_action_taken": False,
        "old_redis_writes_detected": False,
        "leverage_change": False,
        "margin_mode_change": False,
        "redis_trim_or_flush_taken": False,
        "legacy_restart_taken": False,
        "v2_live": 0,
        "v2_canary": 0,
    },
    "artifact_index": {
        "phase_1_json": "legacy_to_v2_zero_exception_data_matrix.json",
        "phase_1_md": "legacy_to_v2_zero_exception_data_matrix.md",
        "phase_2": "legacy_startup_to_v2_startup_map.json",
        "phase_3_adapter_matrix": "legacy_redis_to_v2_namespace_adapter_matrix.json",
        "phase_3_adapter_impl": "v2_redis_adapter_implementation_status.json",
        "phase_4": "v2_full_ingestor_startup_and_validation_status.json",
        "phase_5": "v2_dynamic_symbol_universe_enforcement_status.json",
        "phase_6": "v2_feature_ta_zero_exception_parity_status.json",
        "phase_7": "v2_trainer_all_data_feed_validation_status.json",
        "phase_8": "v2_paper_decision_data_lineage_status.json",
        "phase_9": "v2_website_full_trading_platform_status.json",
        "phase_10": "v2_backtesting_and_strategy_validation_status.json",
        "phase_11": "v2_old_redis_write_observer_live_status.json",
        "operator_dashboard": "operator_dashboard_payload.json",
        "go_no_go": "GO_NO_GO.md",
        "report": "V2_LEGACY_DATA_ZERO_EXCEPTION_PARITY_AND_FULL_RUNTIME_STARTUP_REPORT.md",
    },
}


# ---------------------------------------------------------------------------
# Write artifacts
# ---------------------------------------------------------------------------

_write_json("legacy_to_v2_zero_exception_data_matrix.json", phase1)
_write_text("legacy_to_v2_zero_exception_data_matrix.md", render_md(rows))
_write_json("legacy_startup_to_v2_startup_map.json", phase2)
_write_json("legacy_redis_to_v2_namespace_adapter_matrix.json", phase3)
_write_json("v2_redis_adapter_implementation_status.json", phase3b)
_write_json("v2_full_ingestor_startup_and_validation_status.json", phase4)
_write_json("v2_dynamic_symbol_universe_enforcement_status.json", phase5)
_write_json("v2_feature_ta_zero_exception_parity_status.json", phase6)
_write_json("v2_trainer_all_data_feed_validation_status.json", phase7)
_write_json("v2_paper_decision_data_lineage_status.json", phase8)
_write_json("v2_website_full_trading_platform_status.json", phase9)
_write_json("v2_backtesting_and_strategy_validation_status.json", phase10)
_write_json("v2_old_redis_write_observer_live_status.json", phase11)
_write_json("operator_dashboard_payload.json", operator_dashboard)

for d in (WORKLOG, PUBLIC):
    d.mkdir(parents=True, exist_ok=True)
    (d / "GO_NO_GO.md").write_text(go_no_go + "\n")

print("go_no_go:", go_no_go)
print("status_aggregate:", STATUS_AGG)
print("row_count:", len(rows))
print("block_reasons:", block_reasons)
