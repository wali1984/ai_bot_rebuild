"""Prometheus metrics exporter for Spark closed-loop runtime."""

from __future__ import annotations

import argparse
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

from v2.backend.app.closed_loop.lease_store.sqlite_store import SQLiteLeaseStore
from v2.backend.app.closed_loop.services.systemd_notify import (
    notify_ready,
    notify_status,
    notify_watchdog,
)


def build_metrics_payload(store: SQLiteLeaseStore) -> dict[str, float | None]:
    metrics = store.metrics_snapshot()
    return metrics


def _render_line(metric_name: str, value: Any, *, label: str = "", value_name: str = "value") -> str:
    if isinstance(value, (int, float)):
        metric_value = f"{float(value):.3f}"
    elif value is None:
        metric_value = "nan"
    else:
        metric_value = str(value)
    if label:
        label_clause = f'{{lane_group="{label}"}}'
    else:
        label_clause = ""
    return f"# HELP {metric_name} {metric_name}\n# TYPE {metric_name} gauge\n{metric_name}{label_clause} {metric_value}\n"


def render_prometheus(payload: dict[str, Any]) -> str:
    lines = [
        _render_line("v2_closed_loop_active_leases", payload.get("v2_closed_loop_active_leases")),
        _render_line("v2_closed_loop_busy_workers", payload.get("v2_closed_loop_busy_workers")),
        _render_line("v2_closed_loop_idle_workers", payload.get("v2_closed_loop_idle_workers")),
        _render_line(
            "v2_closed_loop_worker_heartbeat_age_seconds",
            payload.get("v2_closed_loop_worker_heartbeat_age_seconds"),
        ),
        _render_line(
            "v2_closed_loop_lease_heartbeat_age_seconds",
            payload.get("v2_closed_loop_lease_heartbeat_age_seconds"),
        ),
        _render_line(
            "v2_closed_loop_queue_eligible_tasks",
            payload.get("v2_closed_loop_queue_eligible_tasks"),
        ),
        _render_line(
            "v2_closed_loop_queue_oldest_task_age_seconds",
            payload.get("v2_closed_loop_queue_oldest_task_age_seconds"),
        ),
        _render_line(
            "v2_closed_loop_task_completions_total",
            payload.get("v2_closed_loop_task_completions_total"),
        ),
        _render_line(
            "v2_closed_loop_codex_fail_map_total",
            payload.get("v2_closed_loop_codex_fail_map_total"),
        ),
        _render_line(
            "v2_closed_loop_executor_unavailable",
            payload.get("v2_closed_loop_executor_unavailable"),
        ),
        _render_line(
            "v2_closed_loop_duplicate_lease_conflicts_total",
            payload.get("v2_closed_loop_duplicate_lease_conflicts_total"),
        ),
        _render_line(
            "v2_closed_loop_burndown_blockers",
            payload.get("v2_closed_loop_burndown_blockers"),
        ),
        _render_line(
            "v2_closed_loop_payload_age_seconds",
            payload.get("v2_closed_loop_payload_age_seconds"),
        ),
    ]
    return "\n".join(lines)


class _MetricsHandler(BaseHTTPRequestHandler):
    store: SQLiteLeaseStore | None = None

    def do_GET(self) -> None:  # noqa: N802
        if self.path not in ("/", "/metrics"):
            self.send_response(404)
            self.end_headers()
            return
        if self.store is None:
            self.send_response(503)
            self.end_headers()
            return
        body = render_prometheus(build_metrics_payload(self.store)).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def serve(store: SQLiteLeaseStore, *, host: str = "127.0.0.1", port: int = 8123) -> None:
    _MetricsHandler.store = store
    server = HTTPServer((host, port), _MetricsHandler)
    thread = threading.Thread(target=server.serve_forever, name="spark-metrics", daemon=True)
    thread.start()
    notify_ready()
    notify_status("Spark metrics exporter running")
    try:
        while True:
            notify_watchdog()
            time.sleep(1)
    except KeyboardInterrupt:
        server.shutdown()
        server.server_close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-path", default=None)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8123)
    args = parser.parse_args(argv)
    store = SQLiteLeaseStore(db_path=args.db_path)
    _ = build_metrics_payload(store)
    serve(store, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
