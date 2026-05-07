from pathlib import Path


def test_assembler_service_forbidden_tokens() -> None:
    source_dir = Path("v2/backend/app/services/paper_mode")
    source_text = "\n".join(
        (source_dir / name).read_text()
        for name in ("__init__.py", "errors.py", "service.py")
    )
    tokens = (
        "red" + "is",
        "Red" + "is",
        "RED" + "IS",
        "aio" + "redis",
        "hire" + "dis",
        "http" + "x",
        "request" + "s",
        "fast" + "api",
        "Fast" + "API",
        "uvi" + "corn",
        "star" + "lette",
        "url" + "lib",
        "sub" + "process",
        "sock" + "et",
        "os.en" + "viron",
        "os.get" + "env",
        "time." + "time",
        "time." + "monotonic",
        "time." + "sleep",
        "datetime." + "now",
        "datetime." + "utcnow",
        "date" + "time",
        "log" + "ging",
        "print" + "(",
        "url" + "_env",
        "URL" + "_ENV",
        "gamma." + "real",
        "PaperExecution" + "LedgerEntry",
        "RiskDecision" + "Record",
        "OrchestratorDecision" + "Record",
        "ReplayBacktest" + "Run",
        "ReplayBacktest" + "Step",
        "ReplayBacktest" + "Summary",
        "live" + "_enabled",
        "LIVE" + "_ENABLED",
        "PAPER_MODE_LIVE" + "_ENABLED",
        "sql" + "ite",
        "sql" + "alchemy",
        "par" + "quet",
        "BEGIN" + "_FILE",
        "END" + "_FILE",
    )
    for token in tokens:
        assert token not in source_text

    prefix = "PAPER_MODE_LIVE" + "_"
    allowed = "PAPER_MODE_LIVE" + "_BLOCKED"
    normalized = source_text
    for char in "(),{}:":
        normalized = normalized.replace(char, " ")
    prefixed_values = {part for part in normalized.split() if part.startswith(prefix)}
    assert prefixed_values == {allowed}
