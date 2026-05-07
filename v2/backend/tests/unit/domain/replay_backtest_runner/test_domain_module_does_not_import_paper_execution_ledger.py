import subprocess
import sys


def test_domain_module_does_not_import_paper_execution_ledger():
    command = "import sys; import v2.backend.app.domain.replay_backtest_runner; assert 'v2.backend.app.domain.paper_execution_' + 'ledger' not in sys.modules"
    result = subprocess.run([sys.executable, "-c", command], check=False)
    assert result.returncode == 0
