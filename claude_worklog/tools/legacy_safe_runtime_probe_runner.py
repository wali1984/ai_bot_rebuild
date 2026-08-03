#!/usr/bin/env python3
"""Run bounded, read-only runtime probes for V2-covered legacy scripts.

This does not execute the whole legacy tree. It only runs known safe adapters
or native V2 replacements that are exchange read-only and V2-Redis guarded.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT_DIR = (
    REPO_ROOT
    / "claude_worklog/final_readiness/legacy_script_validation_20260603/latest"
)
DEFAULT_PUBLIC_DIR = REPO_ROOT / "v2/frontend/public/legacy_script_validation_20260603/latest"
PYTHON = str(REPO_ROOT / ".venv/bin/python3")


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def rel(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


PROBES: list[dict[str, Any]] = [
    {
        "name": "legacy_adapter_kucoin_one_cycle",
        "legacy_scripts": ["ingest/live_kucoin.py"],
        "description": "Runs legacy KuCoin ingestor through V2 Redis-prefix adapter for one cycle.",
        "timeout_seconds": 120,
        "command": [
            PYTHON,
            "-m",
            "v2.backend.app.cli.v2_legacy_ingestor_adapter",
            "kucoin",
        ],
        "expects": ["NON-v2 keys written: 0"],
    },
    {
        "name": "legacy_adapter_coinapi_v1_bounded",
        "legacy_scripts": ["ingest/live_coinapi_v1.py"],
        "description": "Runs legacy CoinAPI v1 streamer through V2 Redis-prefix adapter with a short bound.",
        "timeout_seconds": 75,
        "command": [
            PYTHON,
            "-m",
            "v2.backend.app.cli.v2_legacy_ingestor_adapter",
            "coinapi_v1",
            "--seconds",
            "20",
        ],
        "expects": ["NON-v2 keys written: 0"],
    },
    {
        "name": "v2_kucoin_native_public_rest",
        "legacy_scripts": ["ingest/live_kucoin.py"],
        "description": "Runs the native V2 KuCoin public REST replacement for two symbols.",
        "timeout_seconds": 90,
        "command": [
            PYTHON,
            "-m",
            "v2.backend.app.cli.v2_kucoin_ingestor_worker",
            "--write-evidence",
            "--fetch-public-rest",
            "--fetch-symbol-limit",
            "2",
            "--symbols",
            "BTCUSDT,ETHUSDT",
            "--fetch-timeframes",
            "1m",
            "--write-v2-redis",
        ],
        "expects": ["NATIVE_V2_PUBLIC_REST_OK"],
    },
    {
        "name": "v2_coinank_global_bridge_once",
        "legacy_scripts": [
            "ingest/live_coinank_global_aggregator.py",
            "ingest/liquidation_bridge.py",
        ],
        "description": "Runs the V2 CoinAnk/liquidation bridge one-shot on a small symbol set.",
        "timeout_seconds": 120,
        "command": [
            PYTHON,
            "-m",
            "v2.backend.app.cli.v2_coinank_and_liquidation_bridge",
            "--once",
            "--symbols",
            "BTCUSDT",
            "ETHUSDT",
            "SOLUSDT",
            "XRPUSDT",
            "--tf",
            "1m",
            "--write-v2-redis",
        ],
        "expects": [],
        "redis_min_counts": {
            "v2:coinank:global:*": 1,
            "v2:market:coinank:global:*": 1,
            "v2:features:global_coinank:*": 1,
        },
    },
    {
        "name": "v2_misc_state_keys_publisher",
        "legacy_scripts": ["config:symbols", "market:state", "market:{SYMBOL}"],
        "description": "Publishes V2 replacements for legacy misc/state Redis key families.",
        "timeout_seconds": 45,
        "command": [
            PYTHON,
            "-m",
            "v2.backend.app.cli.v2_misc_state_keys_publisher",
            "--write-v2-redis",
            "--write-evidence",
        ],
        "expects": ["V2_MISC_STATE_KEYS_PUBLISHED"],
    },
]

REDIS_PATTERNS = [
    "v2:kc:*",
    "v2:features:kucoin:*",
    "v2:latest:coinapi:ohlcv:*",
    "v2:normalized:ohlcv:*",
    "v2:ohlcv:list:coinapi:*",
    "v2:coinank:global:*",
    "v2:market:coinank:global:*",
    "v2:features:global_coinank:*",
    "v2:market:kucoin:*",
    "v2:symbol_universe:contract",
    "v2:market:state",
    "v2:market:state:*",
]


def run_probe(probe: dict[str, Any]) -> dict[str, Any]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT)
    env.setdefault("LIVE_GATE", "blocked_human_only")
    started = utc_iso()
    t0 = time.monotonic()
    try:
        proc = subprocess.run(
            probe["command"],
            cwd=str(REPO_ROOT),
            env=env,
            text=True,
            capture_output=True,
            timeout=int(probe["timeout_seconds"]),
            check=False,
        )
        timed_out = False
        returncode = proc.returncode
        stdout = proc.stdout
        stderr = proc.stderr
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        returncode = 124
        stdout = exc.stdout or ""
        stderr = exc.stderr or f"timed out after {probe['timeout_seconds']}s"
    elapsed = round(time.monotonic() - t0, 3)
    combined = f"{stdout}\n{stderr}"
    expected_hits = {needle: (needle in combined) for needle in probe.get("expects", [])}
    ok = returncode == 0 and not timed_out and all(expected_hits.values())
    return {
        "name": probe["name"],
        "legacy_scripts": probe["legacy_scripts"],
        "description": probe["description"],
        "command": probe["command"],
        "started_utc": started,
        "elapsed_seconds": elapsed,
        "timeout_seconds": probe["timeout_seconds"],
        "returncode": returncode,
        "timed_out": timed_out,
        "expected_hits": expected_hits,
        "redis_min_counts": probe.get("redis_min_counts", {}),
        "status": "ok" if ok else "failed",
        "stdout_tail": stdout[-12000:],
        "stderr_tail": stderr[-12000:],
    }


def redis_counts() -> dict[str, Any]:
    try:
        import redis  # type: ignore
    except Exception as exc:
        return {"redis_ok": False, "error": f"import redis failed: {exc}", "patterns": {}}
    try:
        client = redis.Redis(
            host="127.0.0.1",
            port=6379,
            db=0,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=3,
        )
        client.ping()
    except Exception as exc:
        return {"redis_ok": False, "error": f"redis connection failed: {exc}", "patterns": {}}
    counts: dict[str, int] = {}
    for pattern in REDIS_PATTERNS:
        try:
            counts[pattern] = len(list(client.scan_iter(match=pattern, count=1000)))
        except Exception:
            counts[pattern] = -1
    return {"redis_ok": True, "error": None, "patterns": counts}


def apply_redis_assertions(probes: list[dict[str, Any]], redis: dict[str, Any]) -> None:
    if not redis.get("redis_ok"):
        for probe in probes:
            if probe.get("redis_min_counts"):
                probe["status"] = "failed"
                probe["redis_assertions"] = {"status": "failed", "error": redis.get("error")}
        return
    counts = redis.get("patterns", {})
    for probe in probes:
        required = probe.get("redis_min_counts") or {}
        if not required:
            probe["redis_assertions"] = {"status": "not_required", "checks": {}}
            continue
        checks = {
            pattern: {
                "minimum": minimum,
                "actual": int(counts.get(pattern, 0)),
                "ok": int(counts.get(pattern, 0)) >= int(minimum),
            }
            for pattern, minimum in required.items()
        }
        ok = all(row["ok"] for row in checks.values())
        probe["redis_assertions"] = {"status": "ok" if ok else "failed", "checks": checks}
        if not ok:
            probe["status"] = "failed"


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Legacy Safe Runtime Probe Report",
        "",
        f"Generated UTC: {payload['generated_utc']}",
        f"Overall status: `{payload['overall_status']}`",
        "Scope: bounded probes only for V2-covered legacy ingestors and V2 native replacements.",
        "",
        "## Probe Results",
    ]
    for probe in payload["probes"]:
        lines.append(
            f"- `{probe['name']}`: `{probe['status']}` "
            f"(returncode={probe['returncode']}, elapsed={probe['elapsed_seconds']}s)"
        )
    lines.extend(["", "## Redis Evidence"])
    redis = payload["redis_evidence"]
    if not redis["redis_ok"]:
        lines.append(f"- Redis unavailable: {redis['error']}")
    else:
        for pattern, count in sorted(redis["patterns"].items()):
            lines.append(f"- `{pattern}`: {count}")
    lines.extend(
        [
            "",
            "## Safety",
            "- Exchange probes were read-only.",
            "- Legacy Redis writes were only allowed through the V2 prefixing adapter.",
            "- LIVE_GATE remained `blocked_human_only`; `live_symbols=[]`.",
            "",
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--public-dir", type=Path, default=DEFAULT_PUBLIC_DIR)
    parser.add_argument("--skip-public", action="store_true")
    args = parser.parse_args(argv)

    generated_utc = utc_iso()
    probes = [run_probe(probe) for probe in PROBES]
    redis = redis_counts()
    apply_redis_assertions(probes, redis)
    overall_ok = all(probe["status"] == "ok" for probe in probes)
    payload = {
        "schema_version": "legacy_safe_runtime_probe_status_v1",
        "generated_utc": generated_utc,
        "overall_status": "ok" if overall_ok else "failed",
        "probe_count": len(probes),
        "probes_ok": sum(1 for probe in probes if probe["status"] == "ok"),
        "probes_failed": sum(1 for probe in probes if probe["status"] != "ok"),
        "probes": probes,
        "redis_evidence": redis,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
    }
    for target_dir in [args.out_dir] + ([] if args.skip_public else [args.public_dir]):
        write_json(target_dir / "legacy_safe_runtime_probe_status.json", payload)
        (target_dir / "SAFE_RUNTIME_PROBE_REPORT.md").write_text(
            markdown(payload),
            encoding="utf-8",
        )
    print(
        json.dumps(
            {
                "generated_utc": generated_utc,
                "overall_status": payload["overall_status"],
                "probes_ok": payload["probes_ok"],
                "probes_failed": payload["probes_failed"],
                "out_dir": rel(args.out_dir.resolve()),
                "public_dir": None if args.skip_public else rel(args.public_dir.resolve()),
            },
            sort_keys=True,
        )
    )
    return 0 if overall_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
