from pathlib import Path


def test_assembler_service_forbidden_tokens() -> None:
    root = Path("v2/backend/app/services/paper_execution_ledger")
    paths = (root / "__init__.py", root / "errors.py", root / "service.py")
    values = (
        "re" + "dis",
        "Re" + "dis",
        "RE" + "DIS",
        "aio" + "re" + "dis",
        "hire" + "dis",
        "http" + "x",
        "requ" + "ests",
        "fast" + "api",
        "Fast" + "API",
        "uvi" + "corn",
        "sub" + "process",
        "sock" + "et",
        "os" + ".environ",
        "os" + ".getenv",
        "time" + ".time",
        "time" + ".monotonic",
        "time" + ".sleep",
        "datetime" + ".now",
        "datetime" + ".utcnow",
        "date" + "time",
        "log" + "ging",
        "print" + "(",
        "url" + "_env",
        "URL" + "_ENV",
        "gamma" + ".real",
        "Orchestrator" + "Decision" + "Record",
        "BEGIN" + "_FILE",
        "END" + "_FILE",
    )

    for path in paths:
        content = path.read_text(encoding="utf-8")
        for value in values:
            assert value not in content
