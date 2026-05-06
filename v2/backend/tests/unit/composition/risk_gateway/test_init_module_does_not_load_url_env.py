import subprocess
import sys


def test_init_module_does_not_load_url_env():
    code = """
import sys
name = "url" + "_env"
adapter = "v2.backend.app.adapters." + "red" + "is_v2." + name
for key in list(sys.modules):
    if key.startswith(adapter) or key.startswith("v2.backend.app.composition.risk_gateway"):
        del sys.modules[key]
import v2.backend.app.composition.risk_gateway
assert not any(name in key for key in sys.modules)
"""
    result = subprocess.run([sys.executable, "-c", code], check=False)

    assert result.returncode == 0
