import subprocess
import sys


def test_assembler_service_does_not_import_replay_placeholder() -> None:
    code = """
import sys
import v2.backend.app.services.shadow_mode_readiness
raise SystemExit(1 if "v2.backend.app.domain.replay" in sys.modules else 0)
"""
    completed = subprocess.run([sys.executable, "-c", code])
    assert completed.returncode == 0
