import subprocess
import sys


def test_assembler_service_does_not_import_url_env():
    code = (
        "import sys\n"
        "import v2.backend.app.services.replay_backtest_runner\n"
        "name = 'v2.backend.app.adapters.re' + 'dis_v2.url_' + 'env'\n"
        "raise SystemExit(1 if name in sys.modules else 0)\n"
    )
    subprocess.run([sys.executable, "-c", code], check=True)
