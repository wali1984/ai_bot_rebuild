import subprocess
import sys


def test_init_module_does_not_load_url_env():
    command = "import sys; import v2.backend.app.domain.replay_backtest_runner; assert 'v2.backend.app.adapters.' + 'red' + 'is_v2.url_env' not in sys.modules"
    result = subprocess.run([sys.executable, "-c", command], check=False)
    assert result.returncode == 0
