import subprocess
import sys


def test_init_module_does_not_register_fastapi_lifespan():
    command = "import sys; import v2.backend.app.domain.replay_backtest_runner; assert 'fast' + 'api' not in sys.modules and 'uvi' + 'corn' not in sys.modules and 'star' + 'lette' not in sys.modules"
    result = subprocess.run([sys.executable, "-c", command], check=False)
    assert result.returncode == 0
