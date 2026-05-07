from pathlib import Path


def test_composition_milestone_forbidden_tokens():
    root = Path("v2/backend/app/composition/shadow_mode_readiness")
    sources = {
        path.name: path.read_text(encoding="utf-8")
        for path in (root / "__init__.py", root / "errors.py", root / "runtime.py")
    }
    tokens = (
        "red" + "is",
        "Red" + "is",
        "RED" + "IS",
        "aio" + "redis",
        "hire" + "dis",
        "http" + "x",
        "re" + "quests",
        "url" + "_env",
        "URL" + "_ENV",
        "os." + "environ",
        "get" + "env",
        "sub" + "process",
        "sock" + "et",
        "select" + "ors",
        "path" + "lib",
        "time" + ".time",
        "time" + ".monotonic",
        "time" + ".sleep",
        "date" + "time.now",
        "date" + "time.utcnow",
        "date" + "time",
        "print" + "(",
        "log" + "ging.",
        "log" + "ging",
        "Fast" + "API",
        "fast" + "api",
        "API" + "Router",
        "life" + "span",
        "Dep" + "ends",
        "Background" + "Tasks",
        "lru" + "_cache",
        "cached" + "_property",
        "thread" + "ing",
        "multi" + "processing",
        "async" + "io",
        "eval" + "(",
        "exec" + "(",
        "compile" + "(",
        "pick" + "le",
        "mar" + "shal",
        "__" + "import__",
        "import" + "lib",
        "Risk" + "DecisionRecord",
        "Orchestrator" + "DecisionRecord",
        "RISK" + "_DECISION_REASON_DENY_DEFAULT",
        "deny" + "_default",
        "mirror" + "_deny_default",
        "Paper" + "ExecutionLedgerEntry",
        "Replay" + "BacktestStep",
        "Replay" + "BacktestSummary",
        "Replay" + "BacktestRun",
        "Paper" + "ModeFlag",
        "sql" + "ite",
        "sql" + "alchemy",
        "par" + "quet",
        "ShadowModeReadinessFlag" + "(",
        "SHADOW" + "_MODE_LIVE",
        "SHADOW" + "_MODE_LIVE_ENABLED",
        "live" + "_enabled",
        "enable" + "_live",
        "shadow" + "_decision_id",
        "BEGIN" + "_FILE",
        "END" + "_FILE",
    )

    for name, source in sources.items():
        for token in tokens:
            assert token not in source, (name, token)
