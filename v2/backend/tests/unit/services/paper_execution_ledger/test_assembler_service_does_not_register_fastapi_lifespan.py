import subprocess
import sys


def test_assembler_service_does_not_register_fastapi_lifespan() -> None:
    code = """
import sys
import v2.backend.app.services.paper_execution_ledger as package
print("fastapi" in sys.modules)
print(callable(getattr(package, "lifespan", None)))
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert result.stdout.splitlines() == ["False", "False"]
