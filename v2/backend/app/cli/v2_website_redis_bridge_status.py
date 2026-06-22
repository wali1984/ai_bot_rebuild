"""V2 Website Rebuild — Phase 1 Redis bridge status emitter.

Walks the declared bridge contracts and the prediction-key resolution
contract, emits a single canonical JSON status payload under the
worklog directory and the public frontend mirror.

This CLI never writes Redis. It uses the allowlisted
``safe_bridge_read`` helper for any optional probe.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

THIS_FILE = Path(__file__).resolve()
REPO_ROOT = THIS_FILE.parents[4]
sys.path.insert(0, str(REPO_ROOT))

from v2.backend.app.services.website.redis_bridge_contracts import (  # noqa: E402
    build_prediction_key_resolution_status,
    list_bridge_contracts,
)

WORKLOG_DIR = (
    REPO_ROOT
    / "claude_worklog"
    / "final_readiness"
    / "v2_website_rebuild_phase_1"
    / "latest"
)
PUBLIC_DIR = (
    REPO_ROOT / "v2" / "frontend" / "public" / "v2_website_rebuild_phase_1" / "latest"
)


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _write(path: Path, doc: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(doc, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def run(
    *,
    symbols: tuple[str, ...] | None = None,
    dry_run: bool = False,
    smoke_test: bool = False,
) -> dict[str, Any]:
    from v2.backend.app.services.v2_symbol_runtime_universe import resolve_symbols
    resolved_symbols = tuple(resolve_symbols(explicit=symbols, smoke_test=smoke_test))
    bridges = list_bridge_contracts()
    resolution = build_prediction_key_resolution_status(symbols=resolved_symbols)
    if not dry_run:
        _write(WORKLOG_DIR / "redis_bridge_contracts.json", bridges)
        _write(WORKLOG_DIR / "prediction_key_resolution_status.json", resolution)
        _write(PUBLIC_DIR / "redis_bridge_contracts.json", bridges)
        _write(PUBLIC_DIR / "prediction_key_resolution_status.json", resolution)
    return {
        "schema_version": "v2_website_rebuild_phase_1_bridge_status_v1",
        "generated_at": _utc_iso(),
        "bridge_count": bridges["bridge_count"],
        "prediction_key_resolution": {
            "symbol_count": resolution["symbol_count"],
            "v2_native_count": resolution["v2_native_count"],
            "bridged_count": resolution["bridged_count"],
            "missing_count": resolution["missing_count"],
        },
        "live_gate": "blocked_human_only",
        "live_symbols": [],
    }


def main() -> int:
    p = argparse.ArgumentParser(prog="v2_website_redis_bridge_status")
    p.add_argument("--symbols", default=None)
    p.add_argument(
        "--smoke-test",
        action="store_true",
        help="Use BTC/ETH/SOL only for explicit smoke tests; never the default.",
    )
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()
    syms = (
        tuple(s.strip().upper() for s in args.symbols.split(",") if s.strip())
        if args.symbols
        else None
    )
    out = run(symbols=syms, dry_run=args.dry_run, smoke_test=args.smoke_test)
    if args.json:
        print(json.dumps(out, indent=2, sort_keys=True, default=str))
    else:
        print(json.dumps(out, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
