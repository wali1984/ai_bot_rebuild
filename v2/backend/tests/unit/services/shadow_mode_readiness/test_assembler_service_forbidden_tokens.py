from pathlib import Path


def test_assembler_service_forbidden_tokens() -> None:
    root = Path("v2/backend/app/services/shadow_mode_readiness")
    text = "\n".join(
        (root / name).read_text(encoding="utf-8")
        for name in ("__init__.py", "errors.py", "service.py")
    )
    prefix = "SHADOW_MODE_"
    tokens = [
        "re" + "dis",
        "Re" + "dis",
        "RE" + "DIS",
        "aio" + "re" + "dis",
        "hire" + "dis",
        "http" + "x",
        "re" + "quests",
        "fast" + "api",
        "Fast" + "API",
        "uvi" + "corn",
        "star" + "lette",
        "url" + "lib",
        "sub" + "process",
        "so" + "cket",
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
        "url" + "_env",
        "URL" + "_ENV",
        "gamma." + "real",
        "Paper" + "ModeFlag",
        "Paper" + "ExecutionLedgerEntry",
        "Risk" + "DecisionRecord",
        "Orchestrator" + "DecisionRecord",
        "Replay" + "BacktestRun",
        "Replay" + "BacktestStep",
        "Replay" + "BacktestSummary",
        "live" + "_enabled",
        "LIVE" + "_ENABLED",
        prefix + "LIVE_" + "ENABLED",
        "shadow" + "_decision_id",
        "sql" + "ite",
        "sql" + "alchemy",
        "par" + "quet",
        "BEGIN" + "_FILE",
        "END" + "_FILE",
        prefix + "LIVE",
    ]
    for token in tokens:
        assert token not in text
    assert prefix + "LIVE" not in text
    assert prefix + "LIVE_" + "ENABLED" not in text
