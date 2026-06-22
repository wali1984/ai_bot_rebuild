"""V2 native ingestors verification worker (P0.5).

Emits a public payload at
v2/frontend/public/operator_runtime/v2_native_ingestors/latest/
v2_native_ingestors_status.json that enumerates each legacy ingestor
and its V2 classification. No network IO; no Redis writes.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from v2.backend.app.services.native_ingestors import (
    classify_all_ingestors,
    ingestors_invariants_snapshot,
)

DEFAULT_PAYLOAD_PATH = Path(
    "v2/frontend/public/operator_runtime/v2_native_ingestors/latest/v2_native_ingestors_status.json"
)

V2_RUNTIME_TARGETS = {
    "live_binance": "v2.backend.app.cli.v2_native_ingestors_live_loop",
    "live_binance_liquidations": "v2.backend.app.cli.v2_liquidation_wss_loop",
    "live_coinank": "v2/legacy_owned_runtime/ingest/live_coinank.py",
    "live_coinank_global_aggregator": "v2/legacy_owned_runtime/ingest/live_coinank_global_aggregator.py",
    "live_kucoin": "v2.backend.app.cli.v2_kucoin_ingestor_worker",
    "live_coinapi_v1": "v2.backend.app.cli.v2_coinapi_rest_ingestor_worker",
    "live_coinapi_wsds": "v2.backend.app.cli.v2_coinapi_wsds_loop",
    "live_technical_analysis": "v2.backend.app.cli.v2_full_talib_ta_loop",
    "realtime_price_provider": "v2.backend.app.cli.v2_native_ingestors_live_loop",
    "liquidation_bridge": "v2.backend.app.cli.v2_liquidation_wss_loop",
    "liquidation_levels_engine": "v2.backend.app.cli.v2_liquidation_levels_engine",
    "ccxt_historical": "v2.backend.app.cli.v2_native_ingestors_live_loop + local_replay_store",
}


def build_payload() -> dict:
    records = classify_all_ingestors()
    inv = ingestors_invariants_snapshot()
    body = {
        "worker_id": "v2_native_ingestors",
        "schema_version": "v2_native_ingestors_status_v1",
        "scope": "PAPER_ONLY_PUBLIC_MARKET_DATA_ONLY_CLASSIFICATION",
        "ingestors": [
            {
                "name": r.name,
                "legacy_path": r.legacy_path,
                "v2_runtime_target": V2_RUNTIME_TARGETS.get(r.name),
                "runtime_uses_legacy_ingest_script": r.name in {
                    "live_coinank",
                    "live_coinank_global_aggregator",
                },
                "adapter_runtime_allowed": False,
                "legacy_sha256": r.legacy_sha256,
                "legacy_size_bytes": r.legacy_size_bytes,
                "classification": r.classification.classification,
                "rationale": r.classification.rationale,
                "requires_secret_env": list(r.classification.requires_secret_env),
                "public_market_data_only": r.classification.public_market_data_only,
                "v2_namespace_payload_path": r.classification.v2_namespace_payload_path,
                "rate_limit_concern_notes": r.classification.rate_limit_concern_notes,
            }
            for r in records
        ],
        "ingestor_count": len(records),
        "total_ingestors": len(records),
        "invariants": inv,
        "live_gate": "blocked_human_only",
        "runtime_mode": "PAPER_ONLY_PUBLIC_MARKET_DATA_CLASSIFICATION",
        "dynamic_symbol_refresh_without_restart": True,
        "trader_execution_enabled": True,
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
    }
    return body


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v2_native_ingestors_worker")
    parser.add_argument("--write-evidence", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    payload = build_payload()
    out_text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.dry_run and args.write_evidence:
        print("ERROR: --dry-run and --write-evidence are mutually exclusive", file=sys.stderr)
        return 2
    if args.write_evidence:
        dest = args.out or DEFAULT_PAYLOAD_PATH
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(out_text)
        print(f"v2_native_ingestors_status_written path={dest}")
        return 0
    print(out_text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
