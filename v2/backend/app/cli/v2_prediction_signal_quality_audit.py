"""V2 prediction signal quality audit — CLI runner.

Reads prediction rows from Redis (v2: keys only), runs the quality
auditor, and writes:

  v2/frontend/public/operator_runtime/prediction_quality/latest/
      prediction_signal_quality_status.json

Safety invariants:
  - Only reads v2:* Redis keys.
  - No writes to Redis.
  - No exchange calls.
  - Live trading stays blocked.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

THIS_FILE = Path(__file__).resolve()
REPO_ROOT = THIS_FILE.parents[4]
sys.path.insert(0, str(REPO_ROOT))

from v2.backend.app.services.all_timeframe_prediction_signal_price_target_publisher import (  # noqa: E402
    DEFAULT_STALE_SECONDS,
    REQUIRED_TIMEFRAMES,
    V2KeyValueStore,
    build_prediction_rows,
    extract_symbols,
)
from v2.backend.app.services.prediction_signal_quality_auditor import (  # noqa: E402
    DEFAULT_CONFIDENCE_FLOOR,
    build_quality_status,
)
from v2.backend.app.services.v2_symbol_runtime_universe import (  # noqa: E402
    BASELINE_25_SYMBOLS,
    resolve_symbols_with_provenance,
)

OUTPUT_PATH_REL = (
    "v2/frontend/public/operator_runtime/prediction_quality/latest/"
    "prediction_signal_quality_status.json"
)


def _localhost_store() -> V2KeyValueStore:
    try:
        import redis  # type: ignore

        client = redis.Redis(
            host="127.0.0.1",
            port=6379,
            db=0,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=5,
        )
        client.ping()
        return V2KeyValueStore(client=client)
    except Exception:  # noqa: BLE001
        return V2KeyValueStore(client=None)


def _load_symbols(store: V2KeyValueStore, repo_root: Path) -> list[str]:
    """Resolve symbol universe from filesystem then Redis fallback."""
    universe_path = (
        repo_root
        / "v2/frontend/public/operator_runtime/symbol_universe/latest/symbol_universe_status.json"
    )
    dynamic_path = (
        repo_root
        / "v2/frontend/public/operator_runtime/v2_dynamic_symbol_discovery/latest/"
        "dynamic_symbol_discovery_status.json"
    )
    payloads = []
    for path in (universe_path, dynamic_path):
        try:
            payloads.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass
    symbols = extract_symbols(payloads, fallback=BASELINE_25_SYMBOLS)
    if not symbols:
        symbols = list(BASELINE_25_SYMBOLS)
    return sorted(symbols)


def atomic_write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def run_once(
    *,
    repo_root: Path,
    stale_seconds: int,
    confidence_floor: float,
    write: bool,
) -> dict:
    store = _localhost_store()
    redis_connected = store.audit.connected

    symbols = _load_symbols(store, repo_root)

    prediction_rows: list[dict] = []
    if redis_connected:
        prediction_rows = build_prediction_rows(
            store=store,
            symbols=symbols,
            timeframes=REQUIRED_TIMEFRAMES,
            stale_seconds=stale_seconds,
        )

    quality_status = build_quality_status(
        prediction_rows,
        symbols=symbols,
        timeframes=REQUIRED_TIMEFRAMES,
        stale_seconds=stale_seconds,
        confidence_floor=confidence_floor,
    )
    quality_status["redis_connected"] = redis_connected
    quality_status["symbol_source"] = (
        "v2_symbol_universe_dynamic" if symbols != list(BASELINE_25_SYMBOLS) else "baseline_25_fallback"
    )
    quality_status["_audit_note"] = (
        "Prediction rows are read from Redis (v2:prediction:* keys). "
        "If Redis is unavailable, all rows will be absent and status will be NO_PREDICTION_ROWS. "
        "No exchange calls made. Live trading blocked."
    )

    out_path = repo_root / OUTPUT_PATH_REL
    if write:
        atomic_write_json(out_path, quality_status)

    return {
        "status": quality_status["status"],
        "redis_connected": redis_connected,
        "symbols_covered": len(symbols),
        "prediction_rows_actual": quality_status.get("prediction_grid_count_actual", 0),
        "pit_violation_count": quality_status.get("pit_violation_count", 0),
        "stale_count": quality_status.get("stale_count", 0),
        "paper_candidate_count": quality_status.get("paper_candidate_count", 0),
        "actionable_candidate_count": quality_status.get("actionable_candidate_count", 0),
        "output_path": str(out_path) if write else None,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="v2_prediction_signal_quality_audit",
        description="Audit prediction signal quality for all symbols and timeframes.",
    )
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument("--stale-seconds", type=int, default=DEFAULT_STALE_SECONDS)
    parser.add_argument(
        "--confidence-floor", type=float, default=DEFAULT_CONFIDENCE_FLOOR
    )
    parser.add_argument(
        "--no-write", action="store_true", help="Skip writing output JSON."
    )
    parser.add_argument("--loop", action="store_true", help="Run continuously.")
    parser.add_argument(
        "--interval-seconds", type=int, default=60, help="Loop interval."
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = Path(args.repo_root).resolve()

    def _run() -> None:
        result = run_once(
            repo_root=repo_root,
            stale_seconds=max(1, int(args.stale_seconds)),
            confidence_floor=float(args.confidence_floor),
            write=not bool(args.no_write),
        )
        print(json.dumps(result, indent=2, sort_keys=True), flush=True)

    if args.loop:
        while True:
            _run()
            time.sleep(max(10, int(args.interval_seconds)))
    else:
        _run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
