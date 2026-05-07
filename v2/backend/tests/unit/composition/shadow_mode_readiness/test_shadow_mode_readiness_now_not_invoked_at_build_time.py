from v2.backend.app.composition.shadow_mode_readiness import (
    build_shadow_mode_readiness_runtime,
)


def test_shadow_mode_readiness_now_not_invoked_at_build_time():
    calls = [0]
    flags = []

    def clock():
        calls[0] += 1
        flags.append("flag")
        return 123

    build_shadow_mode_readiness_runtime(now_ms_clock=clock)

    assert calls == [0]
    assert flags == []
