import subprocess
import sys


def test_assembler_service_does_not_import_url_env() -> None:
    code = (
        "import sys\n"
        "import v2.backend.app.services.paper_mode\n"
        "assert 'v2.backend.app.adapters.redis_v2.url_env' not in sys.modules\n"
    )
    subprocess.run([sys.executable, "-c", code], check=True)
