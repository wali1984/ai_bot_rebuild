import subprocess
import sys


def test_summary_module_does_not_load_redis_when_imported():
    command = "import sys; import v2.backend.app.domain.replay_backtest_runner.summary; assert 'red' + 'is' not in sys.modules and 'aio' + 'redis' not in sys.modules and 'hire' + 'dis' not in sys.modules"
    result = subprocess.run([sys.executable, "-c", command], check=False)
    assert result.returncode == 0
