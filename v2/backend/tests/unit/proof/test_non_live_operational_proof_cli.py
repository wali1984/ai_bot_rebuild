from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from v2.backend.app.proof import GO_NO_GO_MARKER, REQUIRED_ARTIFACTS


def test_cli_runs_successfully_and_emits_artifacts(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "v2.backend.app.cli.non_live_operational_proof",
            "--output-dir",
            str(tmp_path),
        ],
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    assert GO_NO_GO_MARKER in result.stdout
    assert [name for name in REQUIRED_ARTIFACTS if not (tmp_path / name).exists()] == []
    assert (tmp_path / "GO_NO_GO.md").read_text() == GO_NO_GO_MARKER
