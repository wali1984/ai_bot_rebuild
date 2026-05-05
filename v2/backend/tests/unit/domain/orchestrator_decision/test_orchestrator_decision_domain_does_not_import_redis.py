import subprocess
import sys


def test_domain_import_does_not_load_forbidden_runtime_modules():
    forbidden = (
        "red" + "is",
        "red" + "is.asyncio",
        "aio" + "redis",
        "hire" + "dis",
        "ht" + "tpx",
        "requ" + "ests",
        "fast" + "api",
        "uvi" + "corn",
        "asyn" + "cio",
        "thread" + "ing",
        "v2.backend.app.adapters.red" + "is_v2.url_env",
    )
    code = (
        "import sys; "
        "import v2.backend.app.domain.orchestrator_decision; "
        f"forbidden = {forbidden!r}; "
        "loaded = [name for name in forbidden if name in sys.modules]; "
        "raise SystemExit(1 if loaded else 0)"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        check=False,
        cwd=".",
        text=True,
        capture_output=True,
    )
    assert completed.returncode == 0, completed.stderr
