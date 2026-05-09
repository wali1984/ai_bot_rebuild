from __future__ import annotations

import argparse
from pathlib import Path

from v2.backend.app.proof import GO_NO_GO_MARKER, write_non_live_proof


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="non_live_operational_proof",
        description="Emit deterministic offline V2 replay/paper/shadow proof artifacts.",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Directory where non-live proof artifacts will be written.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    output_dir = Path(args.output_dir)
    write_non_live_proof(output_dir)
    print(GO_NO_GO_MARKER)
    print(output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
