import ast
import subprocess
import sys


def test_assembler_service_does_not_import_redis() -> None:
    code = """
import sys
import v2.backend.app.services.shadow_mode_readiness
forbidden = [
    "redis",
    "redis.asyncio",
    "aioredis",
    "hiredis",
    "httpx",
    "requests",
    "fastapi",
    "uvicorn",
    "starlette",
    "asyncio",
    "threading",
    "v2.backend.app.adapters.redis_v2.url_env",
]
print([name for name in forbidden if name in sys.modules])
"""
    completed = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        check=True,
        text=True,
    )
    assert ast.literal_eval(completed.stdout.strip()) == []
