import subprocess
import sys


def test_domain_module_does_not_import_risk_gateway() -> None:
    code = (
        "import sys; import v2.backend.app.domain.paper_mode; "
        "assert 'v2.backend.app.domain.risk_gateway' not in sys.modules"
    )
    result = subprocess.run([sys.executable, "-c", code], check=False)
    assert result.returncode == 0
