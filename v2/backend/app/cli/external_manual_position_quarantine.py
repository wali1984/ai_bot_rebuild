from __future__ import annotations

import argparse
from pathlib import Path

from v2.backend.app.proof.external_manual_position_quarantine import (
    GO_NO_GO_MARKER,
    write_external_manual_position_quarantine_proof,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="external_manual_position_quarantine",
        description="Emit deterministic offline external/manual position quarantine proof artifacts.",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Allowed final_readiness output directory for 2X quarantine proof artifacts.",
    )
    parser.add_argument(
        "--public-output-dir",
        default=None,
        help="Optional allowed frontend public directory to mirror static dashboard artifacts.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    write_external_manual_position_quarantine_proof(
        Path(args.output_dir),
        public_output_dir=Path(args.public_output_dir) if args.public_output_dir else None,
    )
    print(GO_NO_GO_MARKER)
    print(args.output_dir)
    if args.public_output_dir:
        print(args.public_output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
