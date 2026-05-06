import subprocess
import sys


def test_assembler_service_does_not_register_fastapi_lifespan() -> None:
    code = """
import sys
import v2.backend.app.services.risk_gateway as service
print(("fastapi" in sys.modules, hasattr(service, "lifespan")))
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == "(False, False)"
