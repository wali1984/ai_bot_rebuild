import subprocess
import sys


def test_assembler_service_does_not_import_replay_backtest_runner() -> None:
    code = (
        "import sys\n"
        "import v2.backend.app.services.paper_mode\n"
        "assert 'v2.backend.app.domain.replay_backtest_runner' not in sys.modules\n"
    )
    subprocess.run([sys.executable, "-c", code], check=True)
