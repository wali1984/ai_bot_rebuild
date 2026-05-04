import v2.backend.app.adapters.redis_v2 as redis_v2_package


def _scrub_factory_milestone_submodules() -> None:
    for name in ("factory", "url_env"):
        if hasattr(redis_v2_package, name):
            delattr(redis_v2_package, name)


def pytest_runtest_setup(item) -> None:
    _scrub_factory_milestone_submodules()


def pytest_runtest_teardown(item, nextitem) -> None:
    _scrub_factory_milestone_submodules()
