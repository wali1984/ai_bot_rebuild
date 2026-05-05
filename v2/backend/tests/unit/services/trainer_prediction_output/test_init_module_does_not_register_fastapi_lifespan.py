import subprocess
import sys


def test_init_module_does_not_register_fastapi_lifespan() -> None:
    module_prefix = "v2.backend.app.services.trainer_prediction_output"
    blocked = "fast" + "api"
    code = (
        "import sys\n"
        f"module_prefix = {module_prefix!r}\n"
        f"blocked = {blocked!r}\n"
        "for name in list(sys.modules):\n"
        "    if name.startswith(blocked) or name.startswith(module_prefix):\n"
        "        del sys.modules[name]\n"
        "import v2.backend.app.services.trainer_prediction_output\n"
        "matches = [name for name in sys.modules if name.startswith(blocked)]\n"
        "raise SystemExit(1 if matches else 0)\n"
    )

    result = subprocess.run([sys.executable, "-c", code], check=False)

    assert result.returncode == 0
