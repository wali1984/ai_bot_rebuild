from pathlib import Path


def test_assembler_service_forbidden_tokens():
    root = Path("v2/backend/app/services/replay_backtest_runner")
    text = "\n".join((root / name).read_text() for name in ("__init__.py", "errors.py", "service.py"))
    tokens = [
        "re" + "dis",
        "Re" + "dis",
        "RE" + "DIS",
        "aio" + "redis",
        "hi" + "redis",
        "ht" + "tpx",
        "req" + "uests",
        "fast" + "api",
        "Fast" + "API",
        "uvi" + "corn",
        "star" + "lette",
        "url" + "lib",
        "sub" + "process",
        "sock" + "et",
        "os." + "environ",
        "os." + "getenv",
        "time." + "time",
        "time." + "monotonic",
        "time." + "sleep",
        "date" + "time.now",
        "date" + "time.utcnow",
        "date" + "time",
        "log" + "ging",
        "pri" + "nt(",
        "url_" + "env",
        "URL_" + "ENV",
        "gamma." + "real",
        "Risk" + "DecisionRecord",
        "Orchestrator" + "DecisionRecord",
        "sql" + "ite",
        "sql" + "alchemy",
        "par" + "quet",
        "BEGIN" + "_FILE",
        "END" + "_FILE",
    ]

    for token in tokens:
        assert token not in text
