import subprocess
import sys


def test_assembler_service_does_not_import_redis() -> None:
    code = """
import sys
import v2.backend.app.services.paper_execution_ledger
names = [
    "redis",
    "redis.asyncio",
    "aioredis",
    "hiredis",
    "httpx",
    "requests",
    "fastapi",
    "uvicorn",
    "asyncio",
    "threading",
    "v2.backend.app.adapters.redis_v2.url_env",
]
print([name for name in names if name in sys.modules])
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert result.stdout.strip() == "[]"
