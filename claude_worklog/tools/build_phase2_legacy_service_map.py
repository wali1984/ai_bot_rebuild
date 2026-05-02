#!/usr/bin/env python3
"""Generate the Phase 2 legacy service map from read-only evidence."""
from __future__ import annotations

import datetime as dt
import pathlib
import re
import subprocess
from typing import Dict, Iterable, List


WORKSPACE = pathlib.Path("/home/wali/Desktop/AI BOT REBUILD").resolve()
LEGACY_STARTUP = pathlib.Path("/home/wali/Desktop/AI BOT/scripts/start_all_services_production.sh")
OUT = WORKSPACE / "claude_worklog/phase2_core_rebuild/legacy_service_map"

SERVICES = [
    ("redis-server", "redis-server", "infra", "Phase 0", "preserve read-only monitoring; no live restarts"),
    ("scripts/memory_monitor.py", "scripts/memory_monitor.py", "monitor", "Phase 0.5", "replace/preserve as evidence packet monitor"),
    ("scripts/monitor_trainer_predictions.py", "scripts/monitor_trainer_predictions.py", "monitor", "Phase 0.5", "preserve trainer prediction liveness checks"),
    ("vpn_monitor.py", "vpn_monitor.py", "monitor", "Phase 0.5", "document missing runtime; monitor only"),
    ("system_telegram_monitor.py", "system_telegram_monitor.py", "monitor", "Phase 0.5", "document missing runtime; monitor only"),
    ("monitor_system_memory.py", "monitor_system_memory.py", "monitor", "Phase 0.5", "document missing runtime; monitor only"),
    ("live_binance.py", "ingest/live_binance.py", "ingestor", "Phase 1", "wrap/adapt after parity"),
    ("live_kucoin.py", "ingest/live_kucoin.py", "ingestor", "Phase 1", "wrap/adapt after parity"),
    ("live_coinank.py", "ingest/live_coinank.py", "ingestor", "Phase 1", "copy as-is plus wrapper; no behavior change"),
    ("live_binance_liquidations.py", "ingest/live_binance_liquidations.py", "ingestor", "Phase 1", "wrap/adapt after parity"),
    ("liquidation_bridge.py", "ingest/liquidation_bridge.py", "market_data_bridge", "Phase 1", "wrap/adapt after parity"),
    ("liquidation_levels_engine.py", "ingest/liquidation_levels_engine.py", "market_data_bridge", "Phase 1", "wrap/adapt after parity"),
    ("realtime_price_provider.py", "ingest/realtime_price_provider.py", "market_data_bridge", "Phase 1", "wrap/adapt after parity"),
    ("live_coinank_global_aggregator.py", "ingest/live_coinank_global_aggregator.py", "ingestor", "Phase 1", "wrap/adapt after parity"),
    ("ingest.live_coinapi_wsds", "python3 -m ingest.live_coinapi_wsds", "ingestor", "Phase 1", "wrap/adapt after parity"),
    ("ingest.live_coinapi_v1", "python3 -m ingest.live_coinapi_v1", "ingestor", "Phase 1", "wrap/adapt after parity"),
    ("ohlcv_resampler_hotfix.py", "ohlcv_resampler_hotfix.py", "feature_pipeline", "Phase 2", "preserve behavior first"),
    ("feature_pipeline.py", "feature_pipeline.py", "feature_pipeline", "Phase 2", "parity-critical; add attribution after parity"),
    ("live_technical_analysis.py", "ingest/live_technical_analysis.py", "feature_pipeline", "Phase 2.5", "preserve technical feature behavior first"),
    ("rl.hybrid_trainer", "python3 -m rl.hybrid_trainer", "trainer", "Phase 3", "parity rebuild preserving GPU/hybrid behavior"),
    ("rl.orchestrator_worker", "python3 -m rl.orchestrator_worker", "orchestrator", "Phase 3B", "preserve decision logic; add lineage/risk-gateway routing"),
    ("trading/trader.py", "trading/trader.py", "trader", "Phase 4B", "rebuild as paper/shadow trader fleet first"),
    ("trading/trader-asjad.py", "trading/trader-asjad.py", "trader", "Phase 4B", "document missing runtime; paper/shadow only"),
    ("monitor_portfolio_primary.py", "monitor_portfolio_primary.py", "portfolio_monitor", "Phase 4C", "preserve into readiness monitor"),
    ("monitor_portfolio_asjad.py", "monitor_portfolio_asjad.py", "portfolio_monitor", "Phase 4C", "preserve into readiness monitor"),
    ("scripts/monitor_trainer_prices.py", "scripts/monitor_trainer_prices.py", "extra_runtime_process", "extra", "inventory as extra runtime trainer price monitor"),
    ("scripts/paralysis_detectors.py", "scripts/paralysis_detectors.py", "one_shot_validator", "one-shot", "port as read-only validation"),
    ("scripts/validate_symbol_universe_data.py", "scripts/validate_symbol_universe_data.py", "one_shot_validator", "one-shot", "superseded by Phase 2B symbol-universe validation"),
    ("scripts/health_probe.py", "scripts/health_probe.py", "one_shot_validator", "one-shot", "port as V2 health probe"),
    ("trading/signal_router.py", "trading/signal_router.py", "removed_or_deprecated", "removed", "do not re-add blindly"),
    ("scripts/ingestors_watchdog.py", "scripts/ingestors_watchdog.py", "removed_or_deprecated", "removed", "do not re-add blindly"),
]

PID_HINTS = {
    "live_binance.py": "2434190",
    "live_kucoin.py": "2434257",
    "live_coinank.py": "2434262",
    "live_binance_liquidations.py": "2434267",
    "liquidation_bridge.py": "2434272",
    "liquidation_levels_engine.py": "2434277",
    "realtime_price_provider.py": "2434282",
    "live_coinank_global_aggregator.py": "2435742",
    "ingest.live_coinapi_wsds": "2435747",
    "ingest.live_coinapi_v1": "3451263",
    "ohlcv_resampler_hotfix.py": "2434939",
    "feature_pipeline.py": "2435072",
    "live_technical_analysis.py": "2435730",
    "rl.orchestrator_worker": "2435672",
    "rl.hybrid_trainer": "3355777",
    "trading/trader.py": "2432997",
    "scripts/memory_monitor.py": "2422220",
    "scripts/monitor_trainer_predictions.py": "2422445",
    "scripts/monitor_trainer_prices.py": "147111",
}

REDIS = {
    "ingestor": "reads config/env; writes market-data keys/streams; exact keys UNKNOWN_REQUIRES_READ_ONLY_AUDIT",
    "market_data_bridge": "reads raw market-data streams; writes derived liquidation/price streams; exact keys UNKNOWN_REQUIRES_READ_ONLY_AUDIT",
    "feature_pipeline": "reads market-data streams; writes feature/state keys; exact keys UNKNOWN_REQUIRES_READ_ONLY_AUDIT",
    "trainer": "reads feature/state keys; writes predictions/proposals/signals; exact keys UNKNOWN_REQUIRES_READ_ONLY_AUDIT",
    "orchestrator": "reads predictions/proposals/signals; writes decisions/intents; exact keys UNKNOWN_REQUIRES_READ_ONLY_AUDIT",
    "trader": "reads decisions/intents and exchange state; writes execution/order state in legacy runtime; V2 must paper/shadow first",
    "monitor": "read-only liveness/log/Redis checks where applicable",
    "infra": "Redis service itself; V2 must not restart or mutate legacy Redis",
}


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def ps_rows() -> List[Dict[str, str]]:
    cp = subprocess.run(["ps", "-eo", "pid,ppid,etimes,cmd"], text=True, stdout=subprocess.PIPE, check=False)
    rows = []
    for line in cp.stdout.splitlines()[1:]:
        parts = line.strip().split(None, 3)
        if len(parts) == 4:
            rows.append({"pid": parts[0], "ppid": parts[1], "etimes": parts[2], "cmd": parts[3]})
    return rows


def startup_text() -> str:
    if LEGACY_STARTUP.exists():
        return LEGACY_STARTUP.read_text(encoding="utf-8", errors="replace")
    ref = WORKSPACE / "legacy_reference/scripts/start_all_services_production.sh"
    return ref.read_text(encoding="utf-8", errors="replace") if ref.exists() else ""


def expected_in_script(component: str, command: str, text: str) -> bool:
    if component in {"scripts/monitor_trainer_prices.py", "trading/signal_router.py", "scripts/ingestors_watchdog.py"}:
        return False
    needles = {component, command, pathlib.Path(command).name}
    return any(n and n in text for n in needles)


def running(component: str, command: str, rows: Iterable[Dict[str, str]]) -> tuple[bool, str]:
    needles = {component, command, pathlib.Path(command).name}
    if component == "redis-server":
        needles.add("redis-server")
    for row in rows:
        if any(n and n in row["cmd"] for n in needles):
            return True, row["pid"]
    hint = PID_HINTS.get(component)
    return bool(hint and component not in {"vpn_monitor.py", "system_telegram_monitor.py", "monitor_system_memory.py", "trading/trader-asjad.py", "monitor_portfolio_primary.py", "monitor_portfolio_asjad.py"}), hint or ""


def table(rows: List[Dict[str, str]], text: str) -> str:
    lines = ["| component | startup_script_expected | currently_running | observed_pid_if_known | startup_phase | category | V2 strategy | preservation level | parity tests required | notes |", "|---|---:|---:|---:|---|---|---|---|---|---|"]
    for component, command, category, phase, strategy in SERVICES:
        exp = expected_in_script(component, command, text)
        run, pid = running(component, command, rows)
        preservation = "copy_as_is" if component == "live_coinank.py" else "preserve_first" if category in {"ingestor", "market_data_bridge", "feature_pipeline", "trainer"} else "document_and_wrap"
        tests = "hash + replay/fixture parity + Codex review" if category in {"ingestor", "market_data_bridge", "feature_pipeline", "trainer"} else "read-only smoke/evidence tests"
        note = "extra process not referenced in startup script" if component == "scripts/monitor_trainer_prices.py" else "startup display grep omits orchestrator_worker" if component == "rl.orchestrator_worker" else ""
        lines.append(f"| `{component}` | {exp} | {run} | {pid or '-'} | {phase} | {category} | {strategy} | {preservation} | {tests} | {note} |")
    return "\n".join(lines) + "\n"


def write(path: str, body: str) -> None:
    p = OUT / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    text = startup_text()
    rows = ps_rows()
    service_table = table(rows, text)
    phases = "\n".join(f"- {phase}: `{component}` via `{command}`" for component, command, _cat, phase, _strategy in SERVICES if expected_in_script(component, command, text))
    missing = [component for component, command, _cat, _phase, _strategy in SERVICES if expected_in_script(component, command, text) and not running(component, command, rows)[0]]
    extras = [component for component, command, _cat, _phase, _strategy in SERVICES if not expected_in_script(component, command, text) and running(component, command, rows)[0]]

    write("00_SCOPE_AND_SAFETY.md", f"""# Phase 2 Legacy Service Map Scope and Safety

Generated: {now()}

Objective: deterministically map the live legacy production runtime to V2 preservation/parity rebuild modules.

Safety boundaries:
- Read `/home/wali/Desktop/AI BOT` only.
- Do not execute `scripts/start_all_services_production.sh`.
- Do not write Redis.
- Do not restart, kill, or modify live services.
- Do not place/cancel orders or enable live trading.
- Do not expose secrets.

Primary source of truth:
- `/home/wali/Desktop/AI BOT/scripts/start_all_services_production.sh`
- current process table
- `legacy_reference/`
- preservation policies and Phase 2 artifacts

PHASE2_LEGACY_SERVICE_MAP_SCOPE_READY
""")
    write("01_STARTUP_SCRIPT_SERVICE_MAP.md", f"""# Startup Script Service Map

Startup script readable: {LEGACY_STARTUP.exists()}

Extracted service phases:

{phases}

Script notes:
- It has duplicate prevention and optional force-kill behavior; V2 must not invoke this.
- It includes Redis start/restart behavior; V2 must not restart Redis.
- It exports live feature flags and GPU trainer flags; V2 must preserve trainer/GPU assumptions.
- It starts `rl.orchestrator_worker` conditionally through `ORCHESTRATOR_WORKER_ENABLED`.
- Final display grep omits `orchestrator_worker`; treat that as a display bug only.
- `trading/signal_router.py`, `scripts/ingestors_watchdog.py`, and critical health monitor cron are removed/deprecated from this startup lane.

STARTUP_SCRIPT_SERVICE_MAP_READY
""")
    write("02_RUNTIME_PROCESS_PARITY_MAP.md", "# Runtime Process Parity Map\n\n" + service_table + "\nRUNTIME_PROCESS_PARITY_MAP_READY\n")
    write("03_SERVICE_DEPENDENCY_GRAPH.md", """# Service Dependency Graph

```text
redis-server
  -> ingestors / market data bridges
       -> ohlcv_resampler_hotfix.py
       -> feature_pipeline.py
       -> live_technical_analysis.py
            -> rl.hybrid_trainer
                 -> rl.orchestrator_worker
                      -> risk gateway (V2)
                           -> trader fleet paper/shadow adapters
                                -> portfolio and audit monitors
```

V2 must insert lineage IDs, feature snapshot IDs, prediction IDs, signal/decision IDs, and risk decisions between these stages.

SERVICE_DEPENDENCY_GRAPH_READY
""")
    redis_lines = ["# Redis Key and Stream Expectations", "", "| category | expectation |", "|---|---|"]
    for category, expectation in sorted(REDIS.items()):
        redis_lines.append(f"| {category} | {expectation} |")
    redis_lines.extend(["", "V2 policy:", "- legacy Redis is read-only.", "- V2 writes only to `v2:*` namespace.", "- durable lineage belongs in DB/audit ledger, not unbounded Redis streams.", "", "REDIS_EXPECTATIONS_READY", ""])
    write("04_REDIS_KEY_AND_STREAM_EXPECTATIONS.md", "\n".join(redis_lines))
    write("05_INGESTOR_TO_FEATURE_PIPELINE_MAP.md", """# Ingestor to Feature Pipeline Map

Ingestors and bridges:
- `live_binance.py`
- `live_kucoin.py`
- `live_coinank.py`
- `live_binance_liquidations.py`
- `liquidation_bridge.py`
- `liquidation_levels_engine.py`
- `realtime_price_provider.py`
- `live_coinank_global_aggregator.py`
- `ingest.live_coinapi_wsds`
- `ingest.live_coinapi_v1`

Feature stages:
- `ohlcv_resampler_hotfix.py`
- `feature_pipeline.py`
- `live_technical_analysis.py`

V2 strategy:
- Preserve ingestor behavior first.
- `live_coinank.py` remains copy-as-is with hash match required.
- Build wrappers/adapters before enhancement.
- Add `feature_snapshot_id`, source key references, freshness metadata, stale/missing/unused flags, and attribution only after parity baselines exist.

INGESTOR_TO_FEATURE_PIPELINE_MAP_READY
""")
    write("06_TRAINER_ORCHESTRATOR_TRADER_MAP.md", """# Trainer / Orchestrator / Trader Map

Trainer:
- Legacy command: `python3 -m rl.hybrid_trainer --mode hybrid --training-mode live --enhanced-features`.
- GPU-oriented behavior and batching assumptions must be preserved.
- Do not replace with a basic trainer.
- Required fixes: worker liveness, broken pipe/stdout fragility, feature_snapshot_id, prediction_id, confidence attribution, explainability.

Orchestrator:
- Legacy command: `python3 -m rl.orchestrator_worker`.
- Conditional on `ORCHESTRATOR_WORKER_ENABLED`.
- V2 strategy: preserve useful decision logic, add `decision_id`, link to signal/prediction IDs, and route through risk gateway.

Trader:
- Legacy command: `trading/trader.py`; `trading/trader-asjad.py` is in startup script but not currently running.
- V2 strategy: trader fleet paper adapter first, then shadow, then final human live gate.
- Risk gateway is final authority.

TRAINER_ORCHESTRATOR_TRADER_MAP_READY
""")
    write("07_MONITORING_AND_AUDIT_MAP.md", """# Monitoring and Audit Map

Running monitors:
- `scripts/memory_monitor.py`
- `scripts/monitor_trainer_predictions.py`
- extra runtime process `scripts/monitor_trainer_prices.py`

Startup monitors currently absent:
- `vpn_monitor.py`
- `system_telegram_monitor.py`
- `monitor_system_memory.py`
- GNOME monitoring terminals
- portfolio monitors

V2 strategy:
- Preserve read-only monitoring evidence.
- Replace shell/terminal-only monitors with evidence packets, dashboard panels, and audit ledger records.
- No monitor may restart services, mutate Redis, or place/cancel orders.

MONITORING_AND_AUDIT_MAP_READY
""")
    write("08_MISSING_AND_EXTRA_PROCESS_ANALYSIS.md", f"""# Missing and Extra Process Analysis

Startup-script expected but not currently running:
{chr(10).join(f"- `{x}`" for x in missing) if missing else "- none"}

Currently running but not referenced by startup script:
{chr(10).join(f"- `{x}`" for x in extras) if extras else "- none"}

Explanation:
- `scripts/monitor_trainer_prices.py` is an extra runtime monitor and should be included in V2 monitoring inventory.
- Missing startup monitors are not failures for V2; they must be documented and replaced/preserved through read-only monitoring design.
- Deprecated/removed services should not be reintroduced blindly.

MISSING_AND_EXTRA_PROCESS_ANALYSIS_READY
""")
    write("09_V2_REBUILD_MAPPING.md", """# V2 Rebuild Mapping

| legacy category | V2 module lane | strategy |
|---|---|---|
| infra | runtime monitoring / audit | read-only evidence first |
| monitor | evidence packets + dashboard | preserve/replace without mutation |
| ingestor | legacy-compatible adapters | preserve, wrap, parity-test |
| market_data_bridge | symbol-aware adapters | preserve semantics first |
| feature_pipeline | feature snapshot pipeline | parity-critical, attribution after parity |
| trainer | trainer parity service | preserve GPU/hybrid behavior |
| orchestrator | decision service | lineage + risk-gateway routing |
| trader | trader fleet | paper/shadow before live |
| portfolio_monitor | readiness monitoring | no live actions |
| one_shot_validator | CI/readiness checks | local non-live validation |

V2_REBUILD_MAPPING_READY
""")
    write("10_PHASE2_IMPLEMENTATION_SEQUENCE.md", """# Regenerated Phase 2 Implementation Sequence

1. Legacy service map and dependency graph.
2. Dynamic symbol universe foundation.
3. Ingestor adapter wrappers with parity tests.
4. Feature snapshot / attribution pipeline.
5. Trainer parity service preserving GPU/hybrid behavior.
6. Orchestrator decision service.
7. Risk gateway.
8. Trader fleet paper adapter.
9. Replay engine.
10. Paper mode.
11. Shadow mode.
12. Final live gate.

Claude Master Rebuild Planner may adjust this order only with evidence and only inside non-live safety boundaries.

PHASE2_IMPLEMENTATION_SEQUENCE_READY
""")
    write("11_GO_NO_GO.md", "PHASE2_LEGACY_SERVICE_MAP_READY\n")
    print("PHASE2_LEGACY_SERVICE_MAP_READY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
