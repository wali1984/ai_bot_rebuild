import pytest


def test_paper_mode_runtime_class_invariants():
    from v2.backend.app.composition.paper_mode import PaperModeRuntime

    def paper_mode_now(*, requested_mode: str):
        return requested_mode

    runtime = PaperModeRuntime(paper_mode_now=paper_mode_now)

    assert PaperModeRuntime.__slots__ == ("paper_mode_now",)
    assert not hasattr(runtime, "__dict__")
    with pytest.raises(AttributeError):
        runtime.extra = 1
    public_methods = {
        name
        for name, value in PaperModeRuntime.__dict__.items()
        if callable(value) and not name.startswith("__")
    }
    assert public_methods == set()
    assert "__weakref__" not in PaperModeRuntime.__slots__
