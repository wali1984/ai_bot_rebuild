"""V2-owned ingestors runtime CLI (smoke / dry-run only).

Sets sys.path to v2/legacy_owned_runtime/ subroots, probes each ingestor
module, and emits a public status payload. Does NOT open any WebSocket or
REST connection, and does NOT write to legacy Redis. This is a dry-run
smoke: it proves the V2-owned import path resolves the ingestor modules
without touching the legacy bot root.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from v2.backend.app.services.v2_owned_runtime.smoke_base import (
    base_status,
    emit_status,
    ensure_v2_owned_sys_path,
    probe_imports,
    summarize_import_probes,
)
from v2.backend.app.services.v2_owned_runtime.redis_namespace_adapter import (
    policy_status_snapshot,
    RedisNamespaceAdapter,
)
from v2.backend.app.services.v2_owned_runtime.exchange_fail_closed_adapter import (
    exchange_invariants_snapshot,
)
from v2.backend.app.services.v2_symbol_runtime_universe import resolve_symbols

REPO = Path(__file__).resolve().parents[4]
PUBLIC_STATUS = REPO / "v2/frontend/public/operator_runtime/v2_owned_ingestors/latest/status.json"

INGESTOR_MODULES = [
    "ingest.live_binance",
    "ingest.live_binance_liquidations",
    "ingest.live_coinank",
    "ingest.live_coinank_global_aggregator",
    "ingest.live_kucoin",
    "ingest.live_coinapi_v1",
    "ingest.live_coinapi_wsds",
    "ingest.live_technical_analysis",
    "ingest.realtime_price_provider",
    "ingest.liquidation_bridge",
    "ingest.liquidation_levels_engine",
]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="V2-owned ingestors smoke")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--symbols", default=None)
    p.add_argument("--smoke-test", action="store_true")
    p.add_argument("--max-events", type=int, default=5)
    p.add_argument("--out", type=Path, default=PUBLIC_STATUS)
    args = p.parse_args(argv)
    symbols = tuple(
        resolve_symbols(
            explicit=(
                tuple(s.strip().upper() for s in args.symbols.split(",") if s.strip())
                if args.symbols
                else None
            ),
            smoke_test=args.smoke_test,
        )
    )

    paths_added = ensure_v2_owned_sys_path()
    probes = probe_imports(INGESTOR_MODULES)
    probe_summary = summarize_import_probes(probes)

    status = base_status("v2_owned_ingestors")
    status.update({
        "sys_path_added": paths_added,
        "symbols": list(symbols),
        "symbol_count": len(symbols),
        "ingestor_module_count": len(INGESTOR_MODULES),
        **probe_summary,
        "redis_policy": policy_status_snapshot(RedisNamespaceAdapter()),
        "exchange_invariants": exchange_invariants_snapshot(),
        "websocket_connections_opened": 0,
        "rest_connections_opened": 0,
    })
    emit_status(args.out, status)
    print(json.dumps({k: status[k] for k in ("resolved_count", "unresolved_count", "legacy_root_rejected_count", "smoke_pass")}))
    return 0 if status["smoke_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
