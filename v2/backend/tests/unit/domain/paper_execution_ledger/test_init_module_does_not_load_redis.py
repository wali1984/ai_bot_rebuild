import subprocess
import sys


def test_init_module_does_not_load_redis() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import v2.backend.app.domain.paper_execution_ledger; "
            "assert 'redis' not in sys.modules; "
            "assert 'redis.asyncio' not in sys.modules; "
            "assert 'aioredis' not in sys.modules; "
            "assert 'hiredis' not in sys.modules",
        ],
        check=False,
    )
    assert result.returncode == 0
