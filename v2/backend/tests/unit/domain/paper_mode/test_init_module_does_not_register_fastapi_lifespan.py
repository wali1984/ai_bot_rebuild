import subprocess
import sys


def test_init_module_does_not_register_fastapi_lifespan() -> None:
    code = (
        "import sys; import v2.backend.app.domain.paper_mode; "
        "assert 'fastapi' not in sys.modules; "
        "assert 'uvicorn' not in sys.modules; "
        "assert 'starlette' not in sys.modules"
    )
    result = subprocess.run([sys.executable, "-c", code], check=False)
    assert result.returncode == 0
