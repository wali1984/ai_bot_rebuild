import ast
import subprocess
import sys


def test_assembler_service_does_not_import_redis():
    code = (
        "import sys\n"
        "import v2.backend.app.services.replay_backtest_runner\n"
        "names = ['re' + 'dis', 're' + 'dis.asyncio', 'aio' + 'redis', "
        "'hi' + 'redis', 'ht' + 'tpx', 'req' + 'uests', 'fast' + 'api', "
        "'uvi' + 'corn', 'star' + 'lette', 'async' + 'io', 'thread' + 'ing', "
        "'v2.backend.app.adapters.re' + 'dis_v2.url_' + 'env']\n"
        "print([name for name in names if name in sys.modules])\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        check=True,
        text=True,
    )

    assert ast.literal_eval(result.stdout.strip()) == []
