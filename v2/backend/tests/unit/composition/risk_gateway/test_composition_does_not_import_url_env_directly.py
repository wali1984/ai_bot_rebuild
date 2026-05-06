from pathlib import Path


def test_composition_does_not_import_url_env_directly():
    package_dir = Path(__file__).parents[4] / "app" / "composition" / "risk_gateway"
    token = "url" + "_env"

    assert token not in (package_dir / "__init__.py").read_text(encoding="utf-8")
    assert token not in (package_dir / "runtime.py").read_text(encoding="utf-8")
