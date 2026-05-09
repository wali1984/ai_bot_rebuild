import sys


def test_init_module_does_not_register_fastapi_lifespan() -> None:
    sys.modules.pop("fastapi", None)
    sys.modules.pop("starlette", None)

    import v2.backend.app.domain.external_manual_position_quarantine  # noqa: F401

    assert "fastapi" not in sys.modules
    assert "starlette" not in sys.modules
