import subprocess
import sys


def test_init_module_does_not_load_url_env():
    forbidden = "url" + "_env"
    code = f"""
import sys
for name in list(sys.modules):
    if {forbidden!r} in name or name.startswith("v2.backend.app.composition.paper_mode"):
        del sys.modules[name]
import v2.backend.app.composition.paper_mode
bad = [name for name in sys.modules if {forbidden!r} in name]
raise SystemExit(1 if bad else 0)
"""
    result = subprocess.run([sys.executable, "-c", code], check=False)

    assert result.returncode == 0
