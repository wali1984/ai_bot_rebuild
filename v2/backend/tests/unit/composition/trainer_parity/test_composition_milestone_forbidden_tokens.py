from pathlib import Path


def test_composition_milestone_forbidden_tokens():
    root = Path(__file__).resolve().parents[4]
    source_files = (
        root / "app/composition/trainer_parity/__init__.py",
        root / "app/composition/trainer_parity/errors.py",
        root / "app/composition/trainer_parity/runtime.py",
    )
    test_dir = root / "tests/unit/composition/trainer_parity"
    test_files = tuple(
        item
        for item in sorted(test_dir.glob("test_*.py"))
        if item.name != "test_composition_milestone_forbidden_tokens.py"
    )
    scanned_files = source_files + test_files

    tokens = (
        "import " + "redis",
        "from " + "redis",
        "redis" + ".asyncio",
        "redis" + ".Redis(",
        "redis" + ".Redis" + ".from_url(",
        "aio" + "redis",
        "hire" + "dis",
        "time" + ".time(",
        "time" + ".monotonic(",
        "time" + ".perf_counter(",
        "time" + ".process_time(",
        "datetime" + ".now(",
        "datetime" + ".utcnow(",
        "datetime" + ".datetime.now(",
        "datetime" + ".datetime.utcnow(",
        "os" + ".environ",
        "os" + ".getenv(",
        "sub" + "process.",
        "sock" + "et.",
        "requests" + ".",
        "httpx" + ".",
        "aio" + "http.",
        "urllib" + ".request",
        "urllib" + ".parse",
        "open" + "(",
        "pathlib" + ".Path(",
        "read" + "_text",
        "read" + "_bytes",
        "print" + "(",
        "logger" + ".",
        "logging" + ".",
        "Fast" + "API",
        "Star" + "lette",
        "ASGI",
        "lifespan",
        "dependency",
        "router",
        "middleware",
        "background" + " task",
        "x" + "add",
        "x" + "del",
        "x" + "trim",
        "x" + "group_",
        "x" + "ack",
        "del" + "ete",
        "un" + "link",
        "flush" + "db",
        "flush" + "all",
        "script" + "_load",
        "eval" + "sha",
        "eval" + "(",
        "pub" + "sub",
        "publish" + "(",
        "connection" + "_pool",
        "from v2.backend.app.adapters." + "redis_v2." + "url" + "_env",
        "v2.backend.app.adapters." + "redis_v2." + "url" + "_env",
        "v2.backend.app.adapters." + "redis_v2." + "client",
        "v2.backend.app.adapters." + "redis_v2." + "streams",
        "v2.backend.app.adapters." + "redis_v2." + "retention",
        "v2.backend.app.adapters." + "redis_v2." + "stream" + "_latest" + "_id" + "_reader",
        "from v2.backend.app.adapters." + "redis_v2." + "factory",
    )
    factory_exemption = "from v2.backend.app.adapters." + "redis_v2." + "factory"
    runtime_path = root / "app/composition/trainer_parity/runtime.py"
    runtime_source = runtime_path.read_text(encoding="utf-8")
    assert runtime_source.count(factory_exemption) == 1

    for path in scanned_files:
        source = path.read_text(encoding="utf-8")
        assert path.exists()
        for token in tokens:
            if path == runtime_path and token == factory_exemption:
                continue
            assert source.count(token) == 0, (str(path), token)
