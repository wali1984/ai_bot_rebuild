import subprocess
import sys


def test_init_module_does_not_load_redis():
    code = """
import sys
name = "red" + "is"
for key in list(sys.modules):
    if key.startswith(name) or key.startswith("v2.backend.app.composition.risk_gateway"):
        del sys.modules[key]
import v2.backend.app.composition.risk_gateway
assert not any(key.startswith(name) for key in sys.modules)
"""
    result = subprocess.run([sys.executable, "-c", code], check=False)

    assert result.returncode == 0
