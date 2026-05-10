from __future__ import annotations

import argparse
from pathlib import Path

from v2.backend.app.proof.readonly_market_exchange_data_plane import (
    GO_NO_GO_MARKER,
    write_readonly_market_exchange_data_plane,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="readonly_market_exchange_data_plane",
        description="Emit read-only market/exchange data-plane artifacts for the V2 cockpit.",
    )
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--public-output-dir", default=None)
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument(
        "--fetch-binance",
        action="store_true",
        help="Use Binance USD-M public GET-only market endpoints; falls back to fixtures on failure.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    write_readonly_market_exchange_data_plane(
        Path(args.output_dir),
        public_output_dir=Path(args.public_output_dir) if args.public_output_dir else None,
        fetch_binance=args.fetch_binance,
        symbol=args.symbol,
    )
    print(GO_NO_GO_MARKER)
    print(args.output_dir)
    if args.public_output_dir:
        print(args.public_output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
