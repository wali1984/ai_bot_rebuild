def test_service_forbidden_tokens() -> None:
    source_dir = "v2/backend/app/services/trainer_prediction_output"
    paths = (
        source_dir + "/__init__.py",
        source_dir + "/errors.py",
        source_dir + "/service.py",
    )
    tokens = (
        "red" + "is",
        "Red" + "is",
        "RED" + "IS",
        "aio" + "red" + "is",
        "hi" + "red" + "is",
        "htt" + "px",
        "requ" + "ests",
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
        "datetime" + ".now",
        "datetime" + ".utcnow",
        "date" + "time",
        "print" + "(",
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
        "asyn" + "cio",
        "eval" + "(",
        "exec" + "(",
        "compile" + "(",
        "pick" + "le",
        "mar" + "shal",
        "__" + "import__",
        "import" + "lib",
    )

    for token in tokens:
        matches = []
        for path in paths:
            with open(path) as handle:
                if token in handle.read():
                    matches.append(path)
        assert matches == []
