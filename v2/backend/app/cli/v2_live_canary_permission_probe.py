"""V2 live-canary network-safe permission probe CLI.

Bounded one-shot (or ``--loop``) tool that runs the read-only
permission probe and writes its status payload to:

- ``claude_worklog/final_readiness/v2_live_canary_permission_probe/latest/permission_probe_status.json``
- ``v2/frontend/public/operator_runtime/v2_live_canary/latest/permission_probe_status.json``

The CLI NEVER places a real order. NEVER cancels or modifies orders.
NEVER changes leverage. NEVER changes margin mode. NEVER writes
legacy Redis. NEVER reads or logs raw API key/secret values.

Allowed file writes: the two paths above.
Allowed Redis writes: NONE.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from v2.backend.app.services.live_canary.permission_probe import (
    PROBE_GO_BLOCKED,
    PROBE_GO_READY,
    run_probe,
)

WORKLOG_STATUS = Path(
    "claude_worklog/final_readiness/v2_live_canary_permission_probe/latest/permission_probe_status.json"
)
PUBLIC_STATUS = Path(
    "v2/frontend/public/operator_runtime/v2_live_canary/latest/permission_probe_status.json"
)
WORKLOG_GO_NO_GO = Path(
    "claude_worklog/final_readiness/v2_live_canary_permission_probe/latest/GO_NO_GO.md"
)


def _write_status_files(payload: dict, worklog: Path, public: Path) -> None:
    body = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    worklog.parent.mkdir(parents=True, exist_ok=True)
    worklog.write_text(body, encoding="utf-8")
    public.parent.mkdir(parents=True, exist_ok=True)
    public.write_text(body, encoding="utf-8")


def _write_go_no_go(label: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(label + "\n", encoding="utf-8")


def run_once(
    *,
    secrets_path: Path | None = None,
    approval_path: Path | None = None,
    codex_pass_marker_path: Path | None = None,
    codex_test_order_marker_path: Path | None = None,
    network_probe_enabled: bool = True,
    out_worklog: Path | None = None,
    out_public: Path | None = None,
    out_go_no_go: Path | None = None,
) -> dict:
    result = run_probe(
        secrets_path=secrets_path,
        approval_path=approval_path,
        codex_pass_marker_path=codex_pass_marker_path,
        codex_test_order_marker_path=codex_test_order_marker_path,
        network_probe_enabled=network_probe_enabled,
    )
    payload = result.as_payload()
    _write_status_files(
        payload,
        out_worklog if out_worklog is not None else WORKLOG_STATUS,
        out_public if out_public is not None else PUBLIC_STATUS,
    )
    _write_go_no_go(
        payload["go_no_go"],
        out_go_no_go if out_go_no_go is not None else WORKLOG_GO_NO_GO,
    )
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v2_live_canary_permission_probe")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=300)
    parser.add_argument("--out-worklog", type=Path, default=WORKLOG_STATUS)
    parser.add_argument("--out-public", type=Path, default=PUBLIC_STATUS)
    parser.add_argument("--out-go-no-go", type=Path, default=WORKLOG_GO_NO_GO)
    parser.add_argument("--secrets-path", type=Path, default=None)
    parser.add_argument("--approval-path", type=Path, default=None)
    parser.add_argument("--codex-pass-marker-path", type=Path, default=None)
    parser.add_argument(
        "--codex-test-order-marker-path", type=Path, default=None
    )
    parser.add_argument(
        "--no-network",
        dest="network_probe_enabled",
        action="store_false",
        help="Skip the real Binance network calls; treat as DISABLED.",
    )
    parser.set_defaults(network_probe_enabled=True)
    args = parser.parse_args(argv)
    if args.once == args.loop:
        args.once = True
        args.loop = False
    if args.once:
        payload = run_once(
            secrets_path=args.secrets_path,
            approval_path=args.approval_path,
            codex_pass_marker_path=args.codex_pass_marker_path,
            codex_test_order_marker_path=args.codex_test_order_marker_path,
            network_probe_enabled=args.network_probe_enabled,
            out_worklog=args.out_worklog,
            out_public=args.out_public,
            out_go_no_go=args.out_go_no_go,
        )
        print(
            json.dumps(
                {
                    "go_no_go": payload["go_no_go"],
                    "mode_selected": payload["mode_selected"],
                    "symbols_requested": payload["symbols_requested"],
                    "exchange_info_call_status": payload[
                        "exchange_info_call_status"
                    ],
                    "account_read_permission_status": payload[
                        "account_read_permission_status"
                    ],
                    "test_order_endpoint_status": payload[
                        "test_order_endpoint_status"
                    ],
                    "fail_blockers": payload["fail_blockers"],
                    "real_order_attempted": payload["real_order_attempted"],
                    "leverage_changed": payload["leverage_changed"],
                    "margin_mode_changed": payload["margin_mode_changed"],
                    "writes_exchange_orders": payload["writes_exchange_orders"],
                    "writes_legacy_redis": payload["writes_legacy_redis"],
                    "raw_credential_in_payload": payload[
                        "raw_credential_in_payload"
                    ],
                    "live_gate": payload["live_gate"],
                    "live_symbols": payload["live_symbols"],
                },
                sort_keys=True,
            )
        )
        return 0
    while True:
        run_once(
            secrets_path=args.secrets_path,
            approval_path=args.approval_path,
            codex_pass_marker_path=args.codex_pass_marker_path,
            codex_test_order_marker_path=args.codex_test_order_marker_path,
            network_probe_enabled=args.network_probe_enabled,
            out_worklog=args.out_worklog,
            out_public=args.out_public,
            out_go_no_go=args.out_go_no_go,
        )
        try:
            time.sleep(max(30, int(args.interval_seconds)))
        except KeyboardInterrupt:
            return 0


if __name__ == "__main__":
    sys.exit(main())
