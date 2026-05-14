"""V2 CoinAnk and liquidation bridge — standalone CLI worker.

Ports the legacy CoinAnk + Binance forced-order + liquidation bridge
responsibilities from the startup-baseline files (``live_coinank.py``,
``live_coinank_global_aggregator.py``, ``live_binance_liquidations.py``,
``liquidation_bridge.py``, ``liquidation_levels_engine.py``) into a single
V2-only worker. See
``claude_worklog/final_readiness/emergency_v2_runtime_migration/latest/workers/v2_coinank_and_liquidation_bridge_from_legacy_baseline_LEGACY_BASELINE_ANALYSIS.md``
for the SHA-anchored mapping.

Hard rules (all asserted by tests):
  - Live gate is always reported as ``blocked_human_only``; the worker has no
    codepath that can unblock it.
  - No legacy Redis writes. The worker writes only V2-namespaced data-plane
    entries (``v2:coinank:*``, ``v2:liquidations:*``) into JSON files.
  - No exchange-mutating method invocation (no order/cancel/leverage/margin).
  - Public REST GETs only.
  - Liquidation events are NEVER synthesized; missing upstream sources are
    labelled as ``missing_api_blockers``.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from v2.backend.app.services.coinank_bridge.service import (
    CoinankBridgeService,
    GLOBAL_11_KEY_CONTRACT,
    LEGACY_BINANCE_FORCE_WS_DELEGATION,
    PLAN3_INTERVAL_LIMITS,
    REQUIRED_COINANK_TFS,
    V2_COINANK_PREFIX,
    V2_LIQUIDATIONS_PREFIX,
)


WORKER_ID = "v2_coinank_and_liquidation_bridge"
LIVE_GATE_STATUS = "blocked_human_only"

REPO_ROOT = Path(__file__).resolve().parents[4]
V2_ROOT = REPO_ROOT / "v2"
PUBLIC_RUNTIME_DIR = (
    V2_ROOT
    / "frontend"
    / "public"
    / "operator_runtime"
    / "coinank_market_intelligence"
    / "latest"
)
LOCAL_RUNTIME_DIR = V2_ROOT / "runtime" / WORKER_ID / "latest"
WORKER_STATUS_DIR = (
    REPO_ROOT
    / "claude_worklog"
    / "final_readiness"
    / "emergency_v2_runtime_migration"
    / "latest"
    / "workers"
)
COPIED_BASELINE_MANIFEST = (
    REPO_ROOT
    / "claude_worklog"
    / "final_readiness"
    / "legacy_startup_baseline_v2_migration"
    / "latest"
    / "copied_baseline_manifest.json"
)

PUBLIC_STATUS_FILE = PUBLIC_RUNTIME_DIR / "coinank_market_intelligence_status.json"
LOCAL_STATUS_FILE = LOCAL_RUNTIME_DIR / f"{WORKER_ID}_status.json"
WORKER_STATUS_FILE = (
    WORKER_STATUS_DIR
    / "v2_coinank_and_liquidation_bridge_from_legacy_baseline_status.json"
)
DATA_PLANE_FILE = LOCAL_RUNTIME_DIR / "v2_coinank_and_liquidation_data_plane.json"


# Legacy baseline SHAs taken verbatim from copied_baseline_manifest.json.
# test_ingestor_sha256_matches_copied_baseline_manifest_contract asserts these
# match byte-for-byte.
LEGACY_BASELINE_SHA256: Dict[str, str] = {
    "v2/legacy_preserved/startup_baseline/ingest/live_coinank.py":
        "cd13dab55c0906c379e4116102c05f960908dd28d6b6e883ca76347cd1f144c8",
    "v2/legacy_preserved/startup_baseline/ingest/live_coinank_global_aggregator.py":
        "1f85c4532e4829aa99ddadbd6a5cd2325ef9e5c4012208eb05876c1b0187eeae",
    "v2/legacy_preserved/startup_baseline/ingest/live_binance_liquidations.py":
        "19711590a3d194fd05ae3be85ef7bd6dec397f6394d02f7e91008c44c310131b",
    "v2/legacy_preserved/startup_baseline/ingest/liquidation_bridge.py":
        "5d70e395938228b61162b531310cd751403ddfeebb8920429e73cdcdbe35d48a",
    "v2/legacy_preserved/startup_baseline/ingest/liquidation_levels_engine.py":
        "fed3c90b5193c27d24dc183089730bda49ff69a1758b597e23a154397f839df7",
}


# Default symbol universe for the test fixture / loop runs. Kept small to
# avoid any dependency on legacy config. Operators override via --symbols.
DEFAULT_SYMBOLS: Tuple[str, ...] = (
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT",
)


def iso_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _try_json(body: str) -> Any:
    if not body:
        return None
    try:
        return json.loads(body)
    except Exception:
        return body


def http_get(url: str) -> Tuple[int, Any]:
    """Stdlib-only public GET fetcher. Used as the default for the service.
    Tests inject their own callable instead.
    """
    request = urllib.request.Request(
        url,
        method="GET",
        headers={"User-Agent": f"ai-bot-v2-{WORKER_ID}-readonly"},
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            body = response.read().decode("utf-8")
            status = int(response.status)
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8")
        except Exception:
            body = ""
        return int(exc.code), _try_json(body)
    except Exception:
        return 599, None
    return status, _try_json(body)


def compute_freshness_seconds(ts_ms: Optional[int]) -> int:
    if not ts_ms:
        return -1
    try:
        now_ms = int(time.time() * 1000)
        return max(0, int((now_ms - int(ts_ms)) / 1000))
    except Exception:
        return -1


def build_status(
    service: CoinankBridgeService,
    *,
    symbols: List[str],
    tf: str,
    run_started_ts: str,
    cycle_id: int,
    duration_ms: int,
) -> Dict[str, Any]:
    """Build the public payload. The required field list is enforced by
    ``test_required_public_payload_fields_present``.
    """
    now_ms = int(time.time() * 1000)
    endpoint_freshness = service.endpoint_freshness_ms
    last_kline_ts = endpoint_freshness.get("global_aggregator")
    funding_freshness = compute_freshness_seconds(endpoint_freshness.get("funding_rate_avg"))
    oi_freshness = compute_freshness_seconds(endpoint_freshness.get("total_oi"))
    long_short_freshness = compute_freshness_seconds(endpoint_freshness.get("long_short_ratio"))
    return {
        "worker_id": WORKER_ID,
        "last_run_ts": run_started_ts,
        "generated_at": run_started_ts,
        "source": "V2_COINANK_AND_LIQUIDATION_BRIDGE",
        "live_gate": LIVE_GATE_STATUS,
        "live_gate_status": LIVE_GATE_STATUS,
        "current_gate_state": LIVE_GATE_STATUS,
        "liquidations_persisted_total": service.liquidations_persisted_total,
        "funding_freshness": funding_freshness,
        "oi_freshness": oi_freshness,
        "long_short_freshness": long_short_freshness,
        "missing_api_blockers": service.missing_api_blockers,
        "legacy_baseline_source_paths": sorted(LEGACY_BASELINE_SHA256.keys()),
        "legacy_baseline_source_sha256_list": [
            {"path": path, "sha256": LEGACY_BASELINE_SHA256[path]}
            for path in sorted(LEGACY_BASELINE_SHA256.keys())
        ],
        "freshness_seconds": compute_freshness_seconds(last_kline_ts) if last_kline_ts else -1,
        "global_11_key_contract": list(GLOBAL_11_KEY_CONTRACT),
        "required_tfs": list(REQUIRED_COINANK_TFS),
        "plan3_interval_limits": dict(PLAN3_INTERVAL_LIMITS),
        "binance_force_ws_owner": LEGACY_BINANCE_FORCE_WS_DELEGATION,
        "cycle_id": cycle_id,
        "duration_ms": duration_ms,
        "endpoint_freshness_ms": dict(endpoint_freshness),
        "symbols": list(symbols),
        "tf": tf,
        "manual_redis_mutation_by_codex": False,
        "destructive_redis_mutation_by_codex": False,
        "exchange_actions_by_codex": False,
        "legacy_execution_code_touched": False,
        "legacy_source_file_hash": LEGACY_BASELINE_SHA256[
            "v2/legacy_preserved/startup_baseline/ingest/live_coinank.py"
        ],
    }


def write_status(status: Dict[str, Any], data_plane: Dict[str, Any]) -> None:
    PUBLIC_RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    LOCAL_RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    WORKER_STATUS_DIR.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(status, indent=2, sort_keys=True, default=str)
    PUBLIC_STATUS_FILE.write_text(payload)
    LOCAL_STATUS_FILE.write_text(payload)
    WORKER_STATUS_FILE.write_text(payload)
    DATA_PLANE_FILE.write_text(
        json.dumps(data_plane, indent=2, sort_keys=True, default=str)
    )


def _fetch_coinank_liquidation_orders(
    fetcher,
    *,
    days_back: int,
    record_blocker,
) -> List[Dict[str, Any]]:
    """Attempt a public CoinAnk Plan-3 liquidation_orders fetch. If the
    endpoint is not reachable without credentials (the typical case in V2
    REST-without-API-key mode), we label a missing_api_blocker and return
    an empty list. We NEVER synthesize events.
    """
    url = "https://open-api.coinank.com/api/liquidation/orders"
    try:
        status, body = fetcher(url)
    except Exception as exc:
        record_blocker(
            "coinank_liquidation_orders_endpoint_unreachable",
            f"fetcher raised: {exc!r}",
        )
        return []
    if not (200 <= int(status) < 300) or not isinstance(body, dict):
        record_blocker(
            "coinank_liquidation_orders_endpoint_unreachable",
            f"http_status={status}",
        )
        return []
    data = body.get("data") or {}
    items = data.get("data") if isinstance(data, dict) else None
    if not isinstance(items, list):
        record_blocker(
            "coinank_endpoint_no_current_key",
            "liquidation_orders response had no data.data list",
        )
        return []
    return items


def run_once(
    args: argparse.Namespace,
    *,
    service: Optional[CoinankBridgeService] = None,
    unified_features_by_symbol: Optional[Dict[str, Dict[str, Any]]] = None,
    binance_force_events: Optional[List[Dict[str, Any]]] = None,
    coinank_order_items: Optional[List[Dict[str, Any]]] = None,
    current_prices: Optional[Dict[str, float]] = None,
    fetcher=None,
) -> Dict[str, Any]:
    """Single bridge cycle.

    Parameters other than ``args`` are dependency-injected by tests. In
    production (when ``--once`` runs on a host), they default to:

      - ``unified_features_by_symbol``: empty (no Redis client). The CLI
        therefore reports zero-aggregate global values and labels
        ``v2_liquidation_event_source_empty`` if no events were provided.
      - ``binance_force_events``: empty. Labelled
        ``binance_force_order_ws_owner_unbound``.
      - ``coinank_order_items``: fetched via public REST when
        ``--enable-coinank-rest`` is passed; otherwise empty.

    The worker never synthesizes events.
    """
    run_started_ts = iso_now()
    t0 = time.time()
    if service is None:
        service = CoinankBridgeService(clock=time.time)
    if fetcher is None:
        fetcher = http_get

    # 1. Global aggregator over unified features (in-memory only).
    feats = unified_features_by_symbol or {}
    if not feats:
        service.record_missing_api_blocker(
            "v2_unified_features_empty",
            "no unified-feature input — V2 worker does not read legacy Redis",
        )
    agg = service.compute_global_11_keys(feats, tf=args.tf)

    # 2. CoinAnk liquidation orders intake.
    coinank_items: List[Dict[str, Any]] = list(coinank_order_items or [])
    if args.enable_coinank_rest and not coinank_items:
        coinank_items = _fetch_coinank_liquidation_orders(
            fetcher,
            days_back=args.coinank_history_days,
            record_blocker=service.record_missing_api_blocker,
        )
    if coinank_items:
        service.bridge_coinank_orders_into_v2_events(coinank_items)
    else:
        service.record_missing_api_blocker(
            "v2_liquidation_event_source_empty",
            "no coinank liquidation_orders source available this cycle",
        )

    # 3. Binance force-order intake (WS owner is a separate worker).
    binance_events: List[Dict[str, Any]] = list(binance_force_events or [])
    if binance_events:
        service.bridge_binance_force_into_v2_events(binance_events)
    else:
        service.record_missing_api_blocker(
            "binance_force_order_ws_owner_unbound",
            "no binance force_order events provided; WS owner=separate_v2_ws_worker",
        )

    # 4. Window aggregations.
    for window in service.AGG_WINDOWS_SECONDS:
        service.aggregate_force_window(window)

    # 5. Per-(symbol, tf) levels.
    prices = current_prices or {}
    symbol_set = [s.upper() for s in (args.symbols or list(DEFAULT_SYMBOLS))]
    for symbol in symbol_set:
        for tf in service.BUCKET_WIDTH_PCT.keys():
            service.compute_liquidation_levels_mapping(
                symbol, tf, current_price=float(prices.get(symbol, 0.0))
            )

    # 6. Endpoint manifest + cycle runtime (V2-namespaced mirrors only).
    service.endpoint_manifest_snapshot(
        endpoints=list(GLOBAL_11_KEY_CONTRACT),
        version="3.0.0",
    )
    duration_ms = int((time.time() - t0) * 1000)
    service.cycle_complete_snapshot(
        cycle_id=int(args.cycle_id_seed),
        duration_ms=duration_ms,
        endpoints_active=len(GLOBAL_11_KEY_CONTRACT),
    )

    status = build_status(
        service,
        symbols=symbol_set,
        tf=args.tf,
        run_started_ts=run_started_ts,
        cycle_id=int(args.cycle_id_seed),
        duration_ms=duration_ms,
    )
    status["global_aggregate_result"] = agg.to_dict()
    if not args.no_write:
        write_status(status, service.data_plane)
    return status


def verify_baseline_shas(manifest_path: Path = COPIED_BASELINE_MANIFEST) -> Dict[str, Any]:
    """Read the copied_baseline_manifest.json and verify each baseline file
    we depend on has a SHA matching ``LEGACY_BASELINE_SHA256``.
    """
    result: Dict[str, Any] = {"checked": [], "mismatches": [], "ok": True}
    try:
        manifest = json.loads(manifest_path.read_text())
    except Exception as exc:
        return {"checked": [], "mismatches": [], "ok": False, "error": f"manifest_load_failed: {exc}"}
    by_path: Dict[str, str] = {}
    for record in manifest.get("records", []):
        v2_path = record.get("v2_preserved_path")
        sha = record.get("sha256")
        if v2_path and sha:
            by_path[v2_path] = sha
    for v2_path, expected in LEGACY_BASELINE_SHA256.items():
        actual = by_path.get(v2_path)
        result["checked"].append({"path": v2_path, "expected": expected, "actual": actual})
        if actual != expected:
            result["mismatches"].append({"path": v2_path, "expected": expected, "actual": actual})
            result["ok"] = False
    return result


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog=WORKER_ID)
    parser.add_argument("--symbols", nargs="*", default=list(DEFAULT_SYMBOLS))
    parser.add_argument("--tf", default="15m")
    parser.add_argument("--interval", type=int, default=5)
    parser.add_argument("--cycle-id-seed", type=int, default=1)
    parser.add_argument("--coinank-history-days", type=int, default=30)
    parser.add_argument("--enable-coinank-rest", action="store_true")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--verify-baseline-shas", action="store_true")
    args = parser.parse_args(argv)
    if not args.loop and not args.once:
        args.once = True
    return args


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    if args.verify_baseline_shas:
        report = verify_baseline_shas()
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if report["ok"] else 2
    if args.once:
        run_once(args)
        return 0
    while True:
        try:
            run_once(args)
        except KeyboardInterrupt:
            return 0
        except Exception:
            pass
        time.sleep(max(1, int(args.interval)))


if __name__ == "__main__":
    sys.exit(main())
