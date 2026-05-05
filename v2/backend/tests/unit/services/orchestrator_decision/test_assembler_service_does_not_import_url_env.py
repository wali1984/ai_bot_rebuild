import subprocess
import sys


def test_assembler_service_does_not_import_url_env() -> None:
    code = """
import sys
import v2.backend.app.services.orchestrator_decision
name = "v2.backend.app.adapters.red" + "is_v2." + "url" + "_env"
raise SystemExit(1 if name in sys.modules else 0)
"""
    result = subprocess.run([sys.executable, "-c", code])

    assert result.returncode == 0
