import subprocess
import sys


def test_assembler_service_does_not_register_fastapi_lifespan() -> None:
    code = """
import sys
import v2.backend.app.services.shadow_mode_readiness as package
blocked = any(name in sys.modules for name in ("fastapi", "uvicorn", "starlette"))
raise SystemExit(1 if blocked or callable(getattr(package, "lifespan", None)) else 0)
"""
    completed = subprocess.run([sys.executable, "-c", code])
    assert completed.returncode == 0
