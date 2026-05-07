from pathlib import Path


def test_composition_does_not_import_url_env_directly():
    forbidden = "url" + "_env"
    root = Path("v2/backend/app/composition/paper_mode")

    assert forbidden not in (root / "runtime.py").read_text()
    assert forbidden not in (root / "__init__.py").read_text()
