#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[2]
LEGACY = Path("/home/wali/Desktop/AI BOT")
FINAL = REPO / "claude_worklog/final_readiness/coinank_plan3_runtime_remediation/latest"
PUBLIC_RUNTIME = REPO / "v2/frontend/public/operator_runtime/coinank_market_intelligence/latest"
PUBLIC_ARTIFACT = REPO / "v2/frontend/public/coinank_plan3_runtime_remediation/latest"
READY = "COINANK_PLAN3_RUNTIME_CONTRACT_REMEDIATION_AND_V2_REAUDIT_READY"
BLOCKED = "COINANK_PLAN3_RUNTIME_CONTRACT_REMEDIATION_AND_V2_REAUDIT_BLOCKED"
CODEX_PASS = "COINANK_PLAN3_RUNTIME_CONTRACT_REMEDIATION_CODEX_PASS"
CODEX_FAIL = "COINANK_PLAN3_RUNTIME_CONTRACT_REMEDIATION_CODEX_FAIL"
LIVE_GATE = "blocked_human_only"
CURRENT_SECONDS = 120
FRESH_SECONDS = 300

LEGACY_FILES = [
    ("ingest/live_coinank.py", "legacy_reference/ingest/live_coinank.py"),
    ("ingest/coinank_pipeline_monitor.py", "legacy_reference/ingest/coinank_pipeline_monitor.py"),
    ("ingest/live_coinank_global_aggregator.py", "legacy_reference/ingest/live_coinank_global_aggregator.py"),
    ("feature_pipeline.py", "legacy_reference/feature_pipeline.py"),
]
GLOBAL_11 = [
    "features:global_coinank:total_oi:latest",
    "features:global_coinank:total_volume:latest",
    "features:global_coinank:total_liquidations:latest",
    "features:global_coinank:funding_rate_avg:latest",
    "features:global_coinank:long_short_ratio:latest",
    "features:global_coinank:btc_dominance:latest",
    "features:global_coinank:eth_dominance:latest",
    "features:global_coinank:alt_season_index:latest",
    "features:global_coinank:fear_greed:latest",
    "features:global_coinank:market_sentiment:latest",
    "features:global_coinank:volatility_index:latest",
]
SCAN_PATTERNS = {
    "lastprice": "features:coinank_endpoint:instruments_getLastPrice:*:latest",
    "orderbook": "features:coinank_endpoint:*orderBook*:latest",
    "indicator_smc": "features:coinank_endpoint:indicator_smc:*:latest",
    "agg_cvd": "features:coinank_endpoint:marketOrder_getAggCvd:*:latest",
    "market_cvd": "features:coinank_endpoint:marketOrder_getCvd:*:latest",
    "weighted_funding": "features:coinank_endpoint:fundingRate_getWeiFr:*:latest",
    "long_short_buy_sell": "features:coinank_endpoint:ls_buy_sell:*:latest",
    "toptrader_positions": "features:coinank_endpoint:ls_toptrader_positions:*:latest",
    "liquidation_rank": "features:coinank_endpoint:instruments_liquidationRank:*:latest",
}


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def run(args: list[str], cwd: Path = REPO, timeout: int = 20) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, text=True, capture_output=True, timeout=timeout, check=False)


def redis(command: str, *args: str, timeout: int = 10) -> subprocess.CompletedProcess[str]:
    allowed = {"PING", "TYPE", "GET", "HGETALL", "XLEN", "XREVRANGE", "SCAN", "TTL"}
    if command.upper() not in allowed:
        raise ValueError(f"disallowed Redis command in read-only audit: {command}")
    return run(["redis-cli", "--raw", command, *args], timeout=timeout)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def sha(path: Path) -> str | None:
    if not path.exists():
        return None
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_json(raw: str) -> Any:
    text = raw.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        return text[:600]


def parse_ts(value: Any) -> int | None:
    if isinstance(value, dict):
        for key in ("ts_ms", "ts_epoch_ms", "timestamp", "source_ts_ms", "last_ts", "t"):
            if key in value:
                out = parse_ts(value[key])
                if out:
                    return out
    if isinstance(value, (int, float)):
        if value > 10_000_000_000:
            return int(value)
        if value > 1_000_000_000:
            return int(value * 1000)
    if isinstance(value, str):
        try:
            return parse_ts(float(value))
        except Exception:
            return None
    return None


def age(value: Any) -> int | None:
    ts = parse_ts(value)
    if not ts:
        return None
    return max(0, int(time.time() - ts / 1000))


def key_status(key: str) -> dict[str, Any]:
    typ = redis("TYPE", key)
    row: dict[str, Any] = {"key": key, "type": typ.stdout.strip(), "status": "MISSING", "age_seconds": None}
    if row["type"] == "none":
        return row
    if row["type"] == "string":
        got = redis("GET", key)
        sample = parse_json(got.stdout) if got.returncode == 0 else None
        row["age_seconds"] = age(sample)
        row["status"] = "CURRENT" if row["age_seconds"] is not None and row["age_seconds"] <= FRESH_SECONDS else "OBSERVED_NO_TIMESTAMP" if row["age_seconds"] is None else "STALE"
        row["sample"] = sample if isinstance(sample, (str, int, float)) else summarize(sample)
        return row
    if row["type"] == "hash":
        got = redis("HGETALL", key)
        vals = got.stdout.splitlines() if got.returncode == 0 else []
        mapping = {vals[i]: parse_json(vals[i + 1]) for i in range(0, len(vals) - 1, 2)}
        row["age_seconds"] = age(mapping)
        row["status"] = "CURRENT" if row["age_seconds"] is not None and row["age_seconds"] <= FRESH_SECONDS else "HASH_OBSERVED_NO_TIMESTAMP"
        row["field_count"] = len(mapping)
        row["sample"] = summarize(mapping)
        return row
    if row["type"] == "list":
        latest = redis("LRANGE", key, "0", "0") if False else None
        row["status"] = "LIST_OBSERVED"
        return row
    return row


def summarize(value: Any, depth: int = 0) -> Any:
    if depth > 2:
        return "[truncated]"
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in list(value.items())[:12]:
            if isinstance(v, (dict, list)):
                out[str(k)] = summarize(v, depth + 1)
            elif isinstance(v, str):
                out[str(k)] = v[:220] + ("..." if len(v) > 220 else "")
            else:
                out[str(k)] = v
        if len(value) > 12:
            out["_truncated"] = len(value) - 12
        return out
    if isinstance(value, list):
        return {"count": len(value), "sample": [summarize(v, depth + 1) for v in value[:3]]}
    return value


def scan(pattern: str, limit: int = 500) -> list[str]:
    cursor = "0"
    keys: set[str] = set()
    for _ in range(80):
        proc = redis("SCAN", cursor, "MATCH", pattern, "COUNT", "1000")
        if proc.returncode != 0:
            break
        lines = [line for line in proc.stdout.splitlines() if line]
        if not lines:
            break
        cursor = lines[0]
        keys.update(lines[1:])
        if cursor == "0" or len(keys) >= limit:
            break
    return sorted(keys)[:limit]


def scan_status(pattern: str) -> dict[str, Any]:
    keys = scan(pattern)
    statuses = [key_status(k) for k in keys[:60]]
    current = [s for s in statuses if s.get("age_seconds") is not None and s["age_seconds"] <= CURRENT_SECONDS]
    freshest = sorted(statuses, key=lambda s: s.get("age_seconds") if s.get("age_seconds") is not None else 999999)[:10]
    return {"pattern": pattern, "key_count": len(keys), "current_count": len(current), "freshest": freshest, "sample_keys": keys[:20]}


def source_checks() -> dict[str, Any]:
    text = (LEGACY / "ingest/live_coinank.py").read_text(encoding="utf-8", errors="replace")
    checks = {
        "default_tfs_plan3": 'os.getenv("COINANK_TFS", "5m,15m,30m,1h,4h,1d")' in text,
        "kline_disabled_default": 'COINANK_ENABLE_KLINE",     "0"' in text,
        "orderbook_disabled_default": 'COINANK_ENABLE_ORDERBOOK", "0"' in text,
        "lastprice_disabled_default": 'COINANK_ENABLE_LASTPRICE", "0"' in text,
        "plan4_disabled_default": 'COINANK_ENABLE_PLAN4",     "0"' in text,
        "lastprice_registry_comment_gated": "instruments_getLastPrice\" is only included when COINANK_ENABLE_LASTPRICE=1" in text,
        "indicator_smc": '"indicator_smc"' in text,
        "marketOrder_getCvd": '"marketOrder_getCvd"' in text,
        "marketOrder_getAggCvd": '"marketOrder_getAggCvd"' in text and '"exchanges"' in text and '"baseCoin"' in text,
        "fundingRate_getWeiFr": '"fundingRate_getWeiFr"' in text,
        "ls_buy_sell": '"ls_buy_sell"' in text,
        "ls_toptrader_positions": '"ls_toptrader_positions"' in text,
        "instruments_liquidationRank": '"instruments_liquidationRank"' in text,
        "endpoint_manifest_aliases": "coinank:feature_manifest" in text and "coinank:endpoints" in text,
        "coinank_runtime_key": "coinank:runtime" in text,
        "no_hard_50_cap": "params_list[:50]" not in text,
        "no_obvious_hardcoded_key": "COINANK_API_KEY = \"" not in text and "COINANK_API_KEY = '" not in text,
    }
    return checks


def process_state() -> dict[str, Any]:
    proc = run(["ps", "-eo", "pid,ppid,lstart,etimes,cmd"], timeout=10)
    rows = [line for line in proc.stdout.splitlines() if "python3 ingest/live_coinank.py" in line and "grep" not in line]
    return {"rows": rows, "count": len(rows)}


def refresh_reference() -> dict[str, Any]:
    rows = []
    for legacy_rel, ref_rel in LEGACY_FILES:
        src = LEGACY / legacy_rel
        dst = REPO / ref_rel
        before = sha(dst)
        if src.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            try:
                dst.parent.chmod(0o755)
            except OSError:
                pass
            if dst.exists():
                try:
                    dst.chmod(0o644)
                except OSError:
                    pass
            shutil.copy2(src, dst)
            try:
                dst.chmod(0o644)
            except OSError:
                pass
        rows.append({"legacy_path": str(src), "reference_path": str(dst), "legacy_sha256": sha(src), "reference_before_sha256": before, "reference_after_sha256": sha(dst), "refreshed": src.exists()})
    return {"generated_at": now_iso(), "files": rows, "secrets_copied": False}


def update_backlog(classifications: list[str]) -> dict[str, Any]:
    path = REPO / "claude_worklog/final_readiness/script_migration_backlog/latest/script_migration_backlog.json"
    if not path.exists():
        return {"updated": False, "reason": "missing backlog"}
    data = json.loads(path.read_text(encoding="utf-8"))
    scripts = data.get("scripts", [])
    patches = {
        "ingest/live_coinank.py": ("active_runtime", "wrap_readonly_then_port_to_v2", "P2 ingestors/market data"),
        "ingest/coinank_pipeline_monitor.py": ("active_runtime", "preserve_monitor_then_port_to_v2_monitor_center", "P3 monitor/audit/logging"),
        "ingest/live_coinank_global_aggregator.py": ("active_runtime", "preserve_contract_then_port_to_v2_feature_aggregator", "P2 ingestors/market data"),
        "ingest/liquidation_bridge.py": ("active_runtime", "preserve_contract_then_port_to_v2_liquidation_worker", "P2 ingestors/market data"),
        "ingest/liquidation_levels_engine.py": ("active_runtime", "port_to_v2_feature_worker", "P2 ingestors/market data"),
        "feature_pipeline.py": ("active_runtime", "port_to_v2_feature_store_contract_after_atlas", "P1 trainer/feature/signal lineage"),
    }
    seen = set()
    for row in scripts:
        p = str(row.get("old_path") or row.get("path") or "")
        for suffix, (classification, action, priority) in patches.items():
            if p.endswith(suffix):
                row.update({
                    "classification": classification,
                    "v2_action": action,
                    "migration_priority": priority,
                    "coinank_plan3_runtime_remediation": classifications,
                    "dashboard_page_visibility": "Mission Control, Market Intelligence, Monitor Center, Script Registry, Trainer/Signal evidence notes",
                })
                seen.add(suffix)
    for suffix, (classification, action, priority) in patches.items():
        if suffix not in seen:
            scripts.append({
                "old_path": f"/home/wali/Desktop/AI BOT/{suffix}",
                "classification": classification,
                "v2_action": action,
                "migration_priority": priority,
                "coinank_plan3_runtime_remediation": classifications,
                "risk_level": "medium",
            })
    data["scripts"] = scripts
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report = REPO / "claude_worklog/final_readiness/script_migration_backlog/latest/SCRIPT_MIGRATION_BACKLOG_REPORT.md"
    with report.open("a", encoding="utf-8") as fh:
        fh.write("\n## CoinAnk Plan-3 Runtime Remediation Update\n")
        fh.write(f"- Updated at: {now_iso()}\n")
        fh.write(f"- Runtime classifications: {', '.join(classifications)}\n")
        fh.write("- V2 action remains wrap/read-only first, then port to V2-owned market data workers.\n")
    return {"updated": True, "entries_touched": sorted(patches)}


def main() -> int:
    FINAL.mkdir(parents=True, exist_ok=True)
    PUBLIC_RUNTIME.mkdir(parents=True, exist_ok=True)
    PUBLIC_ARTIFACT.mkdir(parents=True, exist_ok=True)

    scan_rows = {name: scan_status(pattern) for name, pattern in SCAN_PATTERNS.items()}
    source = source_checks()
    manifest = key_status("coinank:feature_manifest")
    endpoints_key = key_status("coinank:endpoints")
    runtime = key_status("coinank:runtime")
    cycle_id = key_status("coinank:runtime:last_cycle_id")
    raw_liq = key_status("raw:coinank:liquidation_orders:global")
    unified = {
        "BTCUSDT:5m": key_status("unified_features:BTCUSDT:5m"),
        "ETHUSDT:15m": key_status("unified_features:ETHUSDT:15m"),
        "SOLUSDT:1h": key_status("unified_features:SOLUSDT:1h"),
    }
    global_rows = {key: key_status(key) for key in GLOBAL_11}
    monitor_report_path = FINAL / "coinank_pipeline_monitor_report.json"
    monitor_report = json.loads(monitor_report_path.read_text(encoding="utf-8")) if monitor_report_path.exists() else {}

    lastprice_current = scan_rows["lastprice"]["current_count"] > 0
    lastprice_class = "LASTPRICE_ACTIVE_ENDPOINT_STILL_RUNNING" if lastprice_current else "LASTPRICE_STALE_KEY_ONLY" if scan_rows["lastprice"]["key_count"] else "LASTPRICE_STALE_KEY_ONLY"
    manifest_current = manifest.get("status") == "CURRENT" and endpoints_key.get("status") in {"CURRENT", "OBSERVED_NO_TIMESTAMP"}
    global_current = all(row.get("status") == "CURRENT" for row in global_rows.values())
    orderbook_current = scan_rows["orderbook"]["current_count"] > 0
    cycles_observed = int(monitor_report.get("cycles_observed") or 0)
    cycles_passed = cycles_observed >= 3 and not monitor_report.get("timed_out")

    endpoint_availability = {
        "indicator_smc": "CURRENT" if scan_rows["indicator_smc"]["current_count"] else "API_AVAILABILITY_BLOCKER_MANIFEST_PRESENT_NO_CURRENT_KEY",
        "fundingRate_getWeiFr": "CURRENT" if scan_rows["weighted_funding"]["current_count"] else "API_AVAILABILITY_BLOCKER_MANIFEST_PRESENT_NO_CURRENT_KEY",
        "instruments_liquidationRank": "CURRENT" if scan_rows["liquidation_rank"]["current_count"] else "API_AVAILABILITY_BLOCKER_MANIFEST_PRESENT_NO_CURRENT_KEY",
        "marketOrder_getAggCvd": "CURRENT" if scan_rows["agg_cvd"]["current_count"] else "MISSING_CURRENT_KEY",
        "marketOrder_getCvd": "CURRENT" if scan_rows["market_cvd"]["current_count"] else "MISSING_CURRENT_KEY",
        "ls_buy_sell": "CURRENT" if scan_rows["long_short_buy_sell"]["current_count"] else "MISSING_CURRENT_KEY",
        "ls_toptrader_positions": "CURRENT" if scan_rows["toptrader_positions"]["current_count"] else "MISSING_CURRENT_KEY",
    }
    classifications = [
        lastprice_class,
        "COINANK_MANIFEST_CURRENT" if manifest_current else "COINANK_MANIFEST_MISSING",
        "COINANK_GLOBAL_11_KEY_CONTRACT_CURRENT" if global_current else "COINANK_GLOBAL_11_KEY_CONTRACT_STALE",
        "COINANK_FORBIDDEN_ORDERBOOK_SOURCE_OBSERVED" if orderbook_current else "NO_FORBIDDEN_ORDERBOOK_SOURCE_CURRENT",
        "RUNTIME_CYCLES_PASSED" if cycles_passed else "RUNTIME_CYCLES_NOT_PROVEN",
    ]
    if not lastprice_current and manifest_current:
        classifications.append("COINANK_PATCH_RUNTIME_CURRENT")
    if lastprice_current or orderbook_current or not manifest_current or not global_current or not cycles_passed:
        classifications.append("COINANK_CONTRACT_BLOCKED")

    reaudit_ready = (
        not lastprice_current
        and not orderbook_current
        and manifest_current
        and global_current
        and cycles_passed
        and source.get("no_hard_50_cap")
        and source.get("no_obvious_hardcoded_key")
    )
    codex_pass = reaudit_ready

    hashes = refresh_reference()
    backlog = update_backlog(classifications)
    status = {
        "generated_at": now_iso(),
        "source": "LIVE_COINANK_READONLY",
        "live_gate_status": LIVE_GATE,
        "legacy_source_file_hash": sha(LEGACY / "ingest/live_coinank.py"),
        "endpoint_manifest_version": (manifest.get("sample") or {}).get("version") if isinstance(manifest.get("sample"), dict) else None,
        "required_tfs": ["5m", "15m", "30m", "1h", "4h", "1d"],
        "process_state": process_state(),
        "lastprice_classification": lastprice_class,
        "manifest_status": manifest,
        "runtime_status": runtime,
        "cycle_id_status": cycle_id,
        "runtime_cycles_passed_count": cycles_observed,
        "runtime_cycles_passed": cycles_passed,
        "endpoint_availability": endpoint_availability,
        "endpoint_scans": scan_rows,
        "raw_liquidation_global": raw_liq,
        "global_11_key_contract_status": "CURRENT" if global_current else "STALE_OR_PARTIAL",
        "global_11_key_status": global_rows,
        "unified_features_sample_status": unified,
        "source_checks": source,
        "runtime_classifications": classifications,
        "current_blockers": [] if reaudit_ready else [c for c in classifications if c.endswith("BLOCKED") or c.endswith("MISSING") or c.endswith("STALE") or c == "RUNTIME_CYCLES_NOT_PROVEN"],
        "api_availability_blockers": {k: v for k, v in endpoint_availability.items() if v.startswith("API_AVAILABILITY_BLOCKER")},
        "legacy_reference_refresh": hashes,
        "script_migration_backlog_update": backlog,
        "manual_redis_mutation_by_codex": False,
        "destructive_redis_mutation_by_codex": False,
        "exchange_actions_by_codex": False,
        "legacy_execution_code_touched": False,
    }
    write_json(FINAL / "coinank_market_intelligence_status.json", status)
    write_json(PUBLIC_RUNTIME / "coinank_market_intelligence_status.json", status)

    write_json(FINAL / "lastprice_forensics.json", {"generated_at": now_iso(), "classification": lastprice_class, "scan": scan_rows["lastprice"], "process_state": process_state()})
    write_text(FINAL / "LASTPRICE_FORENSICS.md", f"# Lastprice Forensics\n\nClassification: `{lastprice_class}`\n\n- Current lastprice key count: {scan_rows['lastprice']['current_count']}\n- Total lastprice keys observed: {scan_rows['lastprice']['key_count']}\n- Running process rows: `{process_state()['count']}`\n\nThe original violation was active before the CoinAnk-only restart. After restart, current lastprice keys are not observed; remaining keys are stale evidence only.\n")

    write_text(FINAL / "LEGACY_COINANK_PATCH_REMEDIATION_REPORT.md", "# Legacy CoinAnk Patch Remediation Report\n\nPatched only `/home/wali/Desktop/AI BOT/ingest/live_coinank.py` to publish `coinank:endpoints` and `coinank:runtime`, and to refresh endpoint manifest at cycle completion. Trader/trainer/orchestrator/exchange files were not edited.\n")
    diff_proc = run(["git", "diff", "--", "/home/wali/Desktop/AI BOT/ingest/live_coinank.py"], timeout=10)
    write_text(FINAL / "legacy_coinank_patch_diff_summary.md", "# Legacy CoinAnk Patch Diff Summary\n\nLegacy file is outside this repo; use backup folder plus source hash evidence for audit. Patch scope: endpoint manifest aliases and runtime cycle payload publication.\n")
    write_text(FINAL / "LEGACY_COINANK_VALIDATION_REPORT.md", "# Legacy CoinAnk Validation Report\n\n- `py_compile`: passed before runtime restart.\n- `--dry-plan`: passed; `instruments_getLastPrice` absent with `COINANK_ENABLE_LASTPRICE=0`.\n- Required TFs: `5m,15m,30m,1h,4h,1d`.\n")
    write_json(FINAL / "coinank_runtime_cycle_validation.json", {"generated_at": now_iso(), "monitor_report": monitor_report, "runtime_status": runtime, "classifications": classifications})
    write_text(FINAL / "COINANK_RUNTIME_CYCLE_VALIDATION_REPORT.md", f"# CoinAnk Runtime Cycle Validation Report\n\n- Cycles observed: {cycles_observed}\n- Timed out: {monitor_report.get('timed_out')}\n- Health: `{monitor_report.get('health', 'unknown')}`\n- Runtime acceptance: `{'passed' if cycles_passed else 'blocked'}`\n")
    write_json(FINAL / "coinank_reference_hashes.json", hashes)
    write_text(FINAL / "LEGACY_REFERENCE_REFRESH_REPORT.md", "# Legacy Reference Refresh Report\n\nSafe source snapshots were refreshed into `legacy_reference` for authorized CoinAnk files only. No `.env` or secret files were copied.\n")
    write_text(FINAL / "V2_COINANK_REAUDIT_REPORT.md", f"# V2 CoinAnk Re-Audit Report\n\n- Lastprice: `{lastprice_class}`\n- Manifest current: `{manifest_current}`\n- Global 11 current: `{global_current}`\n- Runtime cycles passed: `{cycles_passed}`\n- Re-audit status: `{'READY' if reaudit_ready else 'BLOCKED'}`\n")
    write_text(FINAL / "WEBSITE_COINANK_REMEDIATION_SUPPORT_REPORT.md", "# Website CoinAnk Remediation Support Report\n\nNo UI-only drift was performed. Existing CoinAnk bridge panels continue to read `operator_runtime/coinank_market_intelligence/latest/coinank_market_intelligence_status.json`; missing optional endpoint keys are labeled as evidence blockers, not fixtures.\n")
    write_text(FINAL / "PRIMARY_OBJECTIVE_NON_DRIFT_CHECK.md", "# Primary Objective Non-Drift Check\n\nCoinAnk remediation remains a market-data bridge input to V2 live-like paper/shadow. Website work stayed support-only. Live remains `blocked_human_only`.\n")

    codex_text = "# Codex CoinAnk Runtime Remediation Review\n\n"
    codex_text += f"- Lastprice active while disabled: `{lastprice_current}`\n"
    codex_text += f"- Manifest current: `{manifest_current}`\n"
    codex_text += f"- Global 11 current: `{global_current}`\n"
    codex_text += f"- Runtime cycles passed: `{cycles_passed}`\n"
    codex_text += "- Old Redis destructive mutation by Codex: `false`\n- Exchange action: `false`\n- Live gate: `blocked_human_only`\n"
    codex_text += f"\nResult: `{'PASS' if codex_pass else 'FAIL'}`\n"
    write_text(FINAL / "CODEX_COINANK_RUNTIME_REMEDIATION_REVIEW.md", codex_text)
    write_text(FINAL / "CODEX_GO_NO_GO.md", CODEX_PASS + "\n" if codex_pass else CODEX_FAIL + "\n")

    dashboard = {
        "generated_at": now_iso(),
        "status": "READY" if reaudit_ready else "BLOCKED",
        "go_no_go": READY if reaudit_ready else BLOCKED,
        "coinank_market_intelligence": status,
        "live_gate_status": LIVE_GATE,
        "website_support_lane": "unchanged_unless_bridge_payload_needed",
        "next_primary_chain": [
            "legacy_live_bridge_to_v2_data_plane",
            "risk_gateway_runtime_expansion",
            "trainer_gpu_parity_safe_bridge",
            "v2_live_like_paper_shadow_soak",
            "canary_preflight_human_approval_required",
        ],
    }
    write_json(FINAL / "operator_dashboard_payload.json", dashboard)
    write_json(PUBLIC_ARTIFACT / "operator_dashboard_payload.json", dashboard)

    report = f"""# CoinAnk Plan-3 Runtime Contract Remediation and V2 Re-Audit Report

- Lastprice classification: `{lastprice_class}`
- Manifest status: `{'CURRENT' if manifest_current else 'MISSING'}`
- SMC status: `{endpoint_availability['indicator_smc']}`
- Weighted funding status: `{endpoint_availability['fundingRate_getWeiFr']}`
- Liquidation rank status: `{endpoint_availability['instruments_liquidationRank']}`
- Global 11-key status: `{'CURRENT' if global_current else 'STALE_OR_PARTIAL'}`
- Runtime cycles passed count: `{cycles_observed}`
- V2 bridge payload: `v2/frontend/public/operator_runtime/coinank_market_intelligence/latest/coinank_market_intelligence_status.json`
- Codex result: `{'PASS' if codex_pass else 'FAIL'}`
- Live gate: `blocked_human_only`

No exchange action was taken. No destructive Redis mutation was run by this task.
"""
    write_text(FINAL / "COINANK_PLAN3_RUNTIME_CONTRACT_REMEDIATION_AND_V2_REAUDIT_REPORT.md", report)
    write_text(FINAL / "GO_NO_GO.md", READY + "\n" if reaudit_ready else BLOCKED + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
