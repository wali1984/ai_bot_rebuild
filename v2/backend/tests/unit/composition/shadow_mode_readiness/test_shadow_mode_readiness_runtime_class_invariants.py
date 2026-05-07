import pytest

from v2.backend.app.composition.shadow_mode_readiness import ShadowModeReadinessRuntime


def test_shadow_mode_readiness_runtime_class_invariants():
    instance = ShadowModeReadinessRuntime(shadow_mode_readiness_now=lambda: None)

    assert ShadowModeReadinessRuntime.__slots__ == ("shadow_mode_readiness_now",)
    assert not hasattr(instance, "__dict__")
    with pytest.raises(AttributeError):
        instance.foreign_attribute = True
    public_methods = {
        name
        for name, value in vars(ShadowModeReadinessRuntime).items()
        if callable(value) and not name.startswith("__")
    }
    assert public_methods == set()
    assert "__weakref__" not in ShadowModeReadinessRuntime.__slots__
