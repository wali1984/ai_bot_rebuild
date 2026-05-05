import subprocess
import sys


def test_init_module_does_not_load_redis() -> None:
    code = """
import sys
literal = "red" + "is"
prefix = "v2.backend.app.composition.orchestrator_decision"
for name in list(sys.modules):
    if name.startswith(literal) or name.startswith(prefix):
        sys.modules.pop(name)
import v2.backend.app.composition.orchestrator_decision
loaded = [name for name in sys.modules if name.startswith(literal)]
raise SystemExit(1 if loaded else 0)
"""
    result = subprocess.run([sys.executable, "-c", code])
    assert result.returncode == 0
