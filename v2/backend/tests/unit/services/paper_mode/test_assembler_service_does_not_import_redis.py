import ast
import subprocess
import sys


def test_assembler_service_does_not_import_redis() -> None:
    code = (
        "import sys\n"
        "import v2.backend.app.services.paper_mode\n"
        "names = [\n"
        "    'redis', 'redis.asyncio', 'aioredis', 'hiredis', 'httpx',\n"
        "    'requests', 'fastapi', 'uvicorn', 'starlette', 'asyncio',\n"
        "    'threading', 'v2.backend.app.adapters.redis_v2.url_env',\n"
        "]\n"
        "print([name for name in names if name in sys.modules])\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        check=True,
        capture_output=True,
        text=True,
    )
    assert ast.literal_eval(result.stdout.strip()) == []
