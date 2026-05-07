import subprocess
import sys


def test_init_module_does_not_load_redis() -> None:
    code = (
        "import sys; "
        "import v2.backend.app.domain.shadow_mode_readiness; "
        "assert 'redis' not in sys.modules; "
        "assert 'redis.asyncio' not in sys.modules; "
        "assert 'aioredis' not in sys.modules; "
        "assert 'hiredis' not in sys.modules"
    )

    result = subprocess.run([sys.executable, "-c", code], check=False)

    assert result.returncode == 0
