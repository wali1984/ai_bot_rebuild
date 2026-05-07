import subprocess
import sys


def test_domain_module_does_not_import_trainer_prediction_output() -> None:
    code = (
        "import sys; "
        "import v2.backend.app.domain.shadow_mode_readiness; "
        "assert 'v2.backend.app.domain.trainer_prediction_output' not in sys.modules"
    )

    result = subprocess.run([sys.executable, "-c", code], check=False)

    assert result.returncode == 0
