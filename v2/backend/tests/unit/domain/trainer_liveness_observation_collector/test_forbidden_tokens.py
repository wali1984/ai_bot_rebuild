from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
SOURCE_ROOT = ROOT / "app" / "domain" / "trainer_liveness_observation_collector"
TEST_ROOT = ROOT / "tests" / "unit" / "domain" / "trainer_liveness_observation_collector"

FORBIDDEN_TOKENS = (
    "re" + "dis",
    "aio" + "re" + "dis",
    "re" + "dis" + "." + "asyncio",
    "sub" + "process",
    "os" + "." + "system",
    "os" + "." + "popen",
    "p" + "ty",
    "sock" + "et",
    "url" + "lib",
    "re" + "quests",
    "ht" + "tpx",
    "aio" + "ht" + "tp",
    "num" + "py",
    "tor" + "ch",
    "tensor" + "flow",
    "cu" + "da",
    "legacy" + "_reference",
    "/" + "home" + "/" + "wali" + "/" + "Desktop" + "/" + "AI BOT" + "/",
    "BINANCE" + "_API_KEY",
    "BINANCE" + "_API_SECRET",
    "live" + "_trading_enabled = true",
    "X" + "LEN",
    "x" + "len",
    "time" + "." + "time(",
    "time" + "." + "monotonic(",
    "datetime" + "." + "now(",
    "datetime" + "." + "utcnow(",
)


def test_gamma_source_and_tests_do_not_contain_forbidden_tokens() -> None:
    failures: list[tuple[str, str]] = []

    for root in (SOURCE_ROOT, TEST_ROOT):
        for path in root.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for token in FORBIDDEN_TOKENS:
                if token in text:
                    failures.append((str(path.relative_to(ROOT)), token))

    assert failures == []
