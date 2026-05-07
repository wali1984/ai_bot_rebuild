import subprocess
import sys


def test_assembler_service_does_not_register_fastapi_lifespan() -> None:
    code = (
        "import sys\n"
        "import v2.backend.app.services.paper_mode as paper_mode\n"
        "assert 'fastapi' not in sys.modules\n"
        "assert 'uvicorn' not in sys.modules\n"
        "assert 'starlette' not in sys.modules\n"
        "assert not callable(getattr(paper_mode, 'lifespan', None))\n"
    )
    subprocess.run([sys.executable, "-c", code], check=True)
