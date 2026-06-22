"""CLI wrapper for Spark autoseed service."""

from __future__ import annotations

from v2.backend.app.closed_loop.services.autoseed import run_once


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--db-path", default=None)
    parser.add_argument("--max-new-tasks", type=int, default=3)
    parser.add_argument("--mission-category", action="append", default=None)
    args = parser.parse_args(argv)
    run_once(
        db_path=args.db_path,
        max_new_tasks=args.max_new_tasks,
        mission_filter=args.mission_category,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
