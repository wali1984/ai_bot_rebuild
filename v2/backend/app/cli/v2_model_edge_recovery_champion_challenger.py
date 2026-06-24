"""Train/evaluate the trusted-replay model edge recovery challenger.

The command writes only V2-owned disk/public artifacts by default. With
``--publish-paper-challenger`` it may also write explicit B-grade paper-only
signals to ``v2:signals:paper:challenger:*`` after the untouched holdout gate
passes. It never writes live execution keys and never calls an exchange.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from v2.backend.app.services.native_trainer.model_edge_recovery_challenger import (
    emit_artifacts,
    publish_paper_challenger_signals,
    run_champion_challenger,
)


def connect_redis() -> Any:
    import redis  # type: ignore

    client = redis.Redis(
        host="127.0.0.1",
        port=6379,
        db=0,
        decode_responses=True,
        socket_connect_timeout=3,
        socket_timeout=10,
    )
    client.ping()
    return client


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--scan-limit", type=int, default=60_000)
    parser.add_argument("--replay-limit", type=int, default=30_000)
    parser.add_argument("--min-train-rows", type=int, default=1000)
    parser.add_argument("--min-validation-trades", type=int, default=100)
    parser.add_argument("--min-holdout-trades", type=int, default=100)
    parser.add_argument("--max-features", type=int, default=256)
    parser.add_argument(
        "--publish-paper-challenger",
        action="store_true",
        help="Publish explicit B-grade paper-only challenger signals if holdout gate passes.",
    )
    parser.add_argument("--max-paper-signals", type=int, default=5)
    args = parser.parse_args(argv)

    repo_root = args.repo_root.resolve()
    result = run_champion_challenger(
        repo_root=repo_root,
        scan_limit=args.scan_limit,
        replay_limit=args.replay_limit,
        min_train_rows=args.min_train_rows,
        min_validation_trades=args.min_validation_trades,
        min_holdout_trades=args.min_holdout_trades,
        max_features=args.max_features,
    )
    paths_written = emit_artifacts(repo_root, result)
    publisher_result = None
    if args.publish_paper_challenger:
        publisher_result = publish_paper_challenger_signals(
            client=connect_redis(),
            result=result,
            max_signals=args.max_paper_signals,
        )
        result = dict(result)
        result["paper_challenger_publication"] = publisher_result
        paths_written = emit_artifacts(repo_root, result)

    print(
        json.dumps(
            {
                "status": result.get("status"),
                "result_hash": result.get("result_hash"),
                "untouched_holdout_metrics": result.get("untouched_holdout_metrics"),
                "paper_challenger_policy": result.get("paper_challenger_policy"),
                "paper_challenger_publication": publisher_result,
                "paths_written": [str(path) for path in paths_written],
            },
            indent=2,
            sort_keys=True,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

