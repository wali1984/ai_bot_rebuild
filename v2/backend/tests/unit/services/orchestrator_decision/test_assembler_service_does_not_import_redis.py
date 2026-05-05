import ast
import subprocess
import sys


def test_assembler_service_does_not_import_redis() -> None:
    code = """
import sys
import v2.backend.app.services.orchestrator_decision
names = [
    "red" + "is",
    "red" + "is.asyncio",
    "aio" + "redis",
    "hire" + "dis",
    "ht" + "tpx",
    "req" + "uests",
    "fast" + "api",
    "uvi" + "corn",
    "async" + "io",
    "thread" + "ing",
    "v2.backend.app.adapters.red" + "is_v2.url_env",
]
print([name for name in names if name in sys.modules])
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        check=True,
        capture_output=True,
        text=True,
    )

    assert ast.literal_eval(result.stdout.strip()) == []
