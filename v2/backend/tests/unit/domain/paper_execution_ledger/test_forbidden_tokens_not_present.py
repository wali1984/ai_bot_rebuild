from pathlib import Path


def test_forbidden_tokens_not_present() -> None:
    source_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            Path("v2/backend/app/domain/paper_execution_ledger/__init__.py"),
            Path("v2/backend/app/domain/paper_execution_ledger/errors.py"),
            Path("v2/backend/app/domain/paper_execution_ledger/record.py"),
        )
    )
    forbidden_values = (
        "re" + "dis",
        "aio" + "redis",
        "hire" + "dis",
        "fast" + "api",
        "uvi" + "corn",
        "star" + "lette",
        "http" + "x",
        "requ" + "ests",
        "get" + "env",
        "env" + "iron",
        "sub" + "process",
        "sock" + "et",
        "log" + "ging",
        "time" + ".time",
        "time" + ".monotonic",
        "datetime" + ".now",
        "datetime" + ".utcnow",
        "Risk" + "Decision" + "Record",
        "Orchestrator" + "Decision" + "Record",
    )
    for value in forbidden_values:
        assert value not in source_text
