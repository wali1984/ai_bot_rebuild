import subprocess
import sys


def test_assembler_service_does_not_import_url_env() -> None:
    code = """
import sys
import v2.backend.app.services.risk_gateway
print("v2.backend.app.adapters.redis_v2.url_env" in sys.modules)
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == "False"
