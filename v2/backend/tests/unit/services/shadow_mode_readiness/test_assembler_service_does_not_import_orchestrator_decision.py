import subprocess
import sys


def test_assembler_service_does_not_import_orchestrator_decision() -> None:
    code = """
import sys
import v2.backend.app.services.shadow_mode_readiness
raise SystemExit(1 if "v2.backend.app.domain.orchestrator_decision" in sys.modules else 0)
"""
    completed = subprocess.run([sys.executable, "-c", code])
    assert completed.returncode == 0
