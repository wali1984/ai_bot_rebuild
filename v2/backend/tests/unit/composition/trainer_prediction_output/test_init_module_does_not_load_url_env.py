import subprocess
import sys


def test_init_module_does_not_load_url_env() -> None:
    code = """
import sys
literal = "url" + "_env"
blocked = "v2.backend.app.adapters." + "red" + "is_v2." + literal
prefix = "v2.backend.app.composition.trainer_prediction_output"
for name in list(sys.modules):
    if name.startswith(blocked) or name.startswith(prefix):
        sys.modules.pop(name)
import v2.backend.app.composition.trainer_prediction_output
loaded = [name for name in sys.modules if literal in name]
raise SystemExit(1 if loaded else 0)
"""
    result = subprocess.run([sys.executable, "-c", code])
    assert result.returncode == 0
