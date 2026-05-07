from pathlib import Path


def test_forbidden_tokens_not_present() -> None:
    source_paths = (
        Path("v2/backend/app/domain/paper_mode/__init__.py"),
        Path("v2/backend/app/domain/paper_mode/errors.py"),
        Path("v2/backend/app/domain/paper_mode/flag.py"),
    )
    source_text = "\n".join(path.read_text(encoding="utf-8") for path in source_paths)
    tokens = (
        "red" + "is",
        "aio" + "red" + "is",
        "hire" + "d" + "is",
        "fast" + "api",
        "uvi" + "corn",
        "star" + "lette",
        "htt" + "px",
        "req" + "uests",
        "get" + "env",
        "en" + "viron",
        "sub" + "process",
        "sock" + "et",
        "log" + "ging",
        "time" + ".time",
        "time" + ".monotonic",
        "datetime" + ".now",
        "datetime" + ".utcnow",
        "PaperExecution" + "LedgerEntry",
        "RiskDecision" + "Record",
        "OrchestratorDecision" + "Record",
        "ReplayBacktest" + "Run",
        "ReplayBacktest" + "Step",
        "ReplayBacktest" + "Summary",
        "live" + "_enabled",
        "LIVE" + "_ENABLED",
        "sqlite",
        "sql" + "alchemy",
        "par" + "quet",
    )
    for token in tokens:
        assert token not in source_text
    assert "PAPER_MODE_" + "LIVE" + "_" not in source_text.replace(
        "PAPER_MODE_" + "LIVE" + "_BLOCKED",
        "",
    )
