import subprocess
import sys


def test_runtime_module_does_not_load_redis_when_imported():
    token = "red" + "is"
    code = (
        "import sys\n"
        f"token = {token!r}\n"
        "for name in list(sys.modules):\n"
        "    if name.startswith(token) or name.startswith('v2.backend.app.composition.replay_backtest_runner.runtime'):\n"
        "        sys.modules.pop(name, None)\n"
        "import v2.backend.app.composition.replay_backtest_runner.runtime\n"
        "assert not any(name.startswith(token) for name in sys.modules)\n"
    )
    subprocess.run([sys.executable, "-c", code], check=True)
