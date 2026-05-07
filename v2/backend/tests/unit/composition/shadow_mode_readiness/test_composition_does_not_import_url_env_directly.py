from pathlib import Path


def test_composition_does_not_import_url_env_directly():
    target = "url" + "_env"
    root = Path("v2/backend/app/composition/shadow_mode_readiness")

    assert target not in (root / "runtime.py").read_text(encoding="utf-8")
    assert target not in (root / "__init__.py").read_text(encoding="utf-8")
