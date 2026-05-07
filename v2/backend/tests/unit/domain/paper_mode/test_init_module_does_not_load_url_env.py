import subprocess
import sys


def test_init_module_does_not_load_url_env() -> None:
    code = (
        "import sys; import v2.backend.app.domain.paper_mode; "
        "assert 'v2.backend.app.adapters.redis_v2.url_env' not in sys.modules"
    )
    result = subprocess.run([sys.executable, "-c", code], check=False)
    assert result.returncode == 0
