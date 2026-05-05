from pathlib import Path


def test_domain_source_files_do_not_contain_forbidden_tokens():
    forbidden = (
        "red" + "is",
        "Red" + "is",
        "aio" + "redis",
        "hire" + "dis",
        "ht" + "tpx",
        "requ" + "ests",
        "fast" + "api",
        "Fast" + "API",
        "uvi" + "corn",
        "sub" + "process",
        "sock" + "et",
        "os.en" + "viron",
        "os.get" + "env",
        "time." + "time",
        "time." + "monotonic",
        "datetime." + "now",
        "datetime." + "utcnow",
        "log" + "ging",
        "pri" + "nt(",
        "url" + "_env",
        "gamma." + "real",
        "BEGIN" + "_FILE",
        "END" + "_FILE",
    )
    source_files = (
        Path("v2/backend/app/domain/orchestrator_decision/__init__.py"),
        Path("v2/backend/app/domain/orchestrator_decision/errors.py"),
        Path("v2/backend/app/domain/orchestrator_decision/record.py"),
    )
    for source_file in source_files:
        content = source_file.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in content, (source_file, token)
