from pathlib import Path


def _tokens() -> list[str]:
    return [
        "im" + "port aio" + "red" + "is",
        "fr" + "om aio" + "red" + "is",
        "red" + "is.asyncio",
        "im" + "port hi" + "red" + "is",
        "fr" + "om hi" + "red" + "is",
        "im" + "port sub" + "process",
        "fr" + "om sub" + "process",
        "im" + "port so" + "cket",
        "fr" + "om so" + "cket",
        "im" + "port url" + "lib",
        "fr" + "om url" + "lib",
        "im" + "port req" + "uests",
        "fr" + "om req" + "uests",
        "im" + "port ht" + "tpx",
        "fr" + "om ht" + "tpx",
        "im" + "port aio" + "http",
        "fr" + "om aio" + "http",
        "im" + "port num" + "py",
        "fr" + "om num" + "py",
        "im" + "port tor" + "ch",
        "fr" + "om tor" + "ch",
        "im" + "port tensor" + "flow",
        "fr" + "om tensor" + "flow",
        "time" + ".time(",
        "datetime" + ".now(",
        "datetime" + ".utcnow(",
        "legacy" + "_reference",
        "/" + "home/wali/Desktop/AI" + " BOT",
        "BINANCE" + "_API_KEY",
        "BINANCE" + "_API_SECRET",
        "live" + "_trading_enabled = true",
        "live" + "_trading_enabled=true",
        "x" + "add",
        "x" + "del",
        "x" + "trim",
        "x" + "group",
        "x" + "ack",
        "." + "set(",
        "." + "h" + "set(",
        "." + "l" + "push(",
        "." + "r" + "push(",
        "." + "s" + "add(",
        "." + "z" + "add(",
        "d" + "e" + "l" + "e" + "t" + "e",
        "un" + "link",
        "flush" + "db",
        "flush" + "all",
        "ex" + "pire",
        "p" + "ex" + "pire",
        "script" + "_load",
        "eval" + "sha",
        "config" + "_set",
        "config" + "_get",
        "pub" + "sub",
        "pub" + "lish",
        "." + "ping(",
        "." + "execute" + "_command(",
        "connection" + "_pool.get" + "_connection(",
    ]


def _factory_only_tokens() -> list[str]:
    return [
        "im" + "port " + "red" + "is",
        "fr" + "om " + "red" + "is",
        "red" + "is.Redis.from" + "_url(",
    ]


def test_factory_milestone_forbidden_tokens() -> None:
    root = Path(__file__).parents[4]
    source_paths = [
        root / "app/adapters/redis_v2/url_env.py",
        root / "app/adapters/redis_v2/factory.py",
    ]
    test_paths = sorted(
        path
        for path in (root / "tests/unit/adapters/redis_v2").glob("test_*.py")
        if path.name.startswith(("test_url_env_", "test_factory_"))
        or path.name
        in {
            "test_init_module_unchanged_by_factory_milestone.py",
            "test_init_module_does_not_load_redis_when_imported.py",
        }
    )
    contents = {
        path: path.read_text(encoding="utf-8") for path in source_paths + test_paths
    }

    for token in _tokens():
        for path, content in contents.items():
            assert token not in content, f"{token!r} found in {path}"

    factory_path = root / "app/adapters/redis_v2/factory.py"
    non_factory = {
        path: content for path, content in contents.items() if path != factory_path
    }
    for token in _factory_only_tokens():
        for path, content in non_factory.items():
            assert token not in content, f"{token!r} found in {path}"
