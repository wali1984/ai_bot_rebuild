from pathlib import Path


def test_forbidden_tokens_not_present() -> None:
    source_text = "\n".join(
        (
            Path("v2/backend/app/domain/shadow_mode_readiness/__init__.py").read_text(),
            Path("v2/backend/app/domain/shadow_mode_readiness/errors.py").read_text(),
            Path("v2/backend/app/domain/shadow_mode_readiness/flag.py").read_text(),
        )
    )
    disallowed = (
        "red" + "is",
        "aio" + "red" + "is",
        "hir" + "edis",
        "fast" + "api",
        "uvi" + "corn",
        "star" + "lette",
        "ht" + "tpx",
        "re" + "quests",
        "get" + "env",
        "en" + "viron",
        "sub" + "process",
        "sock" + "et",
        "log" + "ging",
        "time" + ".time",
        "time" + ".monotonic",
        "datetime" + ".now",
        "datetime" + ".utcnow",
        "Paper" + "ModeFlag",
        "Paper" + "ExecutionLedgerEntry",
        "Risk" + "DecisionRecord",
        "Orchestrator" + "DecisionRecord",
        "Replay" + "BacktestRun",
        "Replay" + "BacktestStep",
        "Replay" + "BacktestSummary",
        "live" + "_enabled",
        "LIVE" + "_ENABLED",
        "SHADOW" + "_MODE_LIVE",
        "shadow" + "_decision_id",
        "sq" + "lite",
        "sql" + "alchemy",
        "par" + "quet",
    )

    for item in disallowed:
        assert item not in source_text
