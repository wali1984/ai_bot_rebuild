#!/usr/bin/env python3
"""S16 Redis resilience integration test (PERMANENT_SYSTEM_RECOVERY Section 11).

Runs against an ISOLATED redis-server instance (never production Redis) and
exercises PRODUCTION code paths:

  T1 connection_loss      — write ok -> server killed -> write raises -> restart -> reconnect write ok
  T2 write_failure        — production V2OnlyJsonIO.set_json_expiring returns False and audits (no silent success)
  T3 duplicate_protection — production kline _publish_closed_window dedups an identical closed candle
  T4 wal_recovery         — AOF enabled; kill -9 mid-life; restart; all committed keys survive
  T5 reconstruction       — production rebuild_outcome_memory_from_closed_trades rebuilds identical
                            derived state after the derived keys are flushed

Persists results to goal_state/PERMANENT_SYSTEM_RECOVERY/s16_redis_resilience_result.json,
which the Phase-10 stress runner reads. Exit 0 = all subtests pass.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import redis  # noqa: E402

from v2.backend.app.cli.v2_binance_kline_wss_loop import _publish_closed_window  # noqa: E402
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.safety import V2OnlyJsonIO  # noqa: E402
from v2.backend.app.services.paper_trade_management.outcome_memory_updater import (  # noqa: E402
    rebuild_outcome_memory_from_closed_trades,
)

PORT = 7391
RESULT_PATH = REPO_ROOT / "goal_state/PERMANENT_SYSTEM_RECOVERY/s16_redis_resilience_result.json"


def start_server(data_dir: Path) -> subprocess.Popen:
    proc = subprocess.Popen(
        ["redis-server", "--port", str(PORT), "--bind", "127.0.0.1",
         "--dir", str(data_dir), "--appendonly", "yes", "--save", "",
         "--daemonize", "no", "--loglevel", "warning"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    for _ in range(50):
        try:
            redis.Redis(port=PORT, socket_connect_timeout=0.5).ping()
            return proc
        except Exception:
            time.sleep(0.2)
    raise RuntimeError("isolated redis-server failed to start")


def sample_candle(_open_ms: int) -> dict:
    """Schema-exact test row: a REAL production candle used UNMODIFIED (the
    store hash-binds rows, so any identity remap fails the source contract).
    Safe because T3 writes it only to the ISOLATED server, never production."""
    prod = redis.Redis(decode_responses=True)  # default port = production, GET only
    raw = prod.get("v2:market:ohlcv_closed:binance:BTCUSDT:5m")
    rows = json.loads(raw)
    return dict((rows.get("candles") if isinstance(rows, dict) else rows)[-1])


def main() -> int:
    results: dict[str, dict] = {}
    data_dir = Path(tempfile.mkdtemp(prefix="s16-redis-"))
    proc = start_server(data_dir)
    try:
        client = redis.Redis(port=PORT, decode_responses=True,
                             socket_timeout=2, socket_connect_timeout=2,
                             retry_on_timeout=False)

        # T1: connection loss surfaces as an exception, reconnect works after restart
        client.set("v2:s16:probe", "1")
        proc.send_signal(signal.SIGKILL)
        proc.wait(timeout=10)
        raised = False
        try:
            client.set("v2:s16:probe", "2")
        except redis.exceptions.RedisError:
            raised = True
        proc = start_server(data_dir)
        reconnected = client.set("v2:s16:probe2", "1") is True
        results["T1_connection_loss"] = {
            "pass": raised and reconnected,
            "write_raised_while_down": raised, "reconnected_after_restart": reconnected,
        }

        # T2: production guarded IO returns False + audits when the server is down
        proc.send_signal(signal.SIGKILL)
        proc.wait(timeout=10)
        io = V2OnlyJsonIO(client=redis.Redis(port=PORT, decode_responses=True,
                                             socket_timeout=1, socket_connect_timeout=1))
        wrote = io.set_json_expiring("v2:prediction_serving:s16_probe", {"x": 1}, ex=60)
        results["T2_write_failure_surfaced"] = {
            "pass": wrote is False and io.audit.writes_failed >= 1 and bool(io.audit.errors),
            "returned": wrote, "writes_failed": io.audit.writes_failed,
            "audit_errors": io.audit.errors[:2],
        }
        proc = start_server(data_dir)

        # T3: production closed-window writer dedups an identical candle
        # (the store demands a binary-responses client)
        bin_client = redis.Redis(port=PORT, decode_responses=False)
        raw_client = redis.Redis(port=PORT, decode_responses=True)
        key = "v2:market:ohlcv_closed:binance:BTCUSDT:5m"  # isolated server only
        row = sample_candle(1_785_000_000_000)
        r1 = _publish_closed_window(bin_client, key=key, row=dict(row), row_limit=100, ttl_seconds=3600)
        r2 = _publish_closed_window(bin_client, key=key, row=dict(row), row_limit=100, ttl_seconds=3600)
        window = json.loads(raw_client.get(key))
        rows = window.get("candles") if isinstance(window, dict) else window
        results["T3_duplicate_protection"] = {
            "pass": len(rows) == 1 and r2.rows_deduplicated_or_trimmed_for_row_limit >= 1,
            "window_rows_after_double_write": len(rows),
            "second_write_dedup_count": r2.rows_deduplicated_or_trimmed_for_row_limit,
        }

        # T4: AOF WAL recovery across kill -9
        for i in range(20):
            raw_client.set(f"v2:s16:wal:{i}", str(i))
        time.sleep(1.2)  # allow AOF everysec fsync
        proc.send_signal(signal.SIGKILL)
        proc.wait(timeout=10)
        proc = start_server(data_dir)
        survived = sum(1 for i in range(20) if raw_client.get(f"v2:s16:wal:{i}") == str(i))
        window_survived = raw_client.exists(key) == 1
        results["T4_wal_recovery"] = {
            "pass": survived == 20 and window_survived,
            "keys_survived": survived, "closed_window_survived": bool(window_survived),
        }

        # T5: production outcome-memory reconstruction is deterministic — REAL
        # production closed trades (read-only source), rebuilt into the ISOLATED
        # server, flushed, rebuilt again; every derived bucket must be identical.
        # (Synthetic rows fail STRICT_PIT_VALID_ROWS_ONLY validation by design.)
        prod = redis.Redis(decode_responses=True)  # production, GET only
        closed_rows = json.loads(prod.get("v2:paper:closed_trades") or "[]")
        first = rebuild_outcome_memory_from_closed_trades(
            closed_trade_rows=closed_rows, redis_client=raw_client, write=True)
        bucket_keys = sorted(first.get("bucket_keys") or [])
        derived = {k: raw_client.get(k) for k in bucket_keys}
        for k in bucket_keys:
            raw_client.delete(k)
        rebuild_outcome_memory_from_closed_trades(
            closed_trade_rows=closed_rows, redis_client=raw_client, write=True)
        derived2 = {k: raw_client.get(k) for k in bucket_keys}

        def _stable(payload: str | None) -> str | None:
            if payload is None:
                return None
            d = json.loads(payload)
            d.pop("generated_at", None)
            return json.dumps(d, sort_keys=True)

        identical = bool(bucket_keys) and all(
            _stable(derived[k]) == _stable(derived2[k]) and derived[k] is not None
            for k in bucket_keys
        )
        results["T5_reconstruction"] = {
            "pass": identical,
            "source_rows": len(closed_rows),
            "buckets_rebuilt": len(bucket_keys),
            "events_processed": first.get("events_processed"),
            "identical_after_flush_and_rebuild": identical,
        }
    finally:
        try:
            proc.send_signal(signal.SIGKILL)
        except Exception:
            pass
        shutil.rmtree(data_dir, ignore_errors=True)

    all_pass = all(v.get("pass") for v in results.values())
    payload = {
        "schema_version": "s16_redis_resilience_v1",
        "run_utc": datetime.now(UTC).isoformat(),
        "isolated_port": PORT,
        "production_bindings": [
            "v2_binance_kline_wss_loop._publish_closed_window",
            "hybrid_cuda_trainer.safety.V2OnlyJsonIO.set_json_expiring",
            "outcome_memory_updater.rebuild_outcome_memory_from_closed_trades",
        ],
        "production_redis_untouched": True,
        "subtests": results,
        "all_pass": all_pass,
    }
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(json.dumps(payload, indent=2, default=str))
    print(json.dumps({"all_pass": all_pass, **{k: v["pass"] for k, v in results.items()}}, indent=2))
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
