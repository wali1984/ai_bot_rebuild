from pathlib import Path


def test_composition_milestone_forbidden_tokens() -> None:
    root = Path("v2/backend/app/composition/orchestrator_decision")
    source = b"".join(
        (root / name).read_bytes() for name in ("__init__.py", "errors.py", "runtime.py")
    )
    tokens = (
        "red" + "is",
        "Red" + "is",
        "RED" + "IS",
        "aio" + "red" + "is",
        "hi" + "red" + "is",
        "ht" + "tpx",
        "requ" + "ests",
        "url" + "_env",
        "URL" + "_ENV",
        "os.en" + "viron",
        "get" + "env",
        "sub" + "process",
        "so" + "cket",
        "select" + "ors",
        "path" + "lib",
        "time." + "time",
        "time." + "monotonic",
        "time." + "sleep",
        "datetime." + "now",
        "datetime." + "utcnow",
        "date" + "time",
        "pri" + "nt(",
        "logging" + ".",
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
        "ev" + "al(",
        "ex" + "ec(",
        "comp" + "ile(",
        "pick" + "le",
        "mar" + "shal",
        "__im" + "port__",
        "import" + "lib",
    )
    for token in tokens:
        assert token.encode() not in source
