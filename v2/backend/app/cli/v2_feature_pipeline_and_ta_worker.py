"""V2 feature-pipeline + TA worker — standalone CLI worker.

Ports the responsibilities of the legacy startup-baseline files
(`feature_pipeline.py`, `ohlcv_resampler_hotfix.py`,
`ingest/live_technical_analysis.py`, `scripts/validate_symbol_universe_data.py`,
`scripts/paralysis_detectors.py`) into a single V2-only worker. See the
LEGACY_BASELINE_ANALYSIS sibling document for SHA-anchored mappings.

Hard rules (asserted by tests):
  - Live gate is permanently ``blocked_human_only``; no codepath unblocks it.
  - No legacy Redis writes. The worker writes only V2-namespaced data-plane
    entries under ``v2:features:*`` to a JSON file under
    ``v2/runtime/v2_feature_pipeline_and_ta_worker/latest/``.
  - No exchange mutating method invocation.
  - Binance public websocket cache is the default live input path. REST can
    appear only inside the unified fallback client when explicitly enabled.
  - Paralysis-detector alerts route into the V2 worker public payload, NOT
    the legacy Redis stream.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from v2.backend.app.services.feature_pipeline_and_ta.service import (
    FAST_LANE_INTERVAL_SEC,
    FAST_TIMEFRAMES,
    FeaturePipelineAndTAService,
    LEGACY_FEATURE_FAMILIES_DEFERRED_WITH_REASON,
    LEGACY_FEATURE_FAMILIES_PRESERVED,
    LEGACY_TA_INDICATOR_FAMILIES_PRESERVED,
    LEGACY_TA_INDICATOR_FAMILIES_DEFERRED_WITH_REASON,
    LEGACY_TA_LIBRARY,
    OHLCV_RESAMPLER_INTERVAL_SEC,
    OHLCV_RESAMPLER_TF_EXPIRY_SEC,
    PARALYSIS_DETECTOR_DEFAULT_MINUTES,
    SLOW_LANE_INTERVAL_SEC,
    SLOW_TIMEFRAMES,
    STARTUP_VALIDATE_RETRIES,
    STARTUP_VALIDATE_SLEEP_SEC,
    TA_UPDATE_INTERVAL_SEC,
    V2_KEY_PREFIX,
    VALIDATE_FAST_TF_MAX_AGE_SEC,
    VALIDATE_MIN_CANDLES,
    VALIDATE_ORDERBOOK_STALE_SEC,
    VALIDATE_SLOW_TF_MAX_AGE_SEC,
)
from v2.backend.app.services.binance_unified_websocket_transport import (
    fetch_unified_market_snapshot,
)
from v2.backend.app.services.symbol_universe.service import (
    DYNAMIC_SYMBOL_SOURCES,
    LEGACY_ACTIVE_SYMBOLS_25,
    SYMBOL_SELECTION_SCORE_FACTORS,
    SymbolUniverseService,
)
from v2.backend.app.services.v2_symbol_runtime_universe import resolve_symbols


WORKER_ID = "v2_feature_pipeline_and_ta_worker"
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
    WORKER_STATUS_DIR
    / f"{WORKER_ID}_from_legacy_baseline_status.json"
)
DATA_PLANE_FILE = LOCAL_RUNTIME_DIR / "v2_feature_pipeline_and_ta_data_plane.json"
SYMBOL_UNIVERSE_CONTRACT = "SYMBOL_UNIVERSE_CONTRACT_REQUIRED"
SYMBOL_UNIVERSE_SERVICE_PATH = "v2/backend/app/services/symbol_universe/service.py"
SYMBOL_UNIVERSE_PUBLIC_PAYLOAD_CANDIDATES = [
    V2_ROOT / "frontend" / "public" / "operator_runtime" / "symbol_universe" / "latest" / "symbol_universe_status.json",
    V2_ROOT / "frontend" / "public" / "symbol_universe" / "latest" / "symbol_universe_status.json",
]


# Five legacy baseline files this worker is anchored to. SHAs are taken
# verbatim from copied_baseline_manifest.json. The
# test_baseline_sha256_matches_copied_baseline_manifest_contract test
# asserts these match the manifest byte-for-byte.
LEGACY_BASELINE_SHA256: Dict[str, str] = {
    "v2/legacy_preserved/startup_baseline/feature_pipeline.py":
        "143938e735342179105155a12c50d7c495bdd1c16d570586cb369d03d7d4b2e8",
    "v2/legacy_preserved/startup_baseline/ohlcv_resampler_hotfix.py":
        "b83edf60a7d0db51556752cdcf9d713ee9d7175d05b26a6ce6c2235d214f4239",
    "v2/legacy_preserved/startup_baseline/ingest/live_technical_analysis.py":
        "5cdd4ea1d43271d0199e1ca92ecad3a8b76308838898a611df6ef4602f7388ac",
    "v2/legacy_preserved/startup_baseline/scripts/validate_symbol_universe_data.py":
        "151720d7e9b1c3f9608df6404e20a912da4572dc66078d7cef001bc4ddd5ec07",
    "v2/legacy_preserved/startup_baseline/scripts/paralysis_detectors.py":
        "8fd4c4f55ac43e5af07c84cddea04328f7b4e5811a5230442f276caf33fc7c27",
}


def iso_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch_live_snapshot(symbol: str, timeframe: str) -> Dict[str, Any]:
    """Build a minimal per-symbol/tf snapshot from the unified Binance feed.

    Read-only. No credentials. The unified client reads the Binance public
    websocket cache first and only falls back to REST when the fallback flag is
    explicitly enabled.
    """
    unified = fetch_unified_market_snapshot(symbol, timeframe=timeframe, limit=200)
    candles = [
        {
            "ts_ms": int(row.get("open_time_ms") or row.get("event_time_ms") or 0),
            "open": float(row.get("open") or 0.0),
            "high": float(row.get("high") or 0.0),
            "low": float(row.get("low") or 0.0),
            "close": float(row.get("close") or 0.0),
            "volume": float(row.get("volume") or 0.0),
        }
        for row in unified.candles
        if isinstance(row, dict)
    ]
    last = candles[-1] if candles else {}
    snapshot = {
        "symbols": [symbol],
        "timeframes": [timeframe],
        "per_symbol": {
            symbol: {
                "orderbook_top": {
                    "bid": None,
                    "ask": None,
                    "ts_ms": int(time.time() * 1000),
                    "missing_reason": "ORDERBOOK_TOP_NOT_IN_UNIFIED_KLINE_SNAPSHOT",
                },
                "timeframes": {
                    timeframe: {
                        "market": {
                            "open": last.get("open", 0.0),
                            "high": last.get("high", 0.0),
                            "low": last.get("low", 0.0),
                            "close": last.get("close", 0.0),
                            "volume": last.get("volume", 0.0),
                            "timestamp": last.get("ts_ms", int(time.time() * 1000)),
                        },
                        "ohlcv_list": candles,
                        "unified": {
                            "ts_ms": int(time.time() * 1000),
                            "source": unified.source,
                            "source_pointer": unified.source_pointer,
                            "wss_cache_used": unified.wss_cache_used,
                            "rest_backup_used": unified.rest_backup_used,
                            "rest_backup_reason": unified.rest_backup_reason,
                            "freshness_state": unified.freshness_state,
                        },
                    }
                },
            }
        },
        "snapshot_source": unified.source,
        "snapshot_source_pointer": unified.source_pointer,
        "websocket_primary": True,
        "rest_backup_used": unified.rest_backup_used,
        "rest_backup_reason": unified.rest_backup_reason,
    }
    return snapshot


def load_input(args: argparse.Namespace) -> Tuple[Dict[str, Any], str]:
    if args.input_file:
        path = Path(args.input_file)
        payload = json.loads(path.read_text())
        return payload, str(payload.get("snapshot_source") or path)
    snapshot = fetch_live_snapshot(args.symbol, args.timeframe)
    return snapshot, str(
        snapshot.get("snapshot_source")
        or f"binance_unified_websocket_cache:{args.symbol}:{args.timeframe}"
    )


def _as_symbol_list(value: Any) -> List[str]:
    if not value:
        return []
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, list):
        values = value
    else:
        return []
    out: List[str] = []
    for raw in values:
        if isinstance(raw, dict):
            raw = raw.get("canonical_symbol_id") or raw.get("symbol") or raw.get("legacy_symbol")
        text = str(raw or "").strip().upper()
        if text:
            out.append(text)
    return sorted(set(out))


def _load_symbol_universe_public_payload() -> Tuple[Dict[str, Any], Optional[str]]:
    for candidate in SYMBOL_UNIVERSE_PUBLIC_PAYLOAD_CANDIDATES:
        if candidate.exists():
            try:
                return json.loads(candidate.read_text()), str(candidate.relative_to(REPO_ROOT))
            except Exception:
                return {}, str(candidate.relative_to(REPO_ROOT))
    return {}, None


def build_symbol_scope(snapshot: Dict[str, Any], observed_symbols: List[str]) -> Dict[str, Any]:
    public_payload, public_path = _load_symbol_universe_public_payload()
    source_payload = public_payload if public_payload else snapshot
    observed = _as_symbol_list(observed_symbols)
    legacy_seed = _as_symbol_list(
        source_payload.get("legacy_active_symbols")
        or snapshot.get("legacy_active_symbols")
        or LEGACY_ACTIVE_SYMBOLS_25
    )
    universe_service = SymbolUniverseService(legacy_active_symbols=legacy_seed)

    discovered = _as_symbol_list(
        source_payload.get("discovered_symbols")
        or source_payload.get("symbols_discovered")
        or source_payload.get("all_discovered_symbols")
    )
    if not discovered:
        discovered = sorted(
            {
                identity.canonical_symbol_id.upper()
                for identity in universe_service.all_discovered_symbols()
                if getattr(identity, "canonical_symbol_id", None)
            }
        )
    dynamic_discovered = _as_symbol_list(
        source_payload.get("dynamic_discovered_symbols")
        or source_payload.get("dynamic_symbols")
        or discovered
    )
    if not discovered and dynamic_discovered:
        discovered = list(dynamic_discovered)

    training_symbols = _as_symbol_list(source_payload.get("training_symbols"))
    paper_symbols = _as_symbol_list(source_payload.get("paper_symbols"))
    binance_confirmed = _as_symbol_list(
        source_payload.get("binance_usdm_confirmed_symbols")
        or source_payload.get("binance_usdm_tradable_symbols")
    )
    live_blocked = _as_symbol_list(source_payload.get("live_blocked_symbols"))
    if not live_blocked:
        live_blocked = sorted(
            set(dynamic_discovered or discovered or observed or universe_service.legacy_active_symbols())
        )

    return {
        "symbol_universe_contract": SYMBOL_UNIVERSE_CONTRACT,
        "symbol_universe_source_path": SYMBOL_UNIVERSE_SERVICE_PATH,
        "symbol_universe_public_payload_path": public_path,
        "symbol_universe_public_payload_status": (
            "PRESENT" if public_path else "MISSING_SYMBOL_UNIVERSE_PUBLIC_PAYLOAD"
        ),
        "legacy_active_symbols": universe_service.legacy_active_symbols(),
        "legacy_active_symbol_source": "legacy_config.py_SYMBOLS_current_25",
        "discovered_symbols": discovered,
        "dynamic_discovered_symbols": dynamic_discovered,
        "dynamic_symbol_sources": list(DYNAMIC_SYMBOL_SOURCES),
        "observed_symbols": observed,
        "training_symbols": training_symbols,
        "paper_symbols": paper_symbols,
        "live_symbols": [],
        "live_blocked_symbols": live_blocked,
        "binance_usdm_confirmed_symbols": binance_confirmed,
        "coinank_symbols_tradability": "market_intelligence_only_until_binance_usdm_confirmed",
        "symbol_scope_policy": "do_not_train_or_trade_all_discovered_symbols_automatically",
        "passive_monitor_all_discovered_symbols": True,
        "train_all_discovered_symbols": False,
        "trade_all_discovered_symbols": False,
        "live_symbol_policy": "none_live_blocked_human_only",
        "symbol_selection_score_factors": list(SYMBOL_SELECTION_SCORE_FACTORS),
    }


def _snapshot_now_ms(snapshot: Dict[str, Any], fallback_ms: int) -> int:
    candidates: List[int] = []

    def add(raw: Any) -> None:
        try:
            value = int(float(raw))
        except (TypeError, ValueError):
            return
        if value > 0:
            candidates.append(value)

    for key in ("generated_at_ms", "as_of_ms", "now_ms", "ts_ms", "timestamp"):
        add(snapshot.get(key))
    for ev in snapshot.get("paralysis_events") or []:
        if isinstance(ev, dict):
            add(ev.get("ts_ms") or ev.get("timestamp"))
    for sym_snap in (snapshot.get("per_symbol") or {}).values():
        if not isinstance(sym_snap, dict):
            continue
        for container in (sym_snap.get("orderbook_top") or {}, sym_snap.get("mark") or {}):
            if isinstance(container, dict):
                add(container.get("ts_ms") or container.get("timestamp") or container.get("ts"))
        for tf_snap in (sym_snap.get("timeframes") or {}).values():
            if not isinstance(tf_snap, dict):
                continue
            for container in (tf_snap.get("market") or {}, tf_snap.get("unified") or {}):
                if isinstance(container, dict):
                    add(container.get("ts_ms") or container.get("timestamp") or container.get("ts"))
            candles = tf_snap.get("ohlcv_list") or []
            if candles and isinstance(candles[-1], dict):
                add(candles[-1].get("ts_ms") or candles[-1].get("timestamp") or candles[-1].get("ts"))
    return max(candidates) if candidates else fallback_ms


def build_status(
    *,
    service: FeaturePipelineAndTAService,
    snapshot_source: str,
    run_started_ts: str,
    unified_keys: List[str],
    ta_keys: List[str],
    resample_keys: List[str],
    validation: Dict[str, Any],
    paralysis: Dict[str, Any],
    symbols: List[str],
    timeframes: List[str],
    last_kline_ts: Optional[int],
    symbol_scope: Dict[str, Any],
) -> Dict[str, Any]:
    freshness = _freshness_seconds(last_kline_ts)
    return {
        "worker_id": WORKER_ID,
        "last_run_ts": run_started_ts,
        "snapshot_source": snapshot_source,
        "symbols": symbols,
        **symbol_scope,
        "timeframes": timeframes,
        "fast_timeframes": list(FAST_TIMEFRAMES),
        "slow_timeframes": list(SLOW_TIMEFRAMES),
        "fast_lane_interval_sec": FAST_LANE_INTERVAL_SEC,
        "slow_lane_interval_sec": SLOW_LANE_INTERVAL_SEC,
        "ohlcv_resampler_interval_sec": OHLCV_RESAMPLER_INTERVAL_SEC,
        "ohlcv_resampler_tf_expiry_seconds": dict(OHLCV_RESAMPLER_TF_EXPIRY_SEC),
        "ta_update_interval_sec": TA_UPDATE_INTERVAL_SEC,
        "ta_library_legacy": LEGACY_TA_LIBRARY,
        "ta_indicator_families_preserved": list(LEGACY_TA_INDICATOR_FAMILIES_PRESERVED),
        "ta_indicator_families_deferred_with_reason": dict(
            LEGACY_TA_INDICATOR_FAMILIES_DEFERRED_WITH_REASON
        ),
        "legacy_feature_families_preserved": list(LEGACY_FEATURE_FAMILIES_PRESERVED),
        "legacy_feature_families_deferred_with_reason": dict(
            LEGACY_FEATURE_FAMILIES_DEFERRED_WITH_REASON
        ),
        "universe_validation": {
            "orderbook_stale_sec": VALIDATE_ORDERBOOK_STALE_SEC,
            "fast_tf_max_age_sec": VALIDATE_FAST_TF_MAX_AGE_SEC,
            "slow_tf_max_age_sec": VALIDATE_SLOW_TF_MAX_AGE_SEC,
            "min_candles": VALIDATE_MIN_CANDLES,
            "startup_validate_retries": STARTUP_VALIDATE_RETRIES,
            "startup_validate_sleep_sec": STARTUP_VALIDATE_SLEEP_SEC,
            "result": validation,
        },
        "paralysis_detector": {
            "default_window_minutes": PARALYSIS_DETECTOR_DEFAULT_MINUTES,
            "result": paralysis,
        },
        "v2_keys_written": {
            "unified_features": unified_keys,
            "ta": ta_keys,
            "ohlcv_resampled": resample_keys,
        },
        "v2_key_prefix": V2_KEY_PREFIX,
        "legacy_baseline_source_paths": sorted(LEGACY_BASELINE_SHA256.keys()),
        "legacy_baseline_source_sha256_list": [
            {"path": path, "sha256": LEGACY_BASELINE_SHA256[path]}
            for path in sorted(LEGACY_BASELINE_SHA256.keys())
        ],
        "live_gate": LIVE_GATE_STATUS,
        "current_gate_state": LIVE_GATE_STATUS,
        "freshness_seconds": freshness,
        "last_kline_ts": last_kline_ts,
    }


def _freshness_seconds(ts_ms: Optional[int]) -> int:
    if not ts_ms:
        return -1
    try:
        now_ms = int(time.time() * 1000)
        return max(0, int((now_ms - int(ts_ms)) / 1000))
    except Exception:
        return -1


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


def run_once(
    args: argparse.Namespace,
    *,
    service: Optional[FeaturePipelineAndTAService] = None,
) -> Dict[str, Any]:
    run_started_ts = iso_now()
    if service is None:
        service = FeaturePipelineAndTAService()
    snapshot, snapshot_source = load_input(args)
    now_ms = _snapshot_now_ms(snapshot, int(time.time() * 1000))

    symbols = list(snapshot.get("symbols") or [args.symbol])
    symbol_scope = build_symbol_scope(snapshot, symbols)
    symbols = list(symbol_scope.get("observed_symbols") or symbols)
    timeframes = list(snapshot.get("timeframes") or [args.timeframe])
    per_symbol: Dict[str, Any] = snapshot.get("per_symbol") or {}

    unified_keys: List[str] = []
    ta_keys: List[str] = []
    resample_keys: List[str] = []
    last_kline_ts: Optional[int] = None

    for sym in symbols:
        sym_snap = per_symbol.get(sym) or {}
        for tf in timeframes:
            tf_snap = (sym_snap.get("timeframes") or {}).get(tf) or {}
            unified_input = {
                "ohlcv": tf_snap.get("market") or {},
                "orderbook_top": sym_snap.get("orderbook_top") or {},
                "mark": sym_snap.get("mark") or {},
                "ta": tf_snap.get("ta") or {},
            }
            unified = service.compute_unified_features(sym, tf, unified_input, now_ms=now_ms)
            unified_keys.extend(unified.v2_keys_written)

            candles = tf_snap.get("ohlcv_list") or []
            if candles:
                ta = service.compute_ta_indicators(sym, tf, candles, now_ms=now_ms)
                if ta.v2_key:
                    ta_keys.append(ta.v2_key)
                last_ts = candles[-1].get("ts_ms") or candles[-1].get("timestamp")
                if last_ts is not None:
                    try:
                        last_kline_ts = int(last_ts)
                    except (TypeError, ValueError):
                        pass

            market = tf_snap.get("market") or {}
            if market:
                resample = service.resample_ohlcv(sym, tf, market)
                if resample.v2_key:
                    resample_keys.append(resample.v2_key)

    validation = service.validate_universe_coverage(
        snapshot, now_ms=now_ms, symbols=symbols, timeframes=timeframes,
    ).to_dict()
    paralysis_events = snapshot.get("paralysis_events") or []
    normalized_events: List[Tuple[int, Dict[str, Any]]] = []
    for ev in paralysis_events:
        try:
            normalized_events.append((int(ev.get("ts_ms", 0)), dict(ev)))
        except Exception:
            continue
    paralysis = service.detect_paralysis(
        normalized_events,
        window_minutes=args.paralysis_window_minutes,
        now_ms=now_ms,
    ).to_dict()

    status = build_status(
        service=service,
        snapshot_source=snapshot_source,
        run_started_ts=run_started_ts,
        unified_keys=unified_keys,
        ta_keys=ta_keys,
        resample_keys=resample_keys,
        validation=validation,
        paralysis=paralysis,
        symbols=symbols,
        timeframes=timeframes,
        last_kline_ts=last_kline_ts,
        symbol_scope=symbol_scope,
    )
    if not args.no_write:
        write_status(status, service.data_plane)
    return status


def verify_baseline_shas(manifest_path: Path = COPIED_BASELINE_MANIFEST) -> Dict[str, Any]:
    """Verify each baseline file we depend on has a SHA matching
    ``LEGACY_BASELINE_SHA256`` against the copied_baseline_manifest.json.
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
    parser.add_argument("--symbol", default=None)
    parser.add_argument("--timeframe", default="1m")
    parser.add_argument("--interval", type=int, default=FAST_LANE_INTERVAL_SEC)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--input-file", default=None,
                        help="Read snapshot input (per-symbol/tf dict) from a JSON file.")
    parser.add_argument(
        "--paralysis-window-minutes",
        type=float,
        default=PARALYSIS_DETECTOR_DEFAULT_MINUTES,
    )
    parser.add_argument("--verify-baseline-shas", action="store_true")
    args = parser.parse_args(argv)
    args.symbol = (args.symbol or resolve_symbols(smoke_test=args.smoke_test)[0]).strip().upper()
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
        validation_passed = bool(status["universe_validation"]["result"].get("passed"))
        return 0 if validation_passed else 2
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
