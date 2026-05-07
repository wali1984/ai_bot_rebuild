import subprocess
import sys


def test_init_module_does_not_load_url_env():
    token = "url" + "_env"
    code = (
        "import sys\n"
        f"token = {token!r}\n"
        "for name in list(sys.modules):\n"
        "    if token in name or name.startswith('v2.backend.app.composition.replay_backtest_runner'):\n"
        "        sys.modules.pop(name, None)\n"
        "import v2.backend.app.composition.replay_backtest_runner\n"
        "assert not any(token in name for name in sys.modules)\n"
    )
    subprocess.run([sys.executable, "-c", code], check=True)
