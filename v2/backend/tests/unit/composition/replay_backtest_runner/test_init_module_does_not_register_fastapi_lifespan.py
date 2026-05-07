import subprocess
import sys


def test_init_module_does_not_register_fastapi_lifespan():
    token = "fast" + "api"
    code = (
        "import sys\n"
        f"token = {token!r}\n"
        "for name in list(sys.modules):\n"
        "    if name.startswith(token) or name.startswith('v2.backend.app.composition.replay_backtest_runner'):\n"
        "        sys.modules.pop(name, None)\n"
        "import v2.backend.app.composition.replay_backtest_runner\n"
        "assert not any(name.startswith(token) for name in sys.modules)\n"
    )
    subprocess.run([sys.executable, "-c", code], check=True)
