from pathlib import Path


def test_composition_milestone_forbidden_tokens():
    root = Path("v2/backend/app/composition/trainer_worker_health")
    test_root = Path("v2/backend/tests/unit/composition/trainer_worker_health")
    red = "red" + "is"
    tokens = (
        red,
        "Red" + "is",
        "RED" + "IS",
        "ai" + "o" + red,
        "hi" + red,
        "http" + "x",
        "re" + "quests",
        "url" + "_" + "env",
        "URL" + "_" + "ENV",
        "os" + "." + "environ",
        "get" + "env",
        "sub" + "process",
        "sock" + "et",
        "time" + "." + "time",
        "time" + "." + "monotonic",
        "time" + "." + "perf_counter",
        "time" + "." + "process_time",
        "datetime" + "." + "now",
        "datetime" + "." + "utcnow",
        "print" + "(",
        "logging" + ".",
        "logger" + ".",
        "Fast" + "API",
        "API" + "Router",
        "life" + "span",
        "De" + "pends",
        "Background" + "Tasks",
        "lru" + "_" + "cache",
        "cached" + "_" + "property",
        "threading" + "." + "Lock",
        "x" + "add",
        "x" + "del",
        "x" + "trim",
        "x" + "group_",
        "x" + "ack",
        "flush" + "db",
        "flush" + "all",
        "script" + "_" + "load",
        "eval" + "sha",
        "pub" + "sub",
        "publish" + "(",
        "connection" + "_" + "pool",
        red + "." + "Red" + "is" + "(",
        red + "." + "Red" + "is.from_url" + "(",
        "import " + red,
        "from " + red,
        "urllib" + "." + "request",
        "urllib" + "." + "parse",
        "aio" + "http" + ".",
        "factory" + "." + "make_real_" + red + "_stream_latest_id_reader",
        "make_real_" + red + "_stream_latest_id_reader",
    )
    files = sorted(root.glob("*.py"))
    files.extend(path for path in sorted(test_root.glob("*.py")) if path.name != Path(__file__).name)
    for path in files:
        text = path.read_text()
        for token in tokens:
            assert token not in text, (path, token)
