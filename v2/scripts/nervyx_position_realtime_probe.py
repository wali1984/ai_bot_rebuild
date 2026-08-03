#!/usr/bin/env python3
"""Probe position price and AI-reasoning fields over HTTP and resource WebSockets."""

from __future__ import annotations

import argparse
import asyncio
import json
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import websockets


TARGETS = (
    "/api/v2/paper/status",
    "/api/v2/paper/activity",
    "/api/v2/account/positions",
    "/api/v2/mobile/positions",
)

OPEN_ENTRY_FIELDS = (
    "entry_price",
    "avg_entry_price",
    "paper_entry_price",
    "entry_fill_price",
    "open_price",
)
OPEN_MARK_FIELDS = ("mark_price", "last_mark_price", "current_price")
CLOSED_EXIT_FIELDS = (
    "exit_price",
    "paper_exit_price",
    "close_price",
    "closing_price",
    "filled_exit_price",
)


@dataclass(frozen=True)
class ProbeConfig:
    host: str
    output: Path
    sample_size: int
    frames: int
    interval_ms: int
    timeout_seconds: float


def now_utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def payload_data(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data")
    return data if isinstance(data, dict) else payload


def rows(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [row for row in value if isinstance(row, dict)]


def positive_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and value > 0:
        return float(value)
    return None


def first_positive(row: dict[str, Any], fields: tuple[str, ...]) -> tuple[float | None, str | None]:
    for field in fields:
        value = positive_number(row.get(field))
        if value is not None:
            return value, field
    return None, None


def nonempty_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def has_reasoning(row: dict[str, Any]) -> bool:
    for key in ("decision_reasoning", "signal_reasoning", "reasoning"):
        value = row.get(key)
        if isinstance(value, dict) and value:
            return True
    return False


def row_symbol(row: dict[str, Any]) -> str:
    value = row.get("symbol") or row.get("market_symbol") or "unknown"
    return str(value)


def target_row_groups(path: str, payload: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    data = payload_data(payload)
    groups = {
        "open": rows(data.get("positions")),
        "closed": [],
        "historical": [],
    }
    if path == "/api/v2/paper/status":
        groups["closed"] = rows(data.get("closed_trades"))
    elif path == "/api/v2/mobile/positions":
        groups["closed"] = rows(data.get("closed_positions"))
        groups["historical"] = rows(data.get("historical_positions"))
    return groups


def validate_sample(path: str, group: str, row: dict[str, Any], *, require_reasoning: bool) -> dict[str, Any]:
    issues: list[str] = []
    entry, entry_field = first_positive(row, OPEN_ENTRY_FIELDS)
    if entry is None:
        issues.append("entry_price_missing_or_non_positive")

    if group == "open":
        terminal, terminal_field = first_positive(row, OPEN_MARK_FIELDS)
        terminal_name = "mark_price"
        if terminal is None:
            issues.append("mark_price_missing_or_non_positive")
        if not nonempty_text(row.get("mark_price_source")):
            issues.append("mark_price_source_missing")
        if positive_number(row.get("mark_price_age_seconds")) is None and row.get("mark_price_age_seconds") != 0:
            issues.append("mark_price_age_missing")
    else:
        terminal, terminal_field = first_positive(row, CLOSED_EXIT_FIELDS)
        terminal_name = "exit_price"
        if terminal is None:
            issues.append("exit_price_missing_or_non_positive")
        if not nonempty_text(row.get("exit_price_source")):
            issues.append("exit_price_source_missing")

    if not nonempty_text(row.get("entry_price_source")):
        issues.append("entry_price_source_missing")
    if require_reasoning and not has_reasoning(row):
        issues.append("decision_reasoning_missing")

    return {
        "path": path,
        "group": group,
        "symbol": row_symbol(row),
        "entry_price": entry,
        "entry_field": entry_field,
        terminal_name: terminal,
        "terminal_field": terminal_field,
        "mark_price_age_seconds": row.get("mark_price_age_seconds"),
        "mark_price_source": row.get("mark_price_source"),
        "entry_price_source": row.get("entry_price_source"),
        "exit_price_source": row.get("exit_price_source"),
        "has_decision_reasoning": has_reasoning(row),
        "issues": issues,
        "status": "PASS" if not issues else "FAIL",
    }


def validate_payload(path: str, payload: dict[str, Any], *, sample_size: int, transport: str) -> dict[str, Any]:
    groups = target_row_groups(path, payload)
    data = payload_data(payload)
    samples: list[dict[str, Any]] = []
    issues: list[str] = []
    if payload.get("stale") is True:
        issues.append("payload_stale")
    if transport == "websocket" and payload.get("transport") != "websocket":
        issues.append("websocket_transport_marker_missing")
    if not isinstance(data, dict):
        issues.append("payload_data_missing")

    for group, group_rows in groups.items():
        for row in group_rows[:sample_size]:
            sample = validate_sample(
                path,
                group,
                row,
                require_reasoning=path in {"/api/v2/paper/status", "/api/v2/mobile/positions", "/api/v2/account/positions", "/api/v2/paper/activity"},
            )
            samples.append(sample)
            issues.extend(f"{group}:{sample['symbol']}:{issue}" for issue in sample["issues"])

    return {
        "transport": transport,
        "path": path,
        "source": payload.get("source"),
        "source_type": payload.get("source_type"),
        "stale": payload.get("stale"),
        "timestamp": payload.get("timestamp"),
        "received_at": payload.get("received_at"),
        "lag_ms": payload.get("lag_ms"),
        "row_counts": {group: len(group_rows) for group, group_rows in groups.items()},
        "samples": samples,
        "issues": issues,
        "status": "PASS" if not issues else "FAIL",
    }


def fetch_http(config: ProbeConfig, path: str) -> dict[str, Any]:
    request = urllib.request.Request(
        f"http://{config.host}{path}",
        headers={"Accept": "application/json"},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=config.timeout_seconds) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"{path} returned a non-object HTTP payload")
    return payload


async def fetch_websocket(config: ProbeConfig, path: str) -> dict[str, Any]:
    encoded_path = urllib.parse.quote(path, safe="")
    url = f"ws://{config.host}/api/v2/ws/resource?path={encoded_path}&interval_ms={config.interval_ms}"
    async with websockets.connect(url, open_timeout=config.timeout_seconds, ping_interval=None) as socket:
        payload: dict[str, Any] | None = None
        for _ in range(max(1, config.frames)):
            raw = await asyncio.wait_for(socket.recv(), timeout=config.timeout_seconds)
            decoded = json.loads(raw)
            if not isinstance(decoded, dict):
                raise RuntimeError(f"{path} returned a non-object WebSocket payload")
            payload = decoded
        assert payload is not None
        return payload


async def run_probe(config: ProbeConfig) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for path in TARGETS:
        http_payload = fetch_http(config, path)
        results.append(validate_payload(path, http_payload, sample_size=config.sample_size, transport="http"))
        ws_payload = await fetch_websocket(config, path)
        results.append(validate_payload(path, ws_payload, sample_size=config.sample_size, transport="websocket"))

    issues = [
        f"{result['transport']}:{result['path']}:{issue}"
        for result in results
        for issue in result["issues"]
    ]
    return {
        "generated_at": now_utc(),
        "host": config.host,
        "targets": list(TARGETS),
        "sample_size": config.sample_size,
        "frames": config.frames,
        "interval_ms": config.interval_ms,
        "results": results,
        "issues": issues,
        "status": "PASS" if not issues else "FAIL",
    }


def parse_args() -> ProbeConfig:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1:5173")
    parser.add_argument("--output", default="artifacts/nervyx-position-realtime-probe.json")
    parser.add_argument("--sample-size", type=int, default=3)
    parser.add_argument("--frames", type=int, default=2)
    parser.add_argument("--interval-ms", type=int, default=750)
    parser.add_argument("--timeout-seconds", type=float, default=15.0)
    args = parser.parse_args()
    return ProbeConfig(
        host=args.host,
        output=Path(args.output),
        sample_size=max(1, args.sample_size),
        frames=max(1, args.frames),
        interval_ms=max(500, args.interval_ms),
        timeout_seconds=max(1.0, args.timeout_seconds),
    )


def main() -> None:
    config = parse_args()
    report = asyncio.run(run_probe(config))
    config.output.parent.mkdir(parents=True, exist_ok=True)
    config.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "output": str(config.output),
        "results": len(report["results"]),
        "issues": len(report["issues"]),
    }, indent=2, sort_keys=True))
    if report["issues"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
