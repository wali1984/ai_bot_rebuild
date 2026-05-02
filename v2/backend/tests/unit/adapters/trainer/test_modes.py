from v2.backend.app.adapters.trainer import ALLOWED_MODES, TrainerSubprocessMode


def test_modes_enum_membership_is_exactly_three():
    assert list(TrainerSubprocessMode) == [
        TrainerSubprocessMode.READ_ONLY,
        TrainerSubprocessMode.STATUS,
        TrainerSubprocessMode.EXPORT,
    ]


def test_modes_enum_values_match_subprocess_argv(adapter, fake_runner):
    adapter.invoke(task_id="task1", mode=TrainerSubprocessMode.READ_ONLY)
    assert fake_runner.calls[0].argv == [
        adapter._legacy_python_path,
        adapter._legacy_script_path,
        "--mode",
        "read_only",
    ]


def test_modes_allowed_modes_frozenset_matches_enum():
    assert ALLOWED_MODES == frozenset(mode.value for mode in TrainerSubprocessMode)
