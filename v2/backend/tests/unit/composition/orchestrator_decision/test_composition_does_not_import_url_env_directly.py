from pathlib import Path


def test_composition_does_not_import_url_env_directly() -> None:
    root = Path("v2/backend/app/composition/orchestrator_decision")
    token = "url" + "_env"

    assert token not in (root / "runtime.py").read_text()
    assert token not in (root / "__init__.py").read_text()
