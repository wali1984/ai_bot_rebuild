from pathlib import Path


def test_assembler_service_forbidden_tokens() -> None:
    root = Path("v2/backend/app/services/risk_gateway")
    files = (root / "__init__.py", root / "errors.py", root / "service.py")
    tokens = (
        "red" + "is",
        "Red" + "is",
        "RED" + "IS",
        "aio" + "redis",
        "hi" + "redis",
        "htt" + "px",
        "requ" + "ests",
        "fast" + "api",
        "Fast" + "API",
        "uvi" + "corn",
        "sub" + "process",
        "soc" + "ket",
        "os." + "environ",
        "os." + "getenv",
        "time." + "time",
        "time." + "monotonic",
        "time." + "sleep",
        "datetime." + "now",
        "datetime." + "utcnow",
        "date" + "time",
        "log" + "ging",
        "pri" + "nt(",
        "url" + "_env",
        "URL" + "_ENV",
        "gamma." + "real",
        "RISK_DECISION_REASON_DENY" + "_DEFAULT",
        "deny" + "_default",
        "BEGIN" + "_FILE",
        "END" + "_FILE",
    )
    for file_path in files:
        text = file_path.read_text()
        for token in tokens:
            assert token not in text
