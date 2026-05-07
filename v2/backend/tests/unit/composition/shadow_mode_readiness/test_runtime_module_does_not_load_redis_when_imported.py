import subprocess
import sys


def test_runtime_module_does_not_load_redis_when_imported():
    target = "red" + "is"
    code = """
import sys
target = "red" + "is"
for name in list(sys.modules):
    if name.startswith(target) or name.startswith("v2.backend.app.composition.shadow_mode_readiness.runtime"):
        del sys.modules[name]
import v2.backend.app.composition.shadow_mode_readiness.runtime
assert not any(name.startswith(target) for name in sys.modules)
"""
    result = subprocess.run([sys.executable, "-c", code], check=False)
    assert result.returncode == 0
    assert target == "redis"
