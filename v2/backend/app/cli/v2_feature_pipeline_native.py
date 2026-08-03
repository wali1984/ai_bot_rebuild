"""V2 native feature pipeline worker CLI.

Paper/shadow only. Emits two output payloads:

1. Status payload (always when --write-evidence or --emit-latest-snapshot):
   v2/frontend/public/operator_runtime/v2_feature_pipeline_native/latest/v2_feature_pipeline_native_status.json
2. Trainer-consumable snapshot (when --emit-latest-snapshot):
   v2/frontend/public/operator_runtime/v2_feature_pipeline_native/latest/latest_feature_snapshot.json
   v2/runtime/v2_feature_pipeline_native/latest/latest_feature_snapshot.json

Does NOT connect to legacy Redis. Does NOT mutate exchange state.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

from v2.backend.app.services.feature_pipeline_native.service import (
    FeaturePipelineNativeService,
)

REPO = Path(__file__).resolve().parents[4]
PUBLIC_STATUS_PATH = (
    REPO
    / "v2/frontend/public/operator_runtime/v2_feature_pipeline_native/latest/v2_feature_pipeline_native_status.json"
)
PUBLIC_SNAPSHOT_PATH = (
    REPO
    / "v2/frontend/public/operator_runtime/v2_feature_pipeline_native/latest/latest_feature_snapshot.json"
)
RUNTIME_SNAPSHOT_PATH = (
    REPO
    / "v2/runtime/v2_feature_pipeline_native/latest/latest_feature_snapshot.json"
)


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="V2 native feature pipeline worker (paper/shadow only)")
    p.add_argument("--write-evidence", action="store_true", help="Write status payload to public path.")
    p.add_argument("--dry-run", action="store_true", help="Print status payload to stdout.")
    p.add_argument("--out", type=Path, default=PUBLIC_STATUS_PATH, help="Status output path override.")
    p.add_argument(
        "--emit-latest-snapshot",
        action="store_true",
        help="Emit a trainer-consumable latest_feature_snapshot.json to both public and runtime paths.",
    )
    p.add_argument(
        "--symbol",
        default=None,
        help=(
            "Symbol for the trainer-consumable snapshot. If omitted, falls "
            "back to the first symbol returned by the dynamic universe "
            "resolver (25-symbol baseline + published universe). Pass "
            "--smoke-test to opt into the BTC/ETH/SOL smoke set."
        ),
    )
    p.add_argument(
        "--smoke-test",
        action="store_true",
        help="Use the BTC/ETH/SOL smoke-test set (test only).",
    )
    p.add_argument("--timeframe", default="1m", help="Timeframe for the trainer-consumable snapshot.")
    p.add_argument(
        "--snapshot-public-out",
        type=Path,
        default=PUBLIC_SNAPSHOT_PATH,
        help="Public snapshot output path override.",
    )
    p.add_argument(
        "--snapshot-runtime-out",
        type=Path,
        default=RUNTIME_SNAPSHOT_PATH,
        help="Runtime snapshot output path override.",
    )
    args = p.parse_args(argv)

    svc = FeaturePipelineNativeService()
    status = svc.current_paper_only_status()

    if args.dry_run and not args.emit_latest_snapshot:
        sys.stdout.write(json.dumps(status, indent=2, sort_keys=True) + "\n")
        return 0

    if args.write_evidence or args.emit_latest_snapshot:
        _write_json(args.out, status)
        print(f"v2_feature_pipeline_native_status_written path={args.out} live_gate={status['live_gate']}")

    if args.emit_latest_snapshot:
        from v2.backend.app.services.v2_symbol_runtime_universe import resolve_symbols
        resolved_symbol = args.symbol or (
            resolve_symbols(smoke_test=args.smoke_test)[0]
        )
        inputs = svc.build_deterministic_default_inputs(
            symbol=resolved_symbol,
            timeframe=args.timeframe,
            generated_utc=_now_iso(),
        )
        snapshot = svc.emit_trainer_consumable_snapshot(inputs)
        _write_json(args.snapshot_public_out, snapshot)
        _write_json(args.snapshot_runtime_out, snapshot)
        print(
            f"v2_native_feature_snapshot_written public={args.snapshot_public_out} "
            f"runtime={args.snapshot_runtime_out} "
            f"feature_snapshot_id={snapshot['feature_snapshot_id']} "
            f"trainer_consumable={snapshot['trainer_consumable']} "
            f"feature_freshness_state={snapshot['feature_freshness_state']}"
        )
        return 0

    if not args.write_evidence:
        sys.stdout.write(json.dumps(status, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
