import subprocess
import sys


def test_init_module_does_not_register_fastapi_lifespan():
    forbidden = "fast" + "api"
    code = f"""
import sys
for name in list(sys.modules):
    if name.startswith({forbidden!r}) or name.startswith("v2.backend.app.composition.paper_mode"):
        del sys.modules[name]
import v2.backend.app.composition.paper_mode
bad = [name for name in sys.modules if name.startswith({forbidden!r})]
raise SystemExit(1 if bad else 0)
"""
    result = subprocess.run([sys.executable, "-c", code], check=False)

    assert result.returncode == 0
