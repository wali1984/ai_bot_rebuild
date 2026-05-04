from pathlib import Path


def _tokens() -> list[str]:
    return [
        "im" + "port " + "red" + "is",
        "fr" + "om " + "red" + "is",
        "im" + "port aio" + "red" + "is",
        "fr" + "om aio" + "red" + "is",
        "red" + "is" + ".asyncio",
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
        "d" + "e" + "l" + "e" + "t" + "e",
        "un" + "link",
        "flush" + "db",
        "flush" + "all",
        "l" + "push",
        "r" + "push",
        "s" + "add",
        "z" + "add",
        "ex" + "pire",
        "p" + "ex" + "pire",
        "script" + "_load",
        "eval" + "sha",
        "config" + "_set",
        "config" + "_get",
        "pub" + "sub",
        "pub" + "lish",
        "." + "set(",
        "." + "h" + "set(",
        "." + "l" + "push(",
        "." + "r" + "push(",
        "." + "s" + "add(",
        "." + "z" + "add(",
        "." + "script" + "_load(",
        "." + "eval" + "sha(",
        "." + "config" + "_set(",
        "." + "config" + "_get(",
        "." + "pub" + "sub(",
        "." + "pub" + "lish(",
        "red" + "is_client" + "." + "set",
        "red" + "is_client" + "." + "h" + "set",
    ]


def test_forbidden_tokens() -> None:
    root = Path(__file__).parents[4]
    paths = [
        root / "app/adapters/redis_v2/__init__.py",
        root / "app/adapters/redis_v2/errors.py",
        root / "app/adapters/redis_v2/stream_latest_id_reader.py",
    ]
    paths.extend((root / "tests/unit/adapters/redis_v2").glob("*.py"))

    contents = {path: path.read_text(encoding="utf-8") for path in paths}
    for token in _tokens():
        for path, content in contents.items():
            assert token not in content, f"{token!r} found in {path}"
