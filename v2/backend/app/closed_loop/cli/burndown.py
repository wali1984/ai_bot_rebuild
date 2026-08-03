"""CLI wrapper for Spark burndown service."""

from __future__ import annotations

from v2.backend.app.closed_loop.services.burndown import run_once


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--db-path", default=None)
    args = parser.parse_args(argv)
    run_once(db_path=args.db_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
