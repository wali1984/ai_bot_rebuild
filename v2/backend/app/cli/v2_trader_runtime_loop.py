"""Guarded V2 trader runtime loop.

The loop reads current orchestrator/signal payloads and Binance credentials
from ``v2/.env.local`` by name only. It writes redacted status artifacts and
can call the live order transport only when the audited V2 live gate, accepted
symbols, active risk profile, lineage, exchange filters, balance, kill switch,
and transport write guards all pass. It never calls test-order, cancel, modify,
leverage, margin, transfer, withdrawal, legacy restart, Redis trim, or old Redis
paths.
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

from v2.backend.app.services.live_gate.single_pass import (  # noqa: E402
    LIVE_GATE_BLOCKED,
    _dumps,
    _est_iso,
    _json_load,
    _write_text_atomic,
    build_binance_connectivity_status,
    build_trader_runtime_start_status,
    default_paths,
)
from v2.backend.app.services.live_gate.runtime_execution_state import (  # noqa: E402
    apply_runtime_state_to_trader_status,
    read_runtime_execution_state,
)
from v2.backend.app.services.live_gate.binance_live_order_transport import (  # noqa: E402
    evaluate_live_order_transport,
)


def run_once(*, repo_root: Path, network_probe_enabled: bool = True) -> dict[str, object]:
    paths = default_paths(repo_root)
    generated_est = _est_iso()
    signal_status = _json_load(paths.all_tf_signal_status_path)
    connectivity = build_binance_connectivity_status(
        env_local_path=paths.env_local_path,
        generated_est=generated_est,
        network_probe_enabled=network_probe_enabled,
    )
    trader = build_trader_runtime_start_status(
        signal_status,
        generated_est=generated_est,
        service_start={
            "attempted": True,
            "method": "v2_trader_runtime_loop",
            "process_mode": "loop_or_once",
            "started_est": generated_est,
        },
    )
    runtime_state = read_runtime_execution_state(repo_root=repo_root)
    trader = apply_runtime_state_to_trader_status(trader, runtime_state)
    trader["binance_private_readonly"] = connectivity
    transport_status = evaluate_live_order_transport(
        repo_root=repo_root,
        signal_status=signal_status,
        trader_status=trader,
        runtime_read=runtime_state,
    )
    trader["live_order_transport"] = transport_status
    trader["live_order_transport_bound"] = bool(transport_status.get("live_order_transport_bound"))
    trader["writes_exchange_orders"] = bool(transport_status.get("writes_exchange_orders"))
    trader["places_real_order"] = bool(transport_status.get("places_real_order"))
    trader["generated_utc"] = trader.get("generated_utc") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    trader["live_gate_status"] = trader.get("live_gate") or LIVE_GATE_BLOCKED
    out = repo_root / "v2/frontend/public/operator_runtime/v2_trader_runtime_state/latest/v2_trader_runtime_state_status.json"
    _write_text_atomic(out, _dumps(trader))
    return {
        "status_path": str(out),
        "status": trader["status"],
        "signals_observed_count": trader["signals_observed_count"],
        "live_gate": trader.get("live_gate", LIVE_GATE_BLOCKED),
        "live_symbols": trader.get("live_symbols", []),
        "execution_live_symbols": trader.get("execution_live_symbols", []),
        "trader_execution_enabled": trader.get("trader_execution_enabled", False),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run mutation-frozen V2 trader runtime observer.")
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval", type=float, default=30.0)
    parser.add_argument("--network-probe", action="store_true", default=False)
    args = parser.parse_args(argv)
    repo_root = Path(args.repo_root).resolve()
    if not args.loop:
        print(json.dumps(run_once(repo_root=repo_root, network_probe_enabled=args.network_probe), indent=2, sort_keys=True))
        return 0
    while True:
        run_once(repo_root=repo_root, network_probe_enabled=args.network_probe)
        time.sleep(max(5.0, float(args.interval)))


if __name__ == "__main__":
    raise SystemExit(main())
