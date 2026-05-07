import subprocess
import sys


def test_init_module_does_not_load_url_env():
    target = "url" + "_env"
    code = """
import sys
target = "url" + "_env"
for name in list(sys.modules):
    if target in name or name.startswith("v2.backend.app.composition.shadow_mode_readiness"):
        del sys.modules[name]
import v2.backend.app.composition.shadow_mode_readiness
assert not any(target in name for name in sys.modules)
"""
    result = subprocess.run([sys.executable, "-c", code], check=False)
    assert result.returncode == 0
    assert target == "url_env"
