import subprocess
import sys


def test_assembler_service_does_not_import_url_env() -> None:
    code = """
import sys
import v2.backend.app.services.shadow_mode_readiness
raise SystemExit(1 if "v2.backend.app.adapters.redis_v2.url_env" in sys.modules else 0)
"""
    completed = subprocess.run([sys.executable, "-c", code])
    assert completed.returncode == 0
