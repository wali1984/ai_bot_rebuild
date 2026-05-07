import subprocess
import sys


def test_domain_module_does_not_import_trainer_prediction_output():
    command = "import sys; import v2.backend.app.domain.replay_backtest_runner; assert 'v2.backend.app.domain.trainer_prediction_' + 'output' not in sys.modules"
    result = subprocess.run([sys.executable, "-c", command], check=False)
    assert result.returncode == 0
