import subprocess
import sys


def test_init_module_does_not_load_redis():
    command = "import sys; import v2.backend.app.domain.replay_backtest_runner; assert 'red' + 'is' not in sys.modules and 'red' + 'is.asyncio' not in sys.modules and 'aio' + 'redis' not in sys.modules and 'hire' + 'dis' not in sys.modules"
    result = subprocess.run([sys.executable, "-c", command], check=False)
    assert result.returncode == 0
