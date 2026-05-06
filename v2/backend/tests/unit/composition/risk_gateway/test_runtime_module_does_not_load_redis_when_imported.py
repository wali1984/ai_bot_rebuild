import subprocess
import sys


def test_runtime_module_does_not_load_redis_when_imported():
    code = """
import sys
name = "red" + "is"
for key in list(sys.modules):
    if key.startswith(name) or key == "v2.backend.app.composition.risk_gateway.runtime":
        del sys.modules[key]
import v2.backend.app.composition.risk_gateway.runtime
assert not any(key.startswith(name) for key in sys.modules)
"""
    result = subprocess.run([sys.executable, "-c", code], check=False)

    assert result.returncode == 0
