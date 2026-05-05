from pathlib import Path


def test_assembler_service_forbidden_tokens() -> None:
    base = Path("v2/backend/app/services/orchestrator_decision")
    tokens = (
        "red" + "is",
        "Red" + "is",
        "aio" + "redis",
        "hire" + "dis",
        "ht" + "tpx",
        "req" + "uests",
        "fast" + "api",
        "Fast" + "API",
        "uvi" + "corn",
        "sub" + "process",
        "so" + "cket",
        "os" + ".environ",
        "os" + ".getenv",
        "time" + ".time",
        "time" + ".monotonic",
        "datetime" + ".now",
        "datetime" + ".utcnow",
        "log" + "ging",
        "pri" + "nt(",
        "url" + "_env",
        "gamma" + ".real",
    )
    text = "\n".join(
        (base / name).read_text(encoding="utf-8")
        for name in ("__init__.py", "errors.py", "service.py")
    )

    assert {token for token in tokens if token in text} == set()
