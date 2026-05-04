from __future__ import annotations

from pathlib import Path


def _tokens() -> tuple[str, ...]:
    return (
        "red" + "is",
        "aio" + "red" + "is",
        "red" + "is" + ".asyncio",
        "sub" + "process",
        "os" + ".system",
        "os" + ".popen",
        "p" + "ty",
        "so" + "cket",
        "url" + "lib",
        "req" + "uests",
        "ht" + "tpx",
        "aio" + "http",
        "num" + "py",
        "to" + "rch",
        "tensor" + "flow",
        "cu" + "da",
        "legacy" + "_reference",
        "/home/wali/Desktop/" + "AI BOT/",
        "BINANCE" + "_API_KEY",
        "BINANCE" + "_API_SECRET",
        "live" + "_trading_enabled = true",
        "X" + "LEN",
        "x" + "len",
        "time" + ".time(",
        "datetime" + ".now(",
        "datetime" + ".utcnow(",
    )


def test_delta_source_and_tests_do_not_contain_forbidden_tokens() -> None:
    roots = (
        Path("v2/backend/app/domain/trainer_liveness_composition"),
        Path("v2/backend/tests/unit/domain/trainer_liveness_composition"),
    )
    hits: list[tuple[str, str]] = []
    for root in roots:
        for path in root.rglob("*.py"):
            text = path.read_text()
            for token in _tokens():
                if token in text:
                    hits.append((str(path), token))

    assert hits == []
