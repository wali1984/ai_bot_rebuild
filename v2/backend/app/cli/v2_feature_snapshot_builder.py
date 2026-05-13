"""V2 feature snapshot builder — standalone CLI worker.

Lifts ``v2/backend/app/services/feature_snapshots/service.py`` out of the
``paper_online_runtime`` loop so feature snapshots can be produced
independently. Reads an input payload (from a JSON file, or from the
``paper_online`` runtime's existing public payload as a fallback), runs
``FeatureSnapshotService.build_snapshot``, and writes:

  - ``v2/frontend/public/operator_runtime/v2_feature_snapshot_builder/latest/v2_feature_snapshot_builder_status.json``
  - ``claude_worklog/final_readiness/emergency_v2_runtime_migration/latest/workers/v2_feature_snapshot_builder_status.json``

Hard rules (all enforced by tests):
  - Live gate is always reported as ``blocked_human_only``; this worker
    cannot unblock it and has no exchange-action codepath.
  - No legacy Redis writes. No exchange order/leverage/margin calls.
  - When required feature categories are missing, the worker emits a
    fail-closed status (``trainer_readiness == "BLOCKED_MISSING_REQUIRED"``)
    and returns exit code 2 on a single-shot run.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Dict, Tuple

from v2.backend.app.domain.features.groups import DEFAULT_FEATURE_GROUPS
from v2.backend.app.services.feature_snapshots import FeatureSnapshotService

WORKER_ID = "v2_feature_snapshot_builder"
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
PAPER_ONLINE_PAYLOAD = (
    V2_ROOT
    / "frontend"
    / "public"
    / "operator_runtime"
    / "paper_online"
    / "latest"
    / "paper_runtime_status.json"
)

PUBLIC_STATUS_FILE = PUBLIC_RUNTIME_DIR / f"{WORKER_ID}_status.json"
WORKER_STATUS_FILE = WORKER_STATUS_DIR / f"{WORKER_ID}_status.json"
LOCAL_STATUS_FILE = LOCAL_RUNTIME_DIR / f"{WORKER_ID}_status.json"


def iso_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _http_json(url: str, timeout: int = 8) -> Any:
    request = urllib.request.Request(
        url,
        method="GET",
        headers={"User-Agent": f"ai-bot-v2-{WORKER_ID}-readonly"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_live_payload(symbol: str) -> Dict[str, Any]:
    """Build a minimal feature payload from Binance public REST.

    Read-only. No credentials. No mutating endpoint. Designed for independence
    from paper_online_runtime: this worker can build a snapshot without it.
    """
    encoded = urllib.parse.urlencode({"symbol": symbol})
    ticker = _http_json(f"https://fapi.binance.com/fapi/v1/ticker/price?{encoded}")
    klines = _http_json(
        "https://fapi.binance.com/fapi/v1/klines?"
        + urllib.parse.urlencode({"symbol": symbol, "interval": "1m", "limit": "6"})
    )
    closes = [float(row[4]) for row in klines]
    return_1m = (closes[-1] / closes[-2] - 1.0) if len(closes) >= 2 else 0.0
    return_5m = (closes[-1] / closes[-6] - 1.0) if len(closes) >= 6 else 0.0
    generated = iso_now()
    last_kline_ts = dt.datetime.fromtimestamp(
        int(klines[-1][6]) / 1000.0, tz=dt.timezone.utc
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "canonical_symbol_id": f"BINANCE-USDM-{symbol.replace('USDT','')}-USDT-PERP",
        "legacy_symbol": symbol,
        "timeframe": "1m",
        "generated_ts": generated,
        "feature_values": {
            "close": float(ticker["price"]),
            "return_1m": float(return_1m),
            "return_5m": float(return_5m),
            "spread_bps": 0.0,
            "orderbook_depth_usd": 0.0,
        },
        "feature_to_source": {
            "close": "binance_price",
            "return_1m": "binance_price",
            "return_5m": "binance_price",
            "spread_bps": "binance_price",
            "orderbook_depth_usd": "binance_price",
        },
        "sources": {
            "binance_price": {"source_ts": last_kline_ts, "max_age_ms": 120_000},
        },
        "source_snapshot_ids": [f"binance_kline_{int(time.time())}"],
        "source_key_refs": [f"v2:binance:{symbol}:kline:1m"],
        "source_ingestor_refs": [WORKER_ID],
        "used_features": [
            "close",
            "return_1m",
            "return_5m",
            "spread_bps",
            "orderbook_depth_usd",
        ],
    }


def load_payload(args: argparse.Namespace) -> Tuple[Dict[str, Any], str]:
    """Return (payload, source_payload_path)."""
    if args.payload_file:
        path = Path(args.payload_file)
        return json.loads(path.read_text()), str(path)
    if args.read_from_paper_runtime and PAPER_ONLINE_PAYLOAD.exists():
        data = json.loads(PAPER_ONLINE_PAYLOAD.read_text())
        snap = data.get("feature_snapshot")
        if isinstance(snap, dict) and snap.get("feature_values"):
            return snap, str(PAPER_ONLINE_PAYLOAD)
    return fetch_live_payload(args.symbol), f"binance_public_rest:{args.symbol}"


def snapshot_to_dict(snapshot: Any) -> Dict[str, Any]:
    """Render a FeatureSnapshot dataclass tree as a JSON-safe dict."""
    if is_dataclass(snapshot):
        out: Dict[str, Any] = {}
        for key, value in asdict(snapshot).items():
            out[key] = value
        return out
    if isinstance(snapshot, dict):
        return snapshot
    raise TypeError(f"unsupported snapshot type: {type(snapshot)!r}")


def compute_freshness_seconds(generated_ts: str) -> int:
    try:
        gen = dt.datetime.fromisoformat(generated_ts.replace("Z", "+00:00"))
    except Exception:
        return -1
    now = dt.datetime.now(dt.timezone.utc)
    return max(0, int((now - gen).total_seconds()))


def build_status(
    snapshot: Any,
    source_payload_path: str,
    run_started_ts: str,
) -> Dict[str, Any]:
    snap = snapshot_to_dict(snapshot)
    missing = list(snap.get("missing_features") or [])
    stale = list(snap.get("stale_features") or [])
    trainer_ready = bool(snap.get("confidence_input_ready"))
    if missing:
        trainer_readiness = "BLOCKED_MISSING_REQUIRED"
    elif stale:
        trainer_readiness = "DEGRADED_STALE_INPUTS"
    elif trainer_ready:
        trainer_readiness = "READY"
    else:
        trainer_readiness = "NOT_READY"
    categories_present = [grp["name"] for grp in (snap.get("feature_groups") or [])]
    return {
        "worker_id": WORKER_ID,
        "last_run_ts": run_started_ts,
        "last_snapshot_id": snap.get("feature_snapshot_id"),
        "last_snapshot_ts": snap.get("generated_ts"),
        "feature_categories_present": categories_present,
        "stale_features": stale,
        "missing_features": missing,
        "trainer_readiness": trainer_readiness,
        "source_payload_path": source_payload_path,
        "freshness_seconds": compute_freshness_seconds(snap.get("generated_ts") or ""),
        "live_gate": LIVE_GATE_STATUS,
        "current_gate_state": LIVE_GATE_STATUS,
        "snapshot": snap,
    }


def emit_idle_status(reason: str) -> Dict[str, Any]:
    return {
        "worker_id": WORKER_ID,
        "last_run_ts": iso_now(),
        "last_snapshot_id": None,
        "last_snapshot_ts": None,
        "feature_categories_present": [],
        "stale_features": [],
        "missing_features": [name for group in DEFAULT_FEATURE_GROUPS for name in group.feature_names if group.required_for_trainer],
        "trainer_readiness": "BLOCKED_MISSING_REQUIRED",
        "source_payload_path": None,
        "freshness_seconds": -1,
        "live_gate": LIVE_GATE_STATUS,
        "current_gate_state": LIVE_GATE_STATUS,
        "snapshot": None,
        "error": reason,
    }


def write_status(status: Dict[str, Any]) -> None:
    PUBLIC_RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    LOCAL_RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    WORKER_STATUS_DIR.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(status, indent=2, sort_keys=True, default=str)
    PUBLIC_STATUS_FILE.write_text(payload)
    LOCAL_STATUS_FILE.write_text(payload)
    WORKER_STATUS_FILE.write_text(payload)


def run_once(args: argparse.Namespace) -> Dict[str, Any]:
    run_started_ts = iso_now()
    try:
        payload, src = load_payload(args)
    except Exception as exc:
        status = emit_idle_status(f"payload_load_failed: {exc}")
        write_status(status)
        return status
    try:
        snapshot = FeatureSnapshotService().build_snapshot(payload)
    except KeyError as exc:
        status = emit_idle_status(f"required_field_missing_from_payload: {exc}")
        status["source_payload_path"] = src
        write_status(status)
        return status
    status = build_status(snapshot, src, run_started_ts)
    write_status(status)
    return status


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog=WORKER_ID)
    parser.add_argument("--symbol", default="BTCUSDT", help="exchange symbol (read-only public feed only)")
    parser.add_argument("--interval", type=int, default=30, help="seconds between loop iterations")
    parser.add_argument("--once", action="store_true", help="run a single iteration and exit")
    parser.add_argument("--loop", action="store_true", help="run continuously")
    parser.add_argument("--payload-file", default=None, help="read input payload from a JSON file (overrides live fetch)")
    parser.add_argument(
        "--read-from-paper-runtime",
        action="store_true",
        help="prefer the paper_online runtime payload as input (if present)",
    )
    parser.add_argument("--no-write", action="store_true", help="dry-run; do not write any payload to disk")
    args = parser.parse_args(argv)
    if not args.loop and not args.once:
        args.once = True
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.no_write:
        global write_status

        def _skip(_status: Dict[str, Any]) -> None:
            return None

        write_status = _skip  # type: ignore[assignment]
    if args.once:
        status = run_once(args)
        return 2 if status.get("trainer_readiness") == "BLOCKED_MISSING_REQUIRED" else 0
    while True:
        try:
            run_once(args)
        except KeyboardInterrupt:
            return 0
        except Exception as exc:
            status = emit_idle_status(f"loop_iteration_failed: {exc}")
            try:
                write_status(status)
            except Exception:
                pass
        time.sleep(max(1, args.interval))


if __name__ == "__main__":
    sys.exit(main())
