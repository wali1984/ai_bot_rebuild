import importlib
import inspect
import sys


def test_composition_does_not_import_url_env_directly():
    url_module = "v2.backend.app.adapters." + "redis_v2." + "url" + "_env"
    factory_module = "v2.backend.app.adapters." + "redis_v2.factory"
    package_module = "v2.backend.app.composition.trainer_parity"
    runtime_module = package_module + ".runtime"
    saved = {
        url_module: sys.modules.get(url_module),
        factory_module: sys.modules.get(factory_module),
        package_module: sys.modules.get(package_module),
        runtime_module: sys.modules.get(runtime_module),
    }
    sys.modules.pop(url_module, None)
    sys.modules.pop(factory_module, None)
    sys.modules.pop(package_module, None)
    sys.modules.pop(runtime_module, None)

    try:
        package = importlib.import_module(package_module)

        assert url_module in sys.modules
        assert getattr(package.runtime, "url" + "_env", None) is None
        assert "url" + "_env" not in inspect.getsource(package.runtime)
    finally:
        for name, module in saved.items():
            sys.modules.pop(name, None)
            if module is not None:
                sys.modules[name] = module
        parent = sys.modules.get("v2.backend.app.composition")
        if parent is not None and saved[package_module] is not None:
            setattr(parent, "trainer_parity", saved[package_module])
        if saved[package_module] is not None and saved[runtime_module] is not None:
            setattr(saved[package_module], "runtime", saved[runtime_module])
