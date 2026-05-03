from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
SOURCE_TREE = ROOT / "app" / "domain" / "liveness_stream_growth"
TEST_TREE = ROOT / "tests" / "unit" / "domain" / "liveness_stream_growth"


def _tokens() -> tuple[str, ...]:
    return (
        "import " + "redis",
        "from " + "redis",
        "aio" + "redis",
        "sub" + "process",
        "os." + "system",
        "os." + "popen",
        "sock" + "et",
        "req" + "uests",
        "ht" + "tpx",
        "url" + "lib",
        "legacy" + "_reference",
        "/home/wali/Desktop/AI" + " BOT/",
        "BINANCE" + "_API_KEY",
        "BINANCE" + "_API_SECRET",
        "time." + "time(",
        "datetime." + "now(",
        "datetime." + "utcnow(",
        "num" + "py",
        "tor" + "ch",
        "tensor" + "flow",
        "X" + "LEN",
        "x" + "len",
        "async" + "io",
        "async " + "def",
        "from " + ".".join(("v2", "backend", "app", "domain", "trainer_liveness")),
    )


def _iter_python_files() -> tuple[Path, ...]:
    return tuple(sorted(SOURCE_TREE.glob("*.py"))) + tuple(sorted(TEST_TREE.glob("*.py")))


def test_forbidden_token_counts_are_zero() -> None:
    counts = {token: 0 for token in _tokens()}
    for path in _iter_python_files():
        text = path.read_text(encoding="utf-8")
        for token in counts:
            counts[token] += text.count(token)
    assert counts == {token: 0 for token in _tokens()}
