import subprocess
import sys


def test_assembler_service_does_not_register_fastapi_lifespan() -> None:
    code = """
import sys
import v2.backend.app.services.orchestrator_decision as module
bad = "fast" + "api" in sys.modules or callable(getattr(module, "lifespan", None))
raise SystemExit(1 if bad else 0)
"""
    result = subprocess.run([sys.executable, "-c", code])

    assert result.returncode == 0
