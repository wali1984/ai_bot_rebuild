"""Run each V2 production-equivalent loop once (helper)."""
from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=["ingestors", "features", "rl_core", "orchestrator", "trade_mgmt", "all"], default="all")
    parser.add_argument("--symbols", default="BTCUSDT,ETHUSDT,SOLUSDT")
    args = parser.parse_args(argv)
    rc = 0
    if args.phase in ("ingestors", "all"):
        from v2.backend.app.cli import v2_native_ingestors_live_loop as ing
        rc |= ing.main(["--symbols", args.symbols])
    if args.phase in ("features", "all"):
        try:
            from v2.backend.app.cli import v2_feature_pipeline_native_loop as fp
            rc |= fp.main(["--symbols", args.symbols])
        except ImportError:
            print("feature_pipeline loop not yet built")
    if args.phase in ("rl_core", "all"):
        try:
            from v2.backend.app.cli import v2_rl_core_inference_loop as rl
            rc |= rl.main(["--symbols", args.symbols])
        except ImportError:
            print("rl_core inference loop not yet built")
    if args.phase in ("orchestrator", "all"):
        try:
            from v2.backend.app.cli import v2_orchestrator_arbitration_loop as orc
            rc |= orc.main([])
        except ImportError:
            print("orchestrator loop not yet built")
    if args.phase in ("trade_mgmt", "all"):
        try:
            from v2.backend.app.cli import v2_trade_management_paper_loop as tm
            rc |= tm.main([])
        except ImportError:
            print("trade_mgmt loop not yet built")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
