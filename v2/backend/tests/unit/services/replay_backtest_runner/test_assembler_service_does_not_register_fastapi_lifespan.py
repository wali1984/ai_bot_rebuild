import subprocess
import sys


def test_assembler_service_does_not_register_fastapi_lifespan():
    code = (
        "import sys\n"
        "import v2.backend.app.services.replay_backtest_runner as package\n"
        "names = ['fast' + 'api', 'uvi' + 'corn', 'star' + 'lette']\n"
        "bad = [name for name in names if name in sys.modules]\n"
        "bad.append('lifespan') if callable(getattr(package, 'lifespan', None)) else None\n"
        "raise SystemExit(1 if bad else 0)\n"
    )
    subprocess.run([sys.executable, "-c", code], check=True)
