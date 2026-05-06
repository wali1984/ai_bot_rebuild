import subprocess
import sys


def test_domain_module_does_not_import_trainer_prediction_output() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import v2.backend.app.domain.paper_execution_ledger; "
            "assert 'v2.backend.app.domain.trainer_prediction_output' not in sys.modules",
        ],
        check=False,
    )
    assert result.returncode == 0
