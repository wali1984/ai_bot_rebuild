"""V2 market ingestor — standalone CLI worker.

Ports the legacy market-ingestor responsibility from the startup-baseline
files (`live_binance.py`, `live_kucoin.py`, `live_coinapi_v1.py`,
`live_coinapi_wsds.py`, `realtime_price_provider.py`) into a single,
V2-only worker. See the BASELINE_ANALYSIS doc for the SHA-anchored mapping.

Hard rules (all asserted by tests):
  - Live gate is always reported as ``blocked_human_only``; the worker has no
    codepath that can unblock it.
  - No legacy Redis writes. The worker writes only V2-namespaced data-plane
    entries to a JSON file under ``v2/runtime/v2_market_ingestor/latest/``.
  - No exchange mutating method invocation (no order/cancel/leverage/margin).
  - Public REST GETs only.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from v2.backend.app.services.market_ingest.service import (
    DATA_SOURCE_PRIORITY,
    MarketIngestService,
    PriceSourcePriority,
    V2_KEY_PREFIX,
)


WORKER_ID = "v2_market_ingestor"
LIVE_GATE_STATUS = "blocked_human_only"

REPO_ROOT = Path(__file__).resolve().parents[4]
V2_ROOT = REPO_ROOT / "v2"
PUBLIC_RUNTIME_DIR = (
    V2_ROOT / "frontend" / "public" / "operator_runtime" / WORKER_ID / "latest"
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

PUBLIC_STATUS_FILE = PUBLIC_RUNTIME_DIR / f"{WORKER_ID}_status.json"
LOCAL_STATUS_FILE = LOCAL_RUNTIME_DIR / f"{WORKER_ID}_status.json"
WORKER_STATUS_FILE = (
    WORKER_STATUS_DIR / "v2_market_ingestor_from_legacy_baseline_status.json"
)
DATA_PLANE_FILE = LOCAL_RUNTIME_DIR / "v2_market_data_plane.json"


# Legacy baseline files this worker is anchored to, with SHAs taken from
# copied_baseline_manifest.json. The
# test_ingestor_sha256_matches_copied_baseline_manifest_contract test asserts
# these match the manifest byte-for-byte.
LEGACY_BASELINE_SHA256: Dict[str, str] = {
    "v2/legacy_preserved/startup_baseline/ingest/live_binance.py":
        "6c1eb771a3842e2d94b797eedd55aa624075c51c6d50aec701397f81dbace798",
    "v2/legacy_preserved/startup_baseline/ingest/live_kucoin.py":
        "73b852db1bf69062d4028091cf17c126f5cb666e94bf784cdb2bb9b47328a976",
    "v2/legacy_preserved/startup_baseline/ingest/live_coinapi_v1.py":
        "c8ca17d21b972510b92c4e84c477cd3440b3cfd1e2ec8e7411624a7454cee280",
    "v2/legacy_preserved/startup_baseline/ingest/live_coinapi_wsds.py":
        "a6973d887d1c52a4bb48f3b6f222b04e97d92e500ab889e94d6026cf504471b6",
    "v2/legacy_preserved/startup_baseline/ingest/realtime_price_provider.py":
        "dfdc2568368c134b9afcc4fa0faff312cc93a6ecc501ecaac747e7c20d7344ba",
}


def iso_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def http_get(url: str) -> Tuple[int, Any]:
    """Stdlib-only public GET fetcher. Used as the default http_get for the
    service. Tests inject their own callable instead.
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


def _try_json(body: str) -> Any:
    if not body:
        return None
    try:
        return json.loads(body)
    except Exception:
        return body


def compute_freshness_seconds(ts_ms: Optional[int]) -> int:
    if not ts_ms:
        return -1
    try:
        now_ms = int(time.time() * 1000)
        return max(0, int((now_ms - int(ts_ms)) / 1000))
    except Exception:
        return -1


def build_status(
    service: MarketIngestService,
    result: Any,
    run_started_ts: str,
) -> Dict[str, Any]:
    health = service.health_snapshot().to_dict()
    last_ts = service.last_kline_ts
    return {
        "worker_id": WORKER_ID,
        "last_run_ts": run_started_ts,
        "last_kline_ts": last_ts,
        "klines_persisted_total": service.klines_persisted_total,
        "rate_limit_state": service.rate_limit_state,
        "legacy_baseline_source_paths": sorted(LEGACY_BASELINE_SHA256.keys()),
        "legacy_baseline_source_sha256_list": [
            {"path": path, "sha256": LEGACY_BASELINE_SHA256[path]}
            for path in sorted(LEGACY_BASELINE_SHA256.keys())
        ],
        "live_gate": LIVE_GATE_STATUS,
        "current_gate_state": LIVE_GATE_STATUS,
        "freshness_seconds": compute_freshness_seconds(last_ts),
        "data_source_priority": {k: list(v) for k, v in DATA_SOURCE_PRIORITY.items()},
        "price_source_priority_preserved": [
            {"label": p.label, "priority": p.priority} for p in PriceSourcePriority
        ],
        "result": result if isinstance(result, dict) else getattr(result, "to_dict", lambda: {})(),
        "health": health,
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


def run_once(args: argparse.Namespace, *, service: Optional[MarketIngestService] = None) -> Dict[str, Any]:
    run_started_ts = iso_now()
    if service is None:
        service = MarketIngestService(
            http_get=http_get,
            enable_kucoin=args.enable_kucoin,
            coinapi_daily_budget=args.coinapi_daily_budget,
            coinapi_v1_budget_pct=args.coinapi_v1_budget_pct,
        )
    klines_result = service.ingest_klines(args.symbol, args.timeframe, args.limit)
    market_data_results: Dict[str, Any] = {
        "klines": klines_result.to_dict(),
        "bbo": service.ingest_bbo(args.symbol),
        "mark_premium_funding": service.ingest_mark_premium_funding(args.symbol),
        "open_interest": service.ingest_oi(args.symbol),
        "depth": service.ingest_depth(args.symbol, args.depth_limit),
    }
    if args.enable_kucoin:
        # Recognize the optional KuCoin path (legacy default-off).
        market_data_results["kucoin_quote"] = service.ingest_kucoin_quote(args.symbol)
    status = build_status(service, market_data_results, run_started_ts)
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
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--timeframe", default="1m")
    parser.add_argument("--limit", type=int, default=6)
    parser.add_argument("--interval", type=int, default=15)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--enable-kucoin", action="store_true")
    parser.add_argument("--depth-limit", type=int, default=20)
    parser.add_argument("--coinapi-daily-budget", type=int, default=10000)
    parser.add_argument("--coinapi-v1-budget-pct", type=float, default=0.30)
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
        status = run_once(args)
        return 0 if status["klines_persisted_total"] > 0 else 2
    while True:
        try:
            run_once(args)
        except KeyboardInterrupt:
            return 0
        except Exception:
            pass
        time.sleep(max(1, args.interval))


if __name__ == "__main__":
    sys.exit(main())
