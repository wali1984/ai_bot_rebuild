from pathlib import Path


def test_composition_milestone_forbidden_tokens():
    package_dir = Path(__file__).parents[4] / "app" / "composition" / "replay_backtest_runner"
    sources = (
        package_dir / "__init__.py",
        package_dir / "errors.py",
        package_dir / "runtime.py",
    )
    tokens = (
        "red" + "is",
        "Red" + "is",
        "RED" + "IS",
        "aio" + "red" + "is",
        "hi" + "red" + "is",
        "http" + "x",
        "req" + "uests",
        "url" + "_env",
        "URL" + "_ENV",
        "os." + "environ",
        "get" + "env",
        "sub" + "process",
        "so" + "cket",
        "select" + "ors",
        "time." + "time",
        "time." + "monotonic",
        "time." + "sleep",
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
        "Back" + "groundTasks",
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
        "RISK_DECISION_REASON_DENY" + "_DEFAULT",
        "deny" + "_default",
        "mirror" + "_deny" + "_default",
        "sql" + "ite",
        "sql" + "alchemy",
        "par" + "quet",
        "ReplayBacktest" + "Step(",
        "ReplayBacktest" + "Summary(",
        "PaperExecutionLedger" + "Entry(",
        "ReplayBacktest" + "Run(",
        "BEGIN" + "_FILE",
        "END" + "_FILE",
    )

    for source in sources:
        body = source.read_text(encoding="utf-8")
        for token in tokens:
            assert token not in body
