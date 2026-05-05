from pathlib import Path


def test_authored_source_files_do_not_contain_blocked_literal_tokens() -> None:
    root = Path("v2/backend/app/domain/risk_gateway")
    tokens = (
        "re" + "dis",
        "Re" + "dis",
        "RE" + "DIS",
        "aiore" + "dis",
        "hire" + "dis",
        "http" + "x",
        "req" + "uests",
        "fast" + "api",
        "Fast" + "API",
        "uvi" + "corn",
        "sub" + "process",
        "so" + "cket",
        "os." + "environ",
        "os." + "getenv",
        "time." + "time",
        "time." + "monotonic",
        "time." + "sleep",
        "date" + "time.now",
        "date" + "time.utcnow",
        "date" + "time",
        "log" + "ging",
        "pri" + "nt(",
        "url" + "_env",
        "URL" + "_ENV",
        "gamma." + "real",
        "BEGIN" + "_FILE",
        "END" + "_FILE",
    )
    for relative in ("__init__.py", "errors.py", "record.py"):
        contents = (root / relative).read_text()
        for token in tokens:
            assert token not in contents, (relative, token)
