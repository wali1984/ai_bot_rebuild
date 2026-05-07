from pathlib import Path


def test_composition_milestone_forbidden_tokens():
    root = Path("v2/backend/app/composition/paper_mode")
    source = "\n".join(
        (root / filename).read_text()
        for filename in ("__init__.py", "errors.py", "runtime.py")
    )
    forbidden = [
        "red" + "is",
        "Redis",
        "REDIS",
        "aio" + "redis",
        "hi" + "redis",
        "http" + "x",
        "request" + "s",
        "url" + "_env",
        "URL" + "_ENV",
        "os.environ",
        "get" + "env",
        "sub" + "process",
        "sock" + "et",
        "selectors",
        "path" + "lib",
        "time.time",
        "time.monotonic",
        "time.sleep",
        "date" + "time.now",
        "date" + "time.utcnow",
        "date" + "time",
        "print(",
        "logging.",
        "logging",
        "Fast" + "API",
        "fast" + "api",
        "API" + "Router",
        "life" + "span",
        "Depends",
        "Background" + "Tasks",
        "lru" + "_cache",
        "cached" + "_property",
        "thread" + "ing",
        "multi" + "processing",
        "async" + "io",
        "eval(",
        "exec(",
        "compile(",
        "pick" + "le",
        "marshal",
        "__" + "import__",
        "import" + "lib",
        "Risk" + "Decision" + "Record",
        "Orchestrator" + "Decision" + "Record",
        "RISK" + "_DECISION" + "_REASON" + "_DENY" + "_DEFAULT",
        "deny" + "_default",
        "mirror" + "_deny" + "_default",
        "Paper" + "Execution" + "Ledger" + "Entry",
        "Replay" + "Backtest" + "Step",
        "Replay" + "Backtest" + "Summary",
        "Replay" + "Backtest" + "Run",
        "sqlite",
        "sql" + "alchemy",
        "par" + "quet",
        "PaperModeFlag" + "(",
        "BEGIN" + "_FILE",
        "END" + "_FILE",
    ]

    for token in forbidden:
        assert token not in source
