import subprocess
import sys


def test_runtime_module_does_not_load_redis_when_imported() -> None:
    code = """
import sys
literal = "red" + "is"
target = "v2.backend.app.composition.trainer_prediction_output.runtime"
for name in list(sys.modules):
    if name.startswith(literal) or name == target:
        sys.modules.pop(name)
import v2.backend.app.composition.trainer_prediction_output.runtime
loaded = [name for name in sys.modules if name.startswith(literal)]
raise SystemExit(1 if loaded else 0)
"""
    result = subprocess.run([sys.executable, "-c", code])
    assert result.returncode == 0
