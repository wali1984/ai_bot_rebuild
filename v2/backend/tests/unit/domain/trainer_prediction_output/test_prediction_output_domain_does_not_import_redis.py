import subprocess
import sys


def test_prediction_output_domain_does_not_import_redis() -> None:
    code = """
import json
import sys
import v2.backend.app.domain.trainer_prediction_output
blocked = [
    "redis",
    "redis.asyncio",
    "aioredis",
    "hiredis",
    "v2.backend.app.adapters.redis_v2.url_env",
    "v2.backend.app.adapters.redis_v2.factory",
    "fastapi",
    "uvicorn",
]
print(json.dumps([name for name in blocked if name in sys.modules]))
"""
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "[]"
