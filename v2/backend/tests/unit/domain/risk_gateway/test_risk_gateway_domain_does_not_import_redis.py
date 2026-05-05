import subprocess
import sys


def test_importing_domain_package_does_not_load_blocked_modules() -> None:
    names = (
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
    )
    code = (
        "import sys;"
        "import v2.backend.app.domain.risk_gateway;"
        "blocked = " + repr(names) + ";"
        "loaded = [name for name in blocked if name in sys.modules];"
        "raise SystemExit(1 if loaded else 0)"
    )
    result = subprocess.run([sys.executable, "-c", code], check=False)
    assert result.returncode == 0
