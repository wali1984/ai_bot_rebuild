import subprocess
import sys


def test_init_module_does_not_load_url_env() -> None:
    module_prefix = "v2.backend.app.services.trainer_prediction_output"
    blocked_module = "v2.backend.app.adapters." + "red" + "is_v2." + "url" + "_env"
    blocked = "url" + "_env"
    code = (
        "import sys\n"
        f"module_prefix = {module_prefix!r}\n"
        f"blocked_module = {blocked_module!r}\n"
        f"blocked = {blocked!r}\n"
        "for name in list(sys.modules):\n"
        "    if name.startswith(blocked_module) or name.startswith(module_prefix):\n"
        "        del sys.modules[name]\n"
        "import v2.backend.app.services.trainer_prediction_output\n"
        "matches = [name for name in sys.modules if blocked in name]\n"
        "raise SystemExit(1 if matches else 0)\n"
    )

    result = subprocess.run([sys.executable, "-c", code], check=False)

    assert result.returncode == 0
