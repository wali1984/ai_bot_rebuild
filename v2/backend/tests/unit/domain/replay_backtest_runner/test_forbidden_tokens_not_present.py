from pathlib import Path


def test_forbidden_tokens_not_present():
    roots = [
        Path("v2/backend/app/domain/replay_backtest_runner/__init__.py"),
        Path("v2/backend/app/domain/replay_backtest_runner/errors.py"),
        Path("v2/backend/app/domain/replay_backtest_runner/run.py"),
        Path("v2/backend/app/domain/replay_backtest_runner/step.py"),
        Path("v2/backend/app/domain/replay_backtest_runner/summary.py"),
    ]
    tokens = (
        "red" + "is",
        "aio" + "red" + "is",
        "hire" + "dis",
        "fast" + "api",
        "uvi" + "corn",
        "star" + "lette",
        "htt" + "px",
        "requ" + "ests",
        "get" + "env",
        "en" + "viron",
        "sub" + "process",
        "sock" + "et",
        "log" + "ging",
        "time" + "." + "time",
        "time" + "." + "monotonic",
        "datetime" + "." + "now",
        "datetime" + "." + "utcnow",
        "PaperExecution" + "LedgerEntry",
        "RiskDecision" + "Record",
        "OrchestratorDecision" + "Record",
        "sql" + "ite",
        "sql" + "alchemy",
        "par" + "quet",
    )
    contents = "\n".join(path.read_text(encoding="utf-8") for path in roots)
    for token in tokens:
        assert token not in contents
